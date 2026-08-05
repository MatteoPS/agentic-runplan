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

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from mc import sync

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
CADENCE_NOTE_SPM = 5.0


@dataclass(frozen=True)
class RunMetrics:
    """One running activity, with the fields that were previously dropped."""

    day: date
    label: str  # "DD-MM HH:MM", matching the digest's activity log
    distance_mi: float | None
    duration_min: float | None
    avg_hr: float | None
    pace_min_per_mi: float | None
    gap_min_per_mi: float | None
    cadence_spm: float | None
    elev_gain_ft: float | None
    elev_loss_ft: float | None

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

    return RunMetrics(
        day=dt.date(),
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
    lines = [
        "| Date | Distance | Pace | GAP | Terrain | Cadence | Elev gain |",
        "|---|---|---|---|---|---|---|",
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
            f"| {f'{r.elev_gain_ft:.0f} ft' if r.elev_gain_ft else '—'} |"
        )
    return lines


def form_summary_lines(
    rows: list[RunMetrics], baseline: CadenceBaseline
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

    notes = [n for r in rows[:3] if (n := cadence_note(r, baseline))]
    lines += [f"- {n}" for n in notes]
    if not notes and baseline.usable:
        lines.append("- No recent run more than 5 spm below that baseline.")

    lines.append(
        "- GAP is Garmin's grade-adjusted pace; *Terrain* is what the route "
        "cost against flat. Descriptive only — no §6 rule reads these (D6)."
    )
    return lines
