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
- `avgGroundContactTime`, `avgVerticalOscillation`, `avgVerticalRatio` — no §6
  rule reads them, and nothing in this plan defines what a bad value would even
  be. Adding numbers nobody can act on is how a digest stops being read. They
  stay in the raw cache, available the day there's a question that needs them.

**Stride length** was on that list until 05-08-2026, when a question arrived
that needed it. Reviewing the 2025 NYC marathon lap file showed cadence *rising*
over the final three miles (160 → 166-169 spm) while stride length fell 0.966m
→ 0.845m — the within-run decay check, keyed on cadence alone, would have said
nothing about the most instructive run in this athlete's history. Stride is
where a tiring runner actually gives up ground. It is read per-sample in
`run_splits` only, not as a per-run average: the average has the same problem
the cadence average had.

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

# Stride length is the metric cadence cannot stand in for. In the 2025 NYC
# marathon (4:48:58, a 17-minute positive split) cadence *rose* — 160 spm
# through Brooklyn, 166-169 over the last three miles — while stride length
# fell 0.966m → 0.845m. A cadence-only decay check would have reported nothing
# about the run that most needed reporting. 5% is set above the swing an easy
# run shows from pace alone, so this fires on a genuine shortening.
DECAY_NOTE_STRIDE_PCT = 5.0

# Grade-adjusted pace across the thirds is *reported* but deliberately does not
# *trigger* the note on its own. Checked against the real cache 05-08-2026: a
# warmup and a cooldown live in the first and last thirds, so a structured run
# shows a large apparent fade with no fade in it — 23369959611 goes 9:01 → 7:28
# → 10:06, which is a workout, not a collapse. Every threshold in this module
# errs toward saying nothing; pace decay is the one that would err the other
# way, so it earns its place as context next to a cadence or stride trip rather
# than as a trigger. This bound only decides whether the clause is worth
# printing once the note is already firing.
GAP_CLAUSE_SEC_PER_MI = 10.0

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


# --- within-run decay ------------------------------------------------------------

# Below this a sample is standing still, not striding — a red light, not a step.
_MIN_MOVING_SPEED_MS = 0.5


@dataclass(frozen=True)
class Thirds:
    """One metric's median over the first, middle and final third of a run."""

    first: float | None
    middle: float | None
    last: float | None

    @property
    def drift(self) -> float | None:
        """Final third minus first third. Sign is the metric's own."""
        if self.first is None or self.last is None:
            return None
        return self.last - self.first

    @property
    def drift_pct(self) -> float | None:
        drift = self.drift
        if drift is None or not self.first:
            return None
        return drift / self.first * 100.0


@dataclass(frozen=True)
class RunSplits:
    """How cadence, stride length and pace moved across a run's three thirds.

    Cadence alone answers less than it appears to. Stride length is where a
    tiring runner actually gives up ground, and grade-adjusted pace says
    whether the terrain explains it. All three come from the same cached
    payload, so carrying them costs nothing.
    """

    cadence: Thirds  # spm
    stride: Thirds  # metres per step
    gap: Thirds  # min/mi, grade-adjusted
    pace: Thirds  # min/mi, raw
    n_samples: int

    @property
    def drift_spm(self) -> float | None:
        drift = self.cadence.drift
        return None if drift is None else round(drift, 1)

    @property
    def stride_drift_pct(self) -> float | None:
        pct = self.stride.drift_pct
        return None if pct is None else round(pct, 1)

    @property
    def gap_drift_sec(self) -> float | None:
        """Positive means the last third was slower, terrain accounted for."""
        drift = self.gap.drift
        return None if drift is None else round(drift * 60, 0)

    def terrain_cost_sec_per_mi(self, third: str) -> float | None:
        """Raw pace minus grade-adjusted pace for one third, in sec/mile.

        The within-run version of `RunMetrics.terrain_cost_sec_per_mi`, and the
        thing that separates "the last third was uphill" from "the last third
        was slower". Positive: that stretch cost time against flat.
        """
        raw = getattr(self.pace, third)
        gap = getattr(self.gap, third)
        if raw is None or gap is None:
            return None
        return round((raw - gap) * 60, 0)


def _details_path(activity_id: str):
    return cfg.RAW_GARMIN_DIR / "activities" / "details" / f"{activity_id}.json"


def run_splits(activity_id: str | None) -> RunSplits | None:
    """Per-sample form metrics from the already-cached activity detail payload.

    `get_activity_details` has been called and written to disk for every
    activity since this system's first sync — this reads that file. **Zero API
    calls.** `directStrideLength` and `directGradeAdjustedSpeed` ship in the
    same payload as cadence, so widening this from cadence alone added no
    request to any rate budget.

    Splitting by distance rather than elapsed time keeps a long red light from
    counting as a third of the run. Medians, not means, so a few walk or
    stopped samples don't drag a third. Metrics are looked up by key name
    because the index order genuinely varies between activities (a real
    payload here has 9 metrics, another has 17), and every stream but cadence
    and distance is optional — an older cached payload simply reports `None`
    for the thirds it cannot fill.

    One honest bias: the first third includes any warmup ramp, which pulls its
    cadence and stride medians down and its paces up, and therefore makes
    decay look *smaller* than it was on all three. The error runs toward
    saying nothing, which is the right direction for numbers that exist to
    raise a question.
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
    stride_idx = descriptors.get("directStrideLength")
    gap_idx = descriptors.get("directGradeAdjustedSpeed")
    speed_idx = descriptors.get("directSpeed")

    def value_at(values: list[Any], index: int | None) -> float | None:
        if index is None or len(values) <= index:
            return None
        raw = values[index]
        return None if raw is None else float(raw)

    # (distance, cadence, stride_m, gap_speed_ms, speed_ms)
    samples: list[tuple[float, float, float | None, float | None, float | None]] = []
    for row in rows:
        values = row.get("metrics") or []
        cadence = value_at(values, cadence_idx)
        distance = value_at(values, distance_idx)
        if cadence is None or distance is None or cadence <= 0:
            continue
        stride_cm = value_at(values, stride_idx)
        gap_speed = value_at(values, gap_idx)
        speed = value_at(values, speed_idx)
        samples.append(
            (
                distance,
                cadence,
                stride_cm / 100.0 if stride_cm and stride_cm > 0 else None,
                gap_speed if gap_speed and gap_speed > _MIN_MOVING_SPEED_MS else None,
                speed if speed and speed > _MIN_MOVING_SPEED_MS else None,
            )
        )

    if len(samples) < 30:  # a run too short or too sparsely sampled to split
        return None

    samples.sort(key=lambda s: s[0])
    total = samples[-1][0]
    if total <= 0:
        return None

    buckets: list[list[tuple[float, float | None, float | None, float | None]]]
    buckets = [[], [], []]
    for distance, cadence, stride, gap_speed, speed in samples:
        index = min(2, int(distance / total * 3))
        buckets[index].append((cadence, stride, gap_speed, speed))

    def thirds_of(field: int, convert=None) -> Thirds:
        out: list[float | None] = []
        for bucket in buckets:
            values = [row[field] for row in bucket if row[field] is not None]
            if not values:
                out.append(None)
                continue
            median = statistics.median(values)
            converted = convert(median) if convert else median
            out.append(None if converted is None else round(converted, 3))
        return Thirds(*out)

    # Median the speed, then convert — a median of paces would be skewed by the
    # near-zero speeds that produce enormous min/mi values.
    return RunSplits(
        cadence=thirds_of(0),
        stride=thirds_of(1),
        gap=thirds_of(2, _speed_to_pace),
        pace=thirds_of(3, _speed_to_pace),
        n_samples=len(samples),
    )


def decay_note(row: RunMetrics, splits: RunSplits | None) -> str | None:
    """Whether form held together late in a long run.

    This is the question the per-activity average cannot answer: 166 spm for a
    10-mile run is equally consistent with holding 166 throughout and with
    running 172 then 160.

    Cadence and stride length each trip it independently. The most informative
    case in this athlete's history is the one where cadence *held* — rose, in
    fact — and stride collapsed, so requiring the two to agree would suppress
    exactly the run worth asking about.

    Grade-adjusted pace rides along as context rather than as a trigger; see
    `GAP_CLAUSE_SEC_PER_MI` for why. The per-third terrain cost is printed with
    it so "the last third was uphill" stays distinguishable from "the last
    third was slower".
    """
    if splits is None:
        return None
    if row.distance_mi is None or row.distance_mi < MIN_DECAY_DISTANCE_MI:
        return None

    cadence_drift = splits.drift_spm
    stride_drift = splits.stride_drift_pct
    gap_drift = splits.gap_drift_sec

    tripped = (cadence_drift is not None and cadence_drift <= -DECAY_NOTE_SPM) or (
        stride_drift is not None and stride_drift <= -DECAY_NOTE_STRIDE_PCT
    )
    if not tripped:
        return None

    parts: list[str] = []
    if cadence_drift is not None:
        parts.append(
            f"cadence {splits.cadence.first:.0f} → {splits.cadence.last:.0f} spm "
            f"({cadence_drift:+.0f})"
        )
    if stride_drift is not None:
        parts.append(
            f"stride {splits.stride.first:.2f} → {splits.stride.last:.2f} m "
            f"({stride_drift:+.1f}%)"
        )
    if gap_drift is not None and abs(gap_drift) >= GAP_CLAUSE_SEC_PER_MI:
        first_cost = splits.terrain_cost_sec_per_mi("first")
        last_cost = splits.terrain_cost_sec_per_mi("last")
        terrain = ""
        if first_cost is not None and last_cost is not None:
            terrain = f", terrain {first_cost:+.0f} → {last_cost:+.0f} s/mi"
        parts.append(
            f"grade-adjusted pace {_fmt_pace(splits.gap.first)} → "
            f"{_fmt_pace(splits.gap.last)} /mi ({gap_drift:+.0f} s/mi{terrain})"
        )

    return (
        f"{row.label} ({row.distance_mi:.1f} mi), first third to last: "
        f"{'; '.join(parts)}. {_sentence(conditions_clause(row))}. "
        f"{_decay_pattern(cadence_drift, stride_drift)} Worth asking how the "
        f"last few miles felt — these are numbers, not a finding, and a warmup "
        f"or cooldown sits inside these thirds."
    )


def _decay_pattern(cadence_drift: float | None, stride_drift: float | None) -> str:
    """Name which of the two fell, because they mean different things.

    Turnover and ground covered per step fail independently, and the pairing is
    more informative than either number. Cadence easing while stride holds is
    what deliberately backing off looks like; stride shortening while cadence
    holds is the one that cost this athlete 17 minutes at NYC in 2025. Still a
    description of a run, never a verdict about a body (§6 D6).
    """
    if stride_drift is None:
        return ""
    cadence_fell = cadence_drift is not None and cadence_drift <= -DECAY_NOTE_SPM
    stride_fell = stride_drift <= -DECAY_NOTE_STRIDE_PCT
    if stride_fell and not cadence_fell:
        return (
            "Stride shortened while cadence held — ground per step, not "
            "turnover, which is the pattern most worth asking about."
        )
    if stride_fell and cadence_fell:
        return "Both fell, so the whole stride shortened rather than just its rate."
    if cadence_fell:
        return (
            "Cadence eased while stride held, which looks more like backing "
            "off or a cooldown than like fade."
        )
    return ""


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
    splits_by_id: dict[str, RunSplits | None] | None = None,
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
            "late-run cadence or stride fade, no pace outlier."
        )

    lines.append(
        "- GAP is Garmin's grade-adjusted pace; *Terrain* is what the route "
        "cost against flat; *Dew pt* is the air that run actually happened in. "
        "Descriptive only — no §6 rule reads these (D6), and heat is a "
        "question to confirm, never a conclusion or an excuse (E3)."
    )
    return lines
