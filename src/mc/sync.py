from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from mc import config as cfg
from mc import garmin
from mc import intervals

DEFAULT_SINCE_DAYS = garmin.DEFAULT_SINCE_DAYS
MAX_SINCE_DAYS = garmin.MAX_SINCE_DAYS
MATCH_TOLERANCE_MINUTES = 5

MILE_M = 1609.344

# Canonical type buckets. Checked against my real synced data 28-07-2026
# (50 real activities, both sources, after I connected Garmin inside
# intervals.icu). "row" was added after two real rowing activities — matching
# to the second on both sides ("rowing_v2"/"indoor_rowing" on Garmin,
# "Rowing"/"VirtualRow" on intervals.icu) — landed in "other" on both sides and
# were wrongly reported as one-sided instead of matched, since "other" is
# excluded from matching entirely. Everything else (run/bike/cross/walk/
# strength) matched correctly on the first real run, no changes needed there.
GARMIN_BUCKET_KEYWORDS: dict[str, str] = {
    "running": "run",
    "run": "run",
    "cycling": "bike",
    "biking": "bike",
    "bike": "bike",
    "elliptical": "cross",
    "fitness_equipment": "cross",
    "indoor_cardio": "cross",
    "walking": "walk",
    "hiking": "walk",
    "strength": "strength",
    "row": "row",
}
INTERVALS_BUCKET_KEYWORDS: dict[str, str] = {
    "run": "run",
    "ride": "bike",
    "bike": "bike",
    "cycling": "bike",
    "elliptical": "cross",
    "walk": "walk",
    "hike": "walk",
    "weighttraining": "strength",
    "strength": "strength",
    "workout": "strength",
    "row": "row",
}


def canonical_bucket(type_str: str | None, keywords: dict[str, str]) -> str:
    if not type_str:
        return "other"
    t = type_str.lower()
    for key, bucket in keywords.items():
        if key in t:
            return bucket
    return "other"


# --- report models -------------------------------------------------------------


class SourceReport(BaseModel):
    requested: bool
    ok: bool
    error: str | None = None
    error_type: str | None = None
    last_successful_sync_at: datetime | None = None
    data_as_of: Literal["fresh_this_run", "carried_over"] | None = None
    activities_pulled: int = 0
    most_recent_activity_start: datetime | None = None
    staleness_hours: float | None = None
    stale_gt_36h: bool | None = None
    api_calls_made: int | None = None
    notes: list[str] = []


class FieldComparison(BaseModel):
    garmin: float | None
    intervals: float | None
    pct_diff: float | None
    comparable: bool
    flag: bool


class MatchedActivity(BaseModel):
    garmin_id: str
    intervals_id: str
    start: datetime
    canonical_type: str
    fields: dict[str, FieldComparison]


class ActivityRef(BaseModel):
    id: str
    start: datetime
    canonical_type: str
    source_type_raw: str


class ActivityMatching(BaseModel):
    tolerance_minutes: int
    matched_count: int
    garmin_only: list[ActivityRef]
    intervals_only: list[ActivityRef]
    ambiguous: list[dict[str, Any]]


class SyncReport(BaseModel):
    generated_at: datetime
    requested_source: Literal["garmin", "intervals", "both"]
    since_days: int
    sources: dict[str, SourceReport]
    activity_matching: ActivityMatching
    field_disagreements: list[MatchedActivity]

    @property
    def all_ok(self) -> bool:
        return all(s.ok for s in self.sources.values() if s.requested)


# --- field / time extraction --------------------------------------------------


def parse_garmin_start(activity: dict[str, Any]) -> datetime | None:
    raw = activity.get("startTimeGMT")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_intervals_start(activity: dict[str, Any]) -> datetime | None:
    raw = activity.get("start_date") or activity.get("start_date_local")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_zero(value: float | None) -> float | None:
    """0 almost always means 'no data' for distance/duration/HR on a real
    workout (e.g. no-GPS elliptical distance) — treat as missing, not a
    genuine measurement, so it isn't compared as if it were meaningful."""
    if value is not None and value == 0:
        return None
    return value


def _garmin_fields(activity: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    distance_m = activity.get("distance")
    duration_s = activity.get("duration")
    avg_hr = activity.get("averageHR")
    distance_mi = distance_m / MILE_M if distance_m is not None else None
    duration_min = duration_s / 60 if duration_s is not None else None
    return _normalize_zero(distance_mi), _normalize_zero(duration_min), _normalize_zero(avg_hr)


def _intervals_fields(
    activity: dict[str, Any]
) -> tuple[float | None, float | None, float | None]:
    distance_m = activity.get("distance")
    if distance_m is None:
        distance_m = activity.get("icu_distance")
    duration_s = None
    for key in intervals.MOVING_TIME_FIELD_CANDIDATES:
        if activity.get(key) is not None:
            duration_s = activity[key]
            break
    avg_hr = None
    for key in intervals.AVG_HR_FIELD_CANDIDATES:
        if activity.get(key) is not None:
            avg_hr = activity[key]
            break
    distance_mi = distance_m / MILE_M if distance_m is not None else None
    duration_min = duration_s / 60 if duration_s is not None else None
    return _normalize_zero(distance_mi), _normalize_zero(duration_min), _normalize_zero(avg_hr)


def _pct_diff(a: float, b: float) -> float | None:
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b))
    if denom == 0:
        return None
    return abs(a - b) / denom * 100


def _field_comparison(a: float | None, b: float | None) -> FieldComparison:
    if a is None or b is None:
        return FieldComparison(garmin=a, intervals=b, pct_diff=None, comparable=False, flag=False)
    pct = _pct_diff(a, b)
    return FieldComparison(
        garmin=a, intervals=b, pct_diff=pct, comparable=True, flag=bool(pct is not None and pct > 2.0)
    )


# --- cross-source activity matching --------------------------------------------


def _match_activities(
    garmin_activities: list[dict[str, Any]],
    intervals_activities: list[dict[str, Any]],
    tolerance_minutes: int = MATCH_TOLERANCE_MINUTES,
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any], timedelta]],
    list[ActivityRef],
    list[ActivityRef],
    list[dict[str, Any]],
]:
    tolerance = timedelta(minutes=tolerance_minutes)

    g_refs = [
        (
            a,
            parse_garmin_start(a),
            canonical_bucket(
                (a.get("activityType") or {}).get("typeKey"), GARMIN_BUCKET_KEYWORDS
            ),
        )
        for a in garmin_activities
    ]
    i_refs = [
        (a, parse_intervals_start(a), canonical_bucket(a.get("type"), INTERVALS_BUCKET_KEYWORDS))
        for a in intervals_activities
    ]

    edges: list[tuple[timedelta, int, int]] = []
    for gi, (_, g_start, g_bucket) in enumerate(g_refs):
        if g_start is None:
            continue
        for ii, (_, i_start, i_bucket) in enumerate(i_refs):
            if i_start is None or g_bucket != i_bucket or g_bucket == "other":
                continue
            delta = abs(g_start - i_start)
            if delta <= tolerance:
                edges.append((delta, gi, ii))
    edges.sort(key=lambda e: e[0])

    g_edge_count = Counter(gi for _, gi, _ in edges)
    i_edge_count = Counter(ii for _, _, ii in edges)
    ambiguous_g = {gi for gi, c in g_edge_count.items() if c > 1}
    ambiguous_i = {ii for ii, c in i_edge_count.items() if c > 1}

    matched_g: set[int] = set()
    matched_i: set[int] = set()
    matches: list[tuple[dict[str, Any], dict[str, Any], timedelta]] = []
    ambiguous_groups: list[dict[str, Any]] = []
    seen_ambiguous: set[tuple[int, int]] = set()

    for delta, gi, ii in edges:
        if gi in ambiguous_g or ii in ambiguous_i:
            key = (gi, ii)
            if key not in seen_ambiguous:
                seen_ambiguous.add(key)
                ambiguous_groups.append(
                    {
                        "garmin_id": str(g_refs[gi][0].get("activityId")),
                        "intervals_id": str(i_refs[ii][0].get("id")),
                        "delta_minutes": round(delta.total_seconds() / 60, 1),
                    }
                )
            continue
        if gi in matched_g or ii in matched_i:
            continue
        matched_g.add(gi)
        matched_i.add(ii)
        matches.append((g_refs[gi][0], i_refs[ii][0], delta))

    garmin_only = [
        ActivityRef(
            id=str(a.get("activityId")),
            start=g_start,
            canonical_type=bucket,
            source_type_raw=(a.get("activityType") or {}).get("typeKey") or "unknown",
        )
        for gi, (a, g_start, bucket) in enumerate(g_refs)
        if gi not in matched_g and gi not in ambiguous_g and g_start is not None
    ]
    intervals_only = [
        ActivityRef(
            id=str(a.get("id")),
            start=i_start,
            canonical_type=bucket,
            source_type_raw=a.get("type") or "unknown",
        )
        for ii, (a, i_start, bucket) in enumerate(i_refs)
        if ii not in matched_i and ii not in ambiguous_i and i_start is not None
    ]

    return matches, garmin_only, intervals_only, ambiguous_groups


def _build_matched_activity(
    g: dict[str, Any], i: dict[str, Any], delta: timedelta
) -> MatchedActivity:
    g_dist, g_dur, g_hr = _garmin_fields(g)
    i_dist, i_dur, i_hr = _intervals_fields(i)
    bucket = canonical_bucket((g.get("activityType") or {}).get("typeKey"), GARMIN_BUCKET_KEYWORDS)
    start = parse_garmin_start(g) or parse_intervals_start(i)
    assert start is not None
    return MatchedActivity(
        garmin_id=str(g.get("activityId")),
        intervals_id=str(i.get("id")),
        start=start,
        canonical_type=bucket,
        fields={
            "distance_mi": _field_comparison(g_dist, i_dist),
            "duration_min": _field_comparison(g_dur, i_dur),
            "avg_hr": _field_comparison(g_hr, i_hr),
        },
    )


# --- source report builders -----------------------------------------------------


def _staleness_hours(most_recent_start: datetime | None) -> float | None:
    if most_recent_start is None:
        return None
    now = datetime.now(timezone.utc)
    if most_recent_start.tzinfo is None:
        most_recent_start = most_recent_start.replace(tzinfo=timezone.utc)
    return (now - most_recent_start).total_seconds() / 3600


def _run_garmin(
    since_days: int, force: bool, interactive: bool | None
) -> tuple[SourceReport, list[dict[str, Any]]]:
    estimate = garmin.estimate_call_count(since_days)
    print(f"[sync] Garmin call estimate: ~{estimate['total_est']} calls {estimate}", file=sys.stderr)
    try:
        result = garmin.sync_garmin(since_days, force=force, interactive=interactive)
    except (garmin.GarminSyncError, cfg.ConfigError) as e:
        print(f"[sync] Garmin sync FAILED: {e}", file=sys.stderr)
        return (
            SourceReport(
                requested=True,
                ok=False,
                error=str(e),
                error_type=type(e).__name__,
                data_as_of="fresh_this_run",
            ),
            [],
        )

    starts = [s for a in result.activities if (s := parse_garmin_start(a)) is not None]
    most_recent = max(starts) if starts else None
    staleness = _staleness_hours(most_recent)
    notes = []
    if result.wellness_gaps:
        notes.append(f"{len(result.wellness_gaps)} wellness day/metric gaps (no data returned)")
    for name, err in result.supplementary_failures.items():
        notes.append(f"supplementary pull '{name}' failed (non-critical, not rule-relevant): {err}")

    report = SourceReport(
        requested=True,
        ok=True,
        last_successful_sync_at=datetime.now(timezone.utc),
        data_as_of="fresh_this_run",
        activities_pulled=len(result.activities),
        most_recent_activity_start=most_recent,
        staleness_hours=staleness,
        stale_gt_36h=(staleness is not None and staleness > 36),
        notes=notes,
    )
    return report, result.activities


def _run_intervals(since_days: int) -> tuple[SourceReport, list[dict[str, Any]]]:
    try:
        result = intervals.sync_intervals(since_days)
    except (intervals.IntervalsSyncError, cfg.ConfigError) as e:
        print(f"[sync] intervals.icu sync FAILED: {e}", file=sys.stderr)
        return (
            SourceReport(
                requested=True,
                ok=False,
                error=str(e),
                error_type=type(e).__name__,
                data_as_of="fresh_this_run",
            ),
            [],
        )

    starts = [s for a in result.activities if (s := parse_intervals_start(a)) is not None]
    most_recent = max(starts) if starts else None
    staleness = _staleness_hours(most_recent)

    report = SourceReport(
        requested=True,
        ok=True,
        last_successful_sync_at=datetime.now(timezone.utc),
        data_as_of="fresh_this_run",
        activities_pulled=len(result.activities),
        most_recent_activity_start=most_recent,
        staleness_hours=staleness,
        stale_gt_36h=(staleness is not None and staleness > 36),
    )
    return report, result.activities


def _load_previous_report() -> SyncReport | None:
    if not cfg.SYNC_REPORT_PATH.exists():
        return None
    try:
        return SyncReport.model_validate_json(cfg.SYNC_REPORT_PATH.read_text())
    except Exception as e:  # noqa: BLE001 — a corrupt/old-schema report shouldn't crash sync
        print(f"[sync] warning: could not parse previous sync_report.json ({e}); ignoring it", file=sys.stderr)
        return None


def _carry_over(previous: SyncReport | None, name: str) -> SourceReport:
    if previous is not None and name in previous.sources:
        prev = previous.sources[name]
        return prev.model_copy(update={"requested": False, "data_as_of": "carried_over"})
    return SourceReport(requested=False, ok=False, error="never synced", notes=["source not yet synced"])


def _load_cached_activities(raw_dir: Any) -> list[dict[str, Any]]:
    latest_path = raw_dir / "activities" / "latest.json"
    if not latest_path.exists():
        return []
    try:
        return json.loads(latest_path.read_text())["data"]
    except Exception:  # noqa: BLE001
        return []


# --- orchestration ---------------------------------------------------------------


def run_sync(
    since_days: int | None = None,
    source: Literal["garmin", "intervals", "both"] = "both",
    *,
    force: bool = False,
    interactive: bool | None = None,
) -> SyncReport:
    since_days = since_days or DEFAULT_SINCE_DAYS
    clamp_note = None
    if since_days > MAX_SINCE_DAYS:
        clamp_note = f"--since {since_days} clamped to ceiling {MAX_SINCE_DAYS}"
        print(f"[sync] {clamp_note}", file=sys.stderr)
        since_days = MAX_SINCE_DAYS

    cfg.ensure_data_dirs()
    previous = _load_previous_report()

    if source in ("garmin", "both"):
        garmin_report, garmin_activities = _run_garmin(since_days, force, interactive)
        if clamp_note:
            garmin_report.notes.append(clamp_note)
    else:
        garmin_report = _carry_over(previous, "garmin")
        garmin_activities = _load_cached_activities(cfg.RAW_GARMIN_DIR)

    if source in ("intervals", "both"):
        intervals_report, intervals_activities = _run_intervals(since_days)
    else:
        intervals_report = _carry_over(previous, "intervals")
        intervals_activities = _load_cached_activities(cfg.RAW_INTERVALS_DIR)

    matches, garmin_only, intervals_only, ambiguous = _match_activities(
        garmin_activities, intervals_activities
    )
    field_disagreements = []
    for g, i, delta in matches:
        matched = _build_matched_activity(g, i, delta)
        if any(fc.flag for fc in matched.fields.values()):
            field_disagreements.append(matched)

    report = SyncReport(
        generated_at=datetime.now(timezone.utc),
        requested_source=source,
        since_days=since_days,
        sources={"garmin": garmin_report, "intervals": intervals_report},
        activity_matching=ActivityMatching(
            tolerance_minutes=MATCH_TOLERANCE_MINUTES,
            matched_count=len(matches),
            garmin_only=garmin_only,
            intervals_only=intervals_only,
            ambiguous=ambiguous,
        ),
        field_disagreements=field_disagreements,
    )
    cfg.SYNC_REPORT_PATH.write_text(report.model_dump_json(indent=2))
    return report


# --- manual verification entrypoint (cli.py is step 8, not built yet) -----------

if __name__ == "__main__":
    import argparse

    from rich.console import Console
    from rich.table import Table

    parser = argparse.ArgumentParser(
        description="Manually run mc sync (cli.py doesn't exist yet — that's step 8)."
    )
    parser.add_argument("--since", type=int, default=None, dest="since_days")
    parser.add_argument("--source", choices=["garmin", "intervals", "both"], default="both")
    parser.add_argument(
        "--force", action="store_true", help="Ignore per-day/per-activity cache, refetch everything in window"
    )
    args = parser.parse_args()

    report = run_sync(since_days=args.since_days, source=args.source, force=args.force)

    console = Console()
    table = Table(title="mc sync — data health")
    table.add_column("source")
    table.add_column("ok")
    table.add_column("staleness (h)")
    table.add_column("activities")
    table.add_column("error")
    for name, s in report.sources.items():
        table.add_row(
            name,
            str(s.ok),
            f"{s.staleness_hours:.1f}" if s.staleness_hours is not None else "—",
            str(s.activities_pulled),
            s.error or "—",
        )
    console.print(table)
    console.print(
        f"Matched: {report.activity_matching.matched_count} · "
        f"Garmin-only: {len(report.activity_matching.garmin_only)} · "
        f"Intervals-only: {len(report.activity_matching.intervals_only)} · "
        f"Ambiguous: {len(report.activity_matching.ambiguous)} · "
        f"Field disagreements: {len(report.field_disagreements)}"
    )
    console.print(f"Full report: {cfg.SYNC_REPORT_PATH}")
    sys.exit(0 if report.all_ok else 1)
