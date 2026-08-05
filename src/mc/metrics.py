"""Garmin fields that were already being fetched and then thrown away.

`get_activities_by_date` — one call, made on every `mc sync` since day one —
returns a much richer per-activity summary than the four fields the rest of
this system reads (distance, duration, avg HR, start time). Cadence, elevation
gain/loss and Garmin's own grade-adjusted speed have been sitting unused in
`data/raw/garmin/activities/latest.json` the whole time. Reading them costs
**zero additional API calls**, which is the entire reason this module exists
rather than a new pull in `garmin.py`.

What's here and why:

- **Cadence** (`averageRunningCadenceInStepsPerMinute`). The one metric with a
  real claim on §6: D2 ("any pain that changes my gait") is currently pure
  self-report, and cadence is the cheapest objective proxy for form changing
  under fatigue or discomfort. It is a *proxy*, not a diagnosis — see the
  caveat below.
- **Elevation gain/loss** (metres → feet). Makes a slow mile on a hilly route
  legible as terrain rather than as lost fitness.
- **Grade-adjusted pace** (`avgGradeAdjustedSpeed`, m/s). Garmin's own
  flat-equivalent pace. Reported next to raw pace so the two can disagree
  visibly; the delta is the terrain's cost in sec/mile.

Deliberately **not** here, though the same payload carries them:

- `minTemperature`/`maxTemperature` — a wrist sensor sitting against a warm
  arm in the sun. It measures the watch, not the air. `weather.py` answers
  the question this field looks like it answers, with real ambient data.
- `avgStrideLength`, `avgGroundContactTime`, `avgVerticalOscillation`,
  `avgVerticalRatio` — no §6 rule reads them, and nothing in this plan defines
  what a bad value would even be. Adding numbers nobody can act on is how a
  digest stops being read. They stay in the raw cache, available the day
  there's a question that needs them.

**These are descriptive, not diagnostic (§6 D6).** Cadence tracks pace,
terrain and fatigue all at once, so a drop is a fact about a run, never a
verdict about a body. Everything below reports numbers and deltas; nothing
here decides anything, and no §6 rule consumes it.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from mc import config as cfg
from mc import sync
from mc.weather import HourlyWeather, weather_at

FEET_PER_METER = 3.280839895

FORM_WINDOW_DAYS = 14
BASELINE_WINDOW_DAYS = 28

# Below this many runs the median is noise, so it's reported as "not enough
# runs yet" rather than as a baseline. 4 is roughly one week of this plan.
MIN_BASELINE_RUNS = 4

# What counts as a cadence gap worth printing a note about. Individual cadence
# at a given pace is stable to within a step or two, so ~5 spm (≈3%) is a real
# shift rather than measurement wobble — but it's a threshold chosen by
# judgment, not from a study, in the same spirit as equivalence.py's verdict
# cutoffs. Its only job is deciding whether a line gets printed.
#
# Checked against real data 04-08-2026 and it holds up better here than it
# would for most runners: across paces from 8:48 to 9:32 — 44 s/mi apart —
# this athlete's per-run cadence moved only 165→168 spm. Cadence being nearly
# pace-independent is what makes a flat baseline usable at all; for someone
# whose cadence swung 10 spm with pace it would need banding by pace first.
CADENCE_NOTE_SPM = 5.0

# Within a single run, comparing its own thirds, the noise floor is lower than
# it is between runs — same shoes, same route, same day. 4 spm is the judgment
# call here, on the same footing as the threshold above.
DECAY_NOTE_SPM = 4.0

# Below this, thirds are too short for the comparison to mean anything, and
# "did form hold up late in a long run" isn't a question a 2-miler asks.
MIN_DECAY_DISTANCE_MI = 5.0

# How much slower than the trailing median a run has to be before it's worth
# asking about. Generous on purpose: this fires a question, and a question
# that fires on every ordinary easy day is one that stops being read.
PACE_NOTE_SEC_PER_MI = 30.0


@dataclass(frozen=True)
class RunMetrics:
    """One running activity, with the fields that were previously dropped."""

    day: date
    start: datetime
    activity_id: str | None
    label: str  # "DD-MM HH:MM", matching the digest's activity log
    distance_mi: float | None
    duration_min: float | None
    avg_hr: float | None
    pace_min_per_mi: float | None
    gap_min_per_mi: float | None
    cadence_spm: float | None
    elev_gain_ft: float | None
    elev_loss_ft: float | None
    # Filled by enrich_with_weather, never fetched here — keeping this module
    # free of I/O is what lets every function below be tested on plain dicts.
    feels_like_f: float | None = None
    dew_point_f: float | None = None

    @property
    def terrain_cost_sec_per_mi(self) -> float | None:
        """Raw pace minus grade-adjusted pace, in sec/mile.

        Positive: the route cost you time versus flat. Negative: net descent
        flattered the raw number. Near zero on a flat route, which is the
        common case and worth being able to see at a glance.
        """
        if self.pace_min_per_mi is None or self.gap_min_per_mi is None:
            return None
        return (self.pace_min_per_mi - self.gap_min_per_mi) * 60


@dataclass(frozen=True)
class CadenceBaseline:
    median_spm: float | None
    n_runs: int
    window_days: int

    @property
    def usable(self) -> bool:
        return self.median_spm is not None and self.n_runs >= MIN_BASELINE_RUNS


def _speed_to_pace(speed_m_s: float | None) -> float | None:
    """m/s → min/mile. Zero means 'no data' on a real activity, same
    convention as sync._normalize_zero."""
    if not speed_m_s or speed_m_s <= 0:
        return None
    return (sync.MILE_M / speed_m_s) / 60


def _metres_to_feet(value: float | None) -> float | None:
    if value is None:
        return None
    return value * FEET_PER_METER


def _positive(value: Any) -> float | None:
    """Garmin writes 0 rather than omitting a field it has no reading for."""
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    return as_float if as_float > 0 else None


def build_run_metrics(activity: dict[str, Any]) -> RunMetrics | None:
    dt = sync.parse_garmin_local_start(activity)
    if dt is None:
        return None

    distance_m = _positive(activity.get("distance"))
    duration_s = _positive(activity.get("duration"))
    distance_mi = distance_m / sync.MILE_M if distance_m else None
    duration_min = duration_s / 60 if duration_s else None

    # Pace from distance/duration rather than Garmin's `averageSpeed`, so it
    # agrees with every other mileage number this system prints. Verified
    # against real activities: the two match, because `duration` here is
    # already moving time for a run.
    pace = duration_min / distance_mi if distance_mi and duration_min else None

    activity_id = activity.get("activityId")
    return RunMetrics(
        day=dt.date(),
        start=dt,
        activity_id=str(activity_id) if activity_id is not None else None,
        label=dt.strftime("%d-%m %H:%M"),
        distance_mi=distance_mi,
        duration_min=duration_min,
        avg_hr=_positive(activity.get("averageHR")),
        pace_min_per_mi=pace,
        gap_min_per_mi=_speed_to_pace(_positive(activity.get("avgGradeAdjustedSpeed"))),
        cadence_spm=_positive(activity.get("averageRunningCadenceInStepsPerMinute")),
        elev_gain_ft=_metres_to_feet(_positive(activity.get("elevationGain"))),
        elev_loss_ft=_metres_to_feet(_positive(activity.get("elevationLoss"))),
    )


def run_metrics(
    garmin_activities: list[dict[str, Any]], as_of: date, days: int = FORM_WINDOW_DAYS
) -> list[RunMetrics]:
    """Running activities in the trailing `days` window, newest first."""
    cutoff = as_of - timedelta(days=days)
    rows: list[RunMetrics] = []
    for a in garmin_activities:
        bucket = sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        )
        if bucket != "run":
            continue
        row = build_run_metrics(a)
        if row is None or not (cutoff <= row.day <= as_of):
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r.day, r.label), reverse=True)
    return rows


def cadence_baseline(
    garmin_activities: list[dict[str, Any]],
    as_of: date,
    days: int = BASELINE_WINDOW_DAYS,
) -> CadenceBaseline:
    """Median cadence across the trailing window's runs.

    Median rather than mean: one treadmill shuffle or a run cut short at a
    traffic light shouldn't drag the reference point.
    """
    values = [
        r.cadence_spm
        for r in run_metrics(garmin_activities, as_of, days=days)
        if r.cadence_spm is not None
    ]
    return CadenceBaseline(
        median_spm=round(statistics.median(values), 1) if values else None,
        n_runs=len(values),
        window_days=days,
    )


def pace_baseline(
    garmin_activities: list[dict[str, Any]],
    as_of: date,
    days: int = BASELINE_WINDOW_DAYS,
) -> float | None:
    """Median grade-adjusted pace over the trailing window, min/mile.

    GAP rather than raw pace so a hilly fortnight doesn't move the reference
    point. This deliberately mixes session types — nothing in the Garmin
    summary says whether a run was meant to be easy or hard — which is exactly
    why PACE_NOTE_SEC_PER_MI is set wide enough that only real outliers trip
    it, and why the note it produces asks a question instead of drawing a
    conclusion.
    """
    values = [
        r.gap_min_per_mi or r.pace_min_per_mi
        for r in run_metrics(garmin_activities, as_of, days=days)
        if (r.gap_min_per_mi or r.pace_min_per_mi) is not None
    ]
    return statistics.median(values) if len(values) >= MIN_BASELINE_RUNS else None


# --- weather attribution -------------------------------------------------------


def enrich_with_weather(
    rows: list[RunMetrics], hours: list[HourlyWeather]
) -> list[RunMetrics]:
    """Attach the conditions each run actually happened in.

    A pure join, taking the hours as an argument rather than reading the cache,
    so the whole module stays I/O-free and testable on literals. Runs the
    weather cache doesn't cover keep None and are reported as unknown.
    """
    out: list[RunMetrics] = []
    for row in rows:
        hour = weather_at(hours, row.start)
        out.append(
            row
            if hour is None
            else replace(row, feels_like_f=hour.feels_like_f, dew_point_f=hour.dew_point_f)
        )
    return out


def _sentence(clause: str) -> str:
    """Upper-cases the first character only. str.capitalize() would lowercase
    the rest, which turns "65°F" into "65°f"."""
    return clause[:1].upper() + clause[1:]


def conditions_clause(row: RunMetrics) -> str:
    """The air that run happened in, as a phrase to append to a note.

    Never phrased as a cause. Heat plausibly explains a slow run and it is
    also the easiest thing in this system to hide behind — §6 E3 says never
    soften the framing, and "it was hot" is the softest framing available. So
    this states the numbers and leaves the causal claim to be confirmed by the
    only witness who was there.
    """
    from mc.weather import fmt_temp

    if row.dew_point_f is None and row.feels_like_f is None:
        return "conditions unknown (outside the cached weather window)"
    return (
        f"conditions were {fmt_temp(row.feels_like_f)} feels-like at a "
        f"{fmt_temp(row.dew_point_f)} dew point"
    )


# --- within-run cadence decay ----------------------------------------------------


@dataclass(frozen=True)
class CadenceSplits:
    """Median cadence over the first, middle and final third of a run, split
    by distance covered."""

    first: float | None
    middle: float | None
    last: float | None
    n_samples: int

    @property
    def drift_spm(self) -> float | None:
        """Final third minus first third. Negative means cadence fell."""
        if self.first is None or self.last is None:
            return None
        return round(self.last - self.first, 1)


def _details_path(activity_id: str):
    return cfg.RAW_GARMIN_DIR / "activities" / "details" / f"{activity_id}.json"


def cadence_splits(activity_id: str | None) -> CadenceSplits | None:
    """Per-sample cadence from the already-cached activity detail payload.

    `get_activity_details` has been called and written to disk for every
    activity since this system's first sync — this reads that file. **Zero API
    calls.**

    Splitting by distance rather than elapsed time keeps a long red light from
    counting as a third of the run. Medians, not means, so a few walk or
    stopped samples don't drag a third. Metrics are looked up by key name
    because the index order genuinely varies between activities (a real
    payload here has 9 metrics, another has 17).

    One honest bias: the first third includes any warmup ramp, which pulls its
    median down and therefore makes decay look *smaller* than it was. The
    error runs toward saying nothing, which is the right direction for a
    number that exists to raise a question.
    """
    if not activity_id:
        return None
    path = _details_path(activity_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())["data"]
        descriptors = {m["key"]: m["metricsIndex"] for m in payload["metricDescriptors"]}
        rows = payload["activityDetailMetrics"]
    except (KeyError, TypeError, ValueError):
        return None

    cadence_idx = descriptors.get("directDoubleCadence")
    distance_idx = descriptors.get("sumDistance")
    if cadence_idx is None or distance_idx is None:
        return None

    samples: list[tuple[float, float]] = []
    for row in rows:
        values = row.get("metrics") or []
        if len(values) <= max(cadence_idx, distance_idx):
            continue
        cadence, distance = values[cadence_idx], values[distance_idx]
        if cadence is None or distance is None or cadence <= 0:
            continue
        samples.append((float(distance), float(cadence)))

    if len(samples) < 30:  # a run too short or too sparsely sampled to split
        return None

    samples.sort(key=lambda s: s[0])
    total = samples[-1][0]
    if total <= 0:
        return None

    thirds: list[list[float]] = [[], [], []]
    for distance, cadence in samples:
        index = min(2, int(distance / total * 3))
        thirds[index].append(cadence)

    def median_of(values: list[float]) -> float | None:
        return round(statistics.median(values), 1) if values else None

    return CadenceSplits(
        first=median_of(thirds[0]),
        middle=median_of(thirds[1]),
        last=median_of(thirds[2]),
        n_samples=len(samples),
    )


def decay_note(row: RunMetrics, splits: CadenceSplits | None) -> str | None:
    """Whether form held together late in a long run.

    This is the question the per-activity average cannot answer: 166 spm for a
    10-mile run is equally consistent with holding 166 throughout and with
    running 172 then 160.
    """
    if splits is None or splits.drift_spm is None:
        return None
    if row.distance_mi is None or row.distance_mi < MIN_DECAY_DISTANCE_MI:
        return None
    if splits.drift_spm > -DECAY_NOTE_SPM:
        return None
    return (
        f"{row.label} ({row.distance_mi:.1f} mi): cadence {splits.first:.0f} → "
        f"{splits.last:.0f} spm first third to last ({splits.drift_spm:+.0f}). "
        f"{_sentence(conditions_clause(row))}. Worth asking how the last "
        f"few miles felt — this is a number, not a finding."
    )


def pace_note(row: RunMetrics, baseline_gap: float | None) -> str | None:
    """Fires only on a genuine pace outlier, and asks rather than concludes.

    The conditions are quoted because heat is a real and frequently correct
    explanation for a slow run — and precisely because it's the most
    convenient one, this hands it over as a question to confirm, not as a
    verdict already reached.
    """
    if baseline_gap is None:
        return None
    actual = row.gap_min_per_mi or row.pace_min_per_mi
    if actual is None:
        return None
    delta_sec = (actual - baseline_gap) * 60
    if delta_sec < PACE_NOTE_SEC_PER_MI:
        return None
    return (
        f"{row.label}: {_fmt_pace(actual)} grade-adjusted, {delta_sec:.0f} s/mi "
        f"slower than the {BASELINE_WINDOW_DAYS}-day median of "
        f"{_fmt_pace(baseline_gap)}. {_sentence(conditions_clause(row))}. "
        f"Ask before reading anything into it: was it hot, was it meant to be "
        f"easy, did something hurt?"
    )


def cadence_note(row: RunMetrics, baseline: CadenceBaseline) -> str | None:
    """A neutral sentence when a run's cadence sits well below baseline.

    Pace is always quoted alongside, because the single most likely
    explanation for lower cadence is simply running slower — stating the
    deviation without it would manufacture a worry out of an easy day. This
    reports the gap; deciding whether it means anything is the /daily
    conversation's job, with §6 D1-D3 in hand.
    """
    if not baseline.usable or row.cadence_spm is None or baseline.median_spm is None:
        return None
    delta = row.cadence_spm - baseline.median_spm
    if delta > -CADENCE_NOTE_SPM:
        return None
    pace = (
        f", at {_fmt_pace(row.pace_min_per_mi)} min/mi"
        if row.pace_min_per_mi is not None
        else ""
    )
    return (
        f"{row.label}: cadence {row.cadence_spm:.0f} spm, {abs(delta):.0f} below the "
        f"{baseline.window_days}-day median of {baseline.median_spm:.0f}{pace}. "
        f"Cadence falls with pace and on hills — a number, not a finding."
    )


def _fmt_pace(pace_min_per_mi: float | None) -> str:
    if pace_min_per_mi is None:
        return "—"
    minutes = int(pace_min_per_mi)
    seconds = round((pace_min_per_mi - minutes) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}"


# --- markdown rendering (consumed by digest.py) ---------------------------------


def form_table(rows: list[RunMetrics]) -> list[str]:
    if not rows:
        return [f"_No runs in the last {FORM_WINDOW_DAYS} days._"]
    from mc.weather import fmt_temp

    lines = [
        "| Date | Distance | Pace | GAP | Terrain | Cadence | Elev gain | Dew pt |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        terrain = r.terrain_cost_sec_per_mi
        lines.append(
            f"| {r.label} "
            f"| {f'{r.distance_mi:.1f} mi' if r.distance_mi else '—'} "
            f"| {_fmt_pace(r.pace_min_per_mi)} "
            f"| {_fmt_pace(r.gap_min_per_mi)} "
            f"| {f'{terrain:+.0f} s/mi' if terrain is not None else '—'} "
            f"| {f'{r.cadence_spm:.0f} spm' if r.cadence_spm else '—'} "
            f"| {f'{r.elev_gain_ft:.0f} ft' if r.elev_gain_ft else '—'} "
            f"| {fmt_temp(r.dew_point_f)} |"
        )
    return lines


def form_summary_lines(
    rows: list[RunMetrics],
    baseline: CadenceBaseline,
    baseline_gap: float | None = None,
    splits_by_id: dict[str, CadenceSplits | None] | None = None,
) -> list[str]:
    lines: list[str] = []
    if baseline.usable and baseline.median_spm is not None:
        lines.append(
            f"- Cadence baseline: {baseline.median_spm:.0f} spm "
            f"(median of {baseline.n_runs} runs, last {baseline.window_days}d)"
        )
    else:
        lines.append(
            f"- Cadence baseline: not enough runs with cadence data yet "
            f"({baseline.n_runs} in the last {baseline.window_days}d, need "
            f"{MIN_BASELINE_RUNS})"
        )
    if baseline_gap is not None:
        lines.append(
            f"- Grade-adjusted pace baseline: {_fmt_pace(baseline_gap)} /mi "
            f"(median, last {BASELINE_WINDOW_DAYS}d, all session types mixed)"
        )

    splits_by_id = splits_by_id or {}
    notes: list[str] = []
    for r in rows[:5]:
        notes += [
            n
            for n in (
                cadence_note(r, baseline),
                decay_note(r, splits_by_id.get(r.activity_id or "")),
                pace_note(r, baseline_gap),
            )
            if n
        ]
    lines += [f"- {n}" for n in notes]
    if not notes and baseline.usable:
        lines.append(
            "- Nothing standing out: no run below the cadence baseline, no "
            "late-run cadence fade, no pace outlier."
        )

    lines.append(
        "- GAP is Garmin's grade-adjusted pace; *Terrain* is what the route "
        "cost against flat; *Dew pt* is the air that run actually happened in. "
        "Descriptive only — no §6 rule reads these (D6), and heat is a "
        "question to confirm, never a conclusion or an excuse (E3)."
    )
    return lines
