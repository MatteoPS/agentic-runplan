from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from mc import config as cfg
from mc import intervals
from mc import sync

# Order sections/rows appear in — run/cross are what I actually do
# (per my profile), everything else trails.
TYPE_ORDER = ["run", "cross", "bike", "strength", "walk", "row", "other"]

RECENT_LOG_DAYS = 14
ROLLING_WINDOWS_DAYS = (7, 14, 28)


# --- loading cached data --------------------------------------------------------


def _load_latest(raw_dir: Path, category: str) -> list[dict[str, Any]]:
    path = raw_dir / category / "latest.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())["data"]
    except Exception:  # noqa: BLE001
        return []


def load_sync_report() -> sync.SyncReport | None:
    if not cfg.SYNC_REPORT_PATH.exists():
        return None
    try:
        return sync.SyncReport.model_validate_json(cfg.SYNC_REPORT_PATH.read_text())
    except Exception:  # noqa: BLE001
        return None


def latest_garmin_wellness_value(
    metric: str, as_of: date, lookback_days: int = 7
) -> tuple[str, Any] | None:
    """Most recent day at or before as_of (within lookback_days) that actually
    has non-empty data for this metric — as_of itself often has no data yet
    (watch not synced), so we walk backward rather than assuming it's
    populated."""
    metric_dir = cfg.RAW_GARMIN_DIR / "wellness" / metric
    if not metric_dir.exists():
        return None
    for offset in range(lookback_days):
        d = (as_of - timedelta(days=offset)).isoformat()
        f = metric_dir / f"{d}.json"
        if not f.exists():
            continue
        try:
            payload = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        data = payload.get("data")
        if data not in (None, [], {}):
            return d, data
    return None


# --- time-of-day extraction (build-order step 3's named deliverable) -----------


def _garmin_local_start(activity: dict[str, Any]) -> datetime | None:
    """Local wall-clock start time — distinct from sync.py's parse_garmin_start,
    which deliberately uses startTimeGMT for cross-source UTC comparison. Time-
    of-day patterns need the athlete's actual local clock time and local
    calendar date (for weekday/weekend), not UTC."""
    raw = activity.get("startTimeLocal")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _format_hhmm(minutes: float) -> str:
    total = round(minutes) % (24 * 60)
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"


@dataclass
class TimeOfDayBucket:
    session_type: str
    is_weekend: bool
    half: str  # "AM" or "PM" — see note below on why this split exists
    count: int
    median: str
    earliest: str
    latest: str


def extract_time_of_day_patterns(garmin_activities: list[dict[str, Any]]) -> list[TimeOfDayBucket]:
    """Per §1: 'derive my habitual training times from Garmin activity start
    times (weekday vs weekend, by session type)'. Uses Garmin only, per the
    spec's explicit wording — also avoids double-counting matched activities
    from both sources.

    Split by AM/PM in addition to weekday/weekend/type: real data (28-07-2026)
    showed my weekday runs are genuinely bimodal — a tight morning
    cluster (~07:40-08:59) AND a separate evening cluster (~20:00-21:08) — a
    single median across both (e.g. "19:57") would misleadingly suggest one
    typical time when there are actually two, and would be actively wrong
    input for §1's heat-avoidance guidance ("factor heat into which slot you
    recommend in summer"), which needs to know BOTH real options to choose
    between.

    Deliberately not filtered by as_of (unlike the rest of this module) —
    this is a long-run habit aggregate over the whole cached window, not a
    point-in-time fact, and filtering it per --date would just shrink the
    sample for no benefit.
    """
    groups: dict[tuple[str, bool, str], list[int]] = defaultdict(list)
    for a in garmin_activities:
        dt = _garmin_local_start(a)
        if dt is None:
            continue
        bucket = sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        )
        is_weekend = dt.weekday() >= 5
        minutes = _minutes_since_midnight(dt)
        half = "AM" if minutes < 12 * 60 else "PM"
        groups[(bucket, is_weekend, half)].append(minutes)

    results: list[TimeOfDayBucket] = []
    for t in TYPE_ORDER:
        for is_weekend in (False, True):
            for half in ("AM", "PM"):
                times = groups.get((t, is_weekend, half), [])
                if not times:
                    continue
                results.append(
                    TimeOfDayBucket(
                        session_type=t,
                        is_weekend=is_weekend,
                        half=half,
                        count=len(times),
                        median=_format_hhmm(statistics.median(times)),
                        earliest=_format_hhmm(min(times)),
                        latest=_format_hhmm(max(times)),
                    )
                )
    return results


# --- recent activity log + rolling volume ---------------------------------------


@dataclass
class ActivityLogRow:
    date_local: str
    session_type: str
    distance_mi: float | None
    duration_min: float | None
    avg_hr: float | None


def recent_activity_log(
    garmin_activities: list[dict[str, Any]], as_of: date, days: int = RECENT_LOG_DAYS
) -> list[ActivityLogRow]:
    cutoff = as_of - timedelta(days=days)
    rows = []
    for a in garmin_activities:
        dt = _garmin_local_start(a)
        if dt is None or dt.date() < cutoff or dt.date() > as_of:
            continue
        bucket = sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        )
        distance_m = a.get("distance")
        duration_s = a.get("duration")
        rows.append(
            ActivityLogRow(
                date_local=dt.strftime("%d-%m %H:%M"),
                session_type=bucket,
                distance_mi=(distance_m / sync.MILE_M) if distance_m else None,
                duration_min=(duration_s / 60) if duration_s else None,
                avg_hr=a.get("averageHR"),
            )
        )
    rows.sort(key=lambda r: r.date_local, reverse=True)
    return rows


@dataclass
class RollingVolume:
    window_days: int
    run_miles: float
    run_days: int


def rolling_run_volume(
    garmin_activities: list[dict[str, Any]], window_days: int, as_of: date
) -> RollingVolume:
    cutoff = as_of - timedelta(days=window_days)
    miles = 0.0
    run_days: set[date] = set()
    for a in garmin_activities:
        dt = _garmin_local_start(a)
        if dt is None or dt.date() < cutoff or dt.date() > as_of:
            continue
        bucket = sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        )
        if bucket != "run":
            continue
        distance_m = a.get("distance")
        if distance_m:
            miles += distance_m / sync.MILE_M
        run_days.add(dt.date())
    return RollingVolume(window_days=window_days, run_miles=round(miles, 1), run_days=len(run_days))


@dataclass
class WeekActuals:
    long_run_mi: float
    run_miles: float
    run_days: int
    cross_minutes: float
    has_started: bool


def actuals_for_plan_week(
    garmin_activities: list[dict[str, Any]], week_start: date, week_end: date, *, as_of: date | None = None
) -> WeekActuals:
    """Shared by cli.py (mc check/status/week) and render.py's dashboard —
    written once here rather than duplicated, since both need the same
    'what actually happened in this specific Mon-Sun plan week' computation,
    distinct from rolling_run_volume's trailing-N-days window."""
    as_of = as_of or date.today()
    long_run, run_miles, cross_minutes = 0.0, 0.0, 0.0
    run_days: set[date] = set()
    for a in garmin_activities:
        dt = _garmin_local_start(a)
        if dt is None or not (week_start <= dt.date() <= week_end):
            continue
        bucket = sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        )
        dist_m = a.get("distance")
        dur_s = a.get("duration")
        if bucket == "run":
            if dist_m:
                mi = dist_m / sync.MILE_M
                run_miles += mi
                long_run = max(long_run, mi)
            run_days.add(dt.date())
        elif bucket in ("cross", "bike", "row") and dur_s:
            cross_minutes += dur_s / 60
    return WeekActuals(
        long_run_mi=round(long_run, 1),
        run_miles=round(run_miles, 1),
        run_days=len(run_days),
        cross_minutes=round(cross_minutes),
        has_started=week_start <= as_of,
    )


# --- wellness snapshot -----------------------------------------------------------


@dataclass
class WellnessSnapshot:
    training_readiness: tuple[str, Any] | None
    hrv: tuple[str, Any] | None
    sleep: tuple[str, Any] | None
    stats: tuple[str, Any] | None
    stress: tuple[str, Any] | None
    training_status: tuple[str, Any] | None
    max_metrics: tuple[str, Any] | None
    intervals_ctl_atl_tsb: dict[str, Any] | None


def build_wellness_snapshot(as_of: date) -> WellnessSnapshot:
    intervals_raw = _load_latest(cfg.RAW_INTERVALS_DIR, "wellness")
    intervals_with_tsb = intervals.extract_ctl_atl_tsb(intervals_raw)
    # Records are keyed by "id" = ISO date (confirmed against real data
    # 28-07-2026: ascending chronological order, one record/day). Filter to
    # as_of rather than always taking the global latest, so --date DD-MM
    # actually reflects that date rather than leaking newer data into it.
    as_of_iso = as_of.isoformat()
    eligible = [r for r in intervals_with_tsb if str(r.get("id", "")) <= as_of_iso]
    latest_intervals_record = max(eligible, key=lambda r: r.get("id", "")) if eligible else None

    return WellnessSnapshot(
        training_readiness=latest_garmin_wellness_value("training_readiness", as_of),
        hrv=latest_garmin_wellness_value("hrv", as_of),
        sleep=latest_garmin_wellness_value("sleep", as_of),
        stats=latest_garmin_wellness_value("stats", as_of),
        stress=latest_garmin_wellness_value("stress", as_of),
        training_status=latest_garmin_wellness_value("training_status", as_of),
        max_metrics=latest_garmin_wellness_value("max_metrics", as_of),
        intervals_ctl_atl_tsb=latest_intervals_record,
    )


# --- markdown rendering ------------------------------------------------------------


def _data_health_lines(report: sync.SyncReport | None) -> list[str]:
    if report is None:
        return ["**No sync report found — run `mc sync` first.**"]

    lines = []
    for name in ("garmin", "intervals"):
        s = report.sources.get(name)
        if s is None or not s.requested and s.data_as_of != "carried_over":
            continue
        bold = s.stale_gt_36h or not s.ok
        staleness = f"{s.staleness_hours:.1f}h ago" if s.staleness_hours is not None else "unknown"
        text = (
            f"**{name}**: {'ok' if s.ok else 'FAILED'} · "
            f"last activity {staleness} · "
            f"{s.activities_pulled} activities ({report.since_days}d window)"
            + (f" · {s.error}" if s.error else "")
        )
        if bold:
            text = f"**{text}**"
        lines.append(f"- {text}")

    m = report.activity_matching
    lines.append(
        f"- Matched {m.matched_count} · ambiguous {len(m.ambiguous)} · "
        f"garmin-only {len(m.garmin_only)} · intervals-only {len(m.intervals_only)} · "
        f"field disagreements {len(report.field_disagreements)}"
    )
    for name, s in report.sources.items():
        for note in s.notes:
            lines.append(f"- *{name} note*: {note}")
    return lines


def _time_of_day_table(buckets: list[TimeOfDayBucket]) -> list[str]:
    if not buckets:
        return ["_No Garmin activities with a parseable local start time._"]
    lines = [
        "| Session type | Day | AM/PM | Count | Median start | Range |",
        "|---|---|---|---|---|---|",
    ]
    for b in buckets:
        day = "weekend" if b.is_weekend else "weekday"
        lines.append(
            f"| {b.session_type} | {day} | {b.half} | {b.count} | {b.median} | {b.earliest}–{b.latest} |"
        )
    return lines


def _activity_log_table(rows: list[ActivityLogRow]) -> list[str]:
    if not rows:
        return [f"_No activities in the last {RECENT_LOG_DAYS} days._"]
    lines = ["| Date | Type | Distance | Duration | Avg HR |", "|---|---|---|---|---|"]
    for r in rows:
        dist = f"{r.distance_mi:.1f} mi" if r.distance_mi is not None else "—"
        dur = f"{r.duration_min:.0f} min" if r.duration_min is not None else "—"
        hr = f"{r.avg_hr:.0f}" if r.avg_hr is not None else "—"
        lines.append(f"| {r.date_local} | {r.session_type} | {dist} | {dur} | {hr} |")
    return lines


def _rolling_volume_lines(volumes: list[RollingVolume]) -> list[str]:
    return [
        f"- Last {v.window_days}d: {v.run_miles} mi running, {v.run_days} run day(s)"
        for v in volumes
    ]


def _format_hms(seconds: float) -> str:
    total_min = round(seconds / 60)
    h, m = divmod(total_min, 60)
    return f"{h}h {m}m"


def _wellness_snapshot_lines(snapshot: WellnessSnapshot) -> list[str]:
    """Field paths below were verified against my real Garmin data
    28-07-2026 (raw JSON in data/raw/garmin/wellness/) — the raw response
    shapes for hrv/sleep/training_status/max_metrics are undocumented and not
    covered by garminconnect's typed models, so these were read directly off
    real responses rather than guessed."""
    lines = []

    def fmt(label: str, entry: tuple[str, Any] | None, extractor: Any, missing_note: str = "no data in lookback window") -> str:
        if entry is None:
            return f"- {label}: {missing_note}"
        d, data = entry
        try:
            value = extractor(data)
        except Exception:  # noqa: BLE001
            value = "unparsed — check raw cache, response shape may have changed"
        return f"- {label}: {value} ({d})"

    lines.append(
        fmt(
            "Training readiness",
            snapshot.training_readiness,
            lambda d: d[0].get("score") if isinstance(d, list) and d else "n/a",
            missing_note=(
                "empty for all 7 days in lookback (not a sync bug — every other "
                "metric IS populated for the same days/device). Possibly a "
                "device/firmware feature gap on this Forerunner 255S — worth "
                "checking whether 'Training Readiness' ever appears in Garmin "
                "Connect at all. Not currently required by any §6 rule "
                "(C2 uses HRV/sleep/RHR/self-report directly, not this score)."
            ),
        )
    )
    lines.append(
        fmt(
            "HRV (last night avg)",
            snapshot.hrv,
            lambda d: f"{d.get('hrvSummary', {}).get('lastNightAvg')} ms, {d.get('hrvSummary', {}).get('status')}",
        )
    )
    lines.append(
        fmt(
            "Sleep",
            snapshot.sleep,
            lambda d: _format_hms(d.get("dailySleepDTO", {}).get("sleepTimeSeconds", 0)),
        )
    )
    lines.append(fmt("Resting HR", snapshot.stats, lambda d: f"{d.get('restingHeartRate')} bpm"))
    lines.append(fmt("Stress (avg)", snapshot.stress, lambda d: d.get("avgStressLevel", "n/a")))
    lines.append(
        fmt(
            "Training status",
            snapshot.training_status,
            lambda d: (
                lambda dev: f"{dev.get('trainingStatusFeedbackPhrase', 'n/a')} "
                f"(ACWR {dev.get('acuteTrainingLoadDTO', {}).get('acwrStatus', 'n/a')})"
            )(
                next(
                    iter(
                        d.get("mostRecentTrainingStatus", {})
                        .get("latestTrainingStatusData", {})
                        .values()
                    ),
                    {},
                )
            ),
        )
    )
    lines.append(
        fmt(
            "VO2max",
            snapshot.max_metrics,
            lambda d: d[0].get("generic", {}).get("vo2MaxValue") if isinstance(d, list) and d else "n/a",
        )
    )

    if snapshot.intervals_ctl_atl_tsb:
        r = snapshot.intervals_ctl_atl_tsb
        ctl, atl, tsb = r.get("ctl"), r.get("atl"), r.get("tsb")
        fmt_num = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else x  # noqa: E731
        lines.append(
            f"- CTL/ATL/TSB (intervals.icu): {fmt_num(ctl)} / {fmt_num(atl)} / {fmt_num(tsb)} ({r.get('id', 'n/a')})"
        )
    else:
        lines.append("- CTL/ATL/TSB (intervals.icu): no wellness data available")

    return lines


def render_markdown(as_of: date) -> str:
    report = load_sync_report()
    garmin_activities = _load_latest(cfg.RAW_GARMIN_DIR, "activities")

    tod_buckets = extract_time_of_day_patterns(garmin_activities)
    log_rows = recent_activity_log(garmin_activities, as_of)
    volumes = [rolling_run_volume(garmin_activities, w, as_of) for w in ROLLING_WINDOWS_DAYS]
    wellness = build_wellness_snapshot(as_of)

    lines: list[str] = [f"# Digest · {as_of.strftime('%d-%m-%Y')}", ""]

    lines.append("## Data health")
    lines += _data_health_lines(report)
    lines.append("")

    lines.append("## Time of day patterns")
    lines += _time_of_day_table(tod_buckets)
    lines.append("")

    lines.append(f"## Recent activity log (last {RECENT_LOG_DAYS} days)")
    lines += _activity_log_table(log_rows)
    lines.append("")

    lines.append("## Rolling volume")
    lines += _rolling_volume_lines(volumes)
    lines.append("")

    lines.append("## Wellness snapshot")
    lines += _wellness_snapshot_lines(wellness)
    lines.append("")

    return "\n".join(lines)


def write_digest(as_of: date | None = None) -> Path:
    as_of = as_of or date.today()
    cfg.DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(as_of)
    dated_path = cfg.DIGEST_DIR / f"{as_of.isoformat()}.md"
    latest_path = cfg.DIGEST_DIR / "latest.md"
    dated_path.write_text(markdown)
    latest_path.write_text(markdown)
    return latest_path


# --- manual verification entrypoint (cli.py doesn't exist yet — that's step 8) --

if __name__ == "__main__":
    import argparse
    import sys

    def _parse_ddmm(s: str, year: int = 2026) -> date:
        day, month = s.split("-")
        return date(year, int(month), int(day))

    parser = argparse.ArgumentParser(
        description="Manually run mc digest (cli.py doesn't exist yet — that's step 8)."
    )
    parser.add_argument("--date", type=str, default=None, help="DD-MM, defaults to today")
    args = parser.parse_args()

    as_of = _parse_ddmm(args.date) if args.date else date.today()
    path = write_digest(as_of)
    print(f"Digest written to {path}", file=sys.stderr)
    print(path.read_text())
