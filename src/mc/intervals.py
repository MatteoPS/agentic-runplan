from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone  # noqa: F401
from pathlib import Path
from typing import Any

import httpx

from mc import clock
from mc import config as cfg

BASE_URL = "https://intervals.icu"

# Plausible avg-HR / moving-time field name candidates on intervals.icu's
# Activity object — the OpenAPI schema didn't confirm the exact key. Probed
# defensively; sync.py records "none present" explicitly rather than treating
# it as 0 or a match. Correct this list against a real response during the
# first manual verification run.
AVG_HR_FIELD_CANDIDATES = ("average_heartrate", "icu_average_hr", "average_hr")
MOVING_TIME_FIELD_CANDIDATES = ("moving_time", "icu_moving_time", "elapsed_time")


# --- exceptions -------------------------------------------------------------


class IntervalsSyncError(Exception):
    """Base for all intervals.py errors. Never swallow into empty data — raise."""


class IntervalsAuthError(IntervalsSyncError):
    pass


class IntervalsRateLimitError(IntervalsSyncError):
    pass


class IntervalsNotFoundError(IntervalsSyncError):
    pass


class IntervalsServerError(IntervalsSyncError):
    pass


class IntervalsConnectionError(IntervalsSyncError):
    pass


# --- client / request helpers ------------------------------------------------


def get_client() -> tuple[httpx.Client, str]:
    api_key, athlete_id = cfg.require_intervals_credentials()
    client = httpx.Client(
        base_url=BASE_URL,
        auth=httpx.BasicAuth("API_KEY", api_key),
        timeout=30.0,
    )
    return client, athlete_id


_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5


def _request(
    client: httpx.Client, method: str, path: str, *, description: str, **kwargs: Any
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            resp = client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < _MAX_RETRIES:
                attempt += 1
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise IntervalsConnectionError(f"{description}: network error — {e}") from e

        if resp.status_code == 401:
            raise IntervalsAuthError(f"{description}: 401 — check INTERVALS_API_KEY")
        if resp.status_code == 404:
            raise IntervalsNotFoundError(f"{description}: 404 — {resp.text[:200]}")
        if resp.status_code == 429:
            raise IntervalsRateLimitError(f"{description}: 429 rate-limited")
        if resp.status_code >= 500:
            if attempt < _MAX_RETRIES:
                attempt += 1
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise IntervalsServerError(
                f"{description}: {resp.status_code} — {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise IntervalsSyncError(
                f"{description}: {resp.status_code} — {resp.text[:200]}"
            )
        return resp


# --- raw-dump helpers ---------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def _envelope(data: Any, *, source: str) -> dict[str, Any]:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "data": data,
    }


# --- data pull functions -------------------------------------------------------


def pull_activities(
    client: httpx.Client, athlete_id: str, since_days: int
) -> list[dict[str, Any]]:
    oldest = (clock.today() - timedelta(days=since_days)).isoformat()
    newest = clock.today().isoformat()
    resp = _request(
        client,
        "GET",
        f"/api/v1/athlete/{athlete_id}/activities",
        description=f"GET activities({oldest},{newest})",
        params={"oldest": oldest, "newest": newest},
    )
    activities = resp.json()

    out_dir = cfg.RAW_INTERVALS_DIR / "activities"
    _write_json(
        out_dir / f"activities_{oldest}_{newest}.json",
        _envelope(activities, source="GET /activities"),
    )
    _write_json(out_dir / "latest.json", _envelope(activities, source="GET /activities"))
    return activities


def pull_wellness(
    client: httpx.Client, athlete_id: str, since_days: int
) -> list[dict[str, Any]]:
    oldest = (clock.today() - timedelta(days=since_days)).isoformat()
    newest = clock.today().isoformat()
    resp = _request(
        client,
        "GET",
        f"/api/v1/athlete/{athlete_id}/wellness",
        description=f"GET wellness({oldest},{newest})",
        params={"oldest": oldest, "newest": newest},
    )
    wellness = resp.json()

    out_dir = cfg.RAW_INTERVALS_DIR / "wellness"
    _write_json(
        out_dir / f"wellness_{oldest}_{newest}.json",
        _envelope(wellness, source="GET /wellness"),
    )
    _write_json(out_dir / "latest.json", _envelope(wellness, source="GET /wellness"))
    return wellness


def pull_events(
    client: httpx.Client,
    athlete_id: str,
    since_days: int,
    days_forward: int = 28,
) -> list[dict[str, Any]]:
    oldest = (clock.today() - timedelta(days=since_days)).isoformat()
    newest = (clock.today() + timedelta(days=days_forward)).isoformat()
    resp = _request(
        client,
        "GET",
        f"/api/v1/athlete/{athlete_id}/events",
        description=f"GET events({oldest},{newest})",
        params={"oldest": oldest, "newest": newest},
    )
    events = resp.json()

    out_dir = cfg.RAW_INTERVALS_DIR / "events"
    _write_json(
        out_dir / f"events_{oldest}_{newest}.json",
        _envelope(events, source="GET /events"),
    )
    _write_json(out_dir / "latest.json", _envelope(events, source="GET /events"))
    return events


def extract_ctl_atl_tsb(wellness_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure function — adds tsb = ctl - atl per record. Does not mutate raw/;
    called on demand by sync.py / later digest.py."""
    out = []
    for record in wellness_records:
        r = dict(record)
        ctl, atl = r.get("ctl"), r.get("atl")
        r["tsb"] = ctl - atl if ctl is not None and atl is not None else None
        out.append(r)
    return out


# --- per-sample streams ---------------------------------------------------------

# Only what metrics.run_splits actually reads. Filtering matters: the same run
# is 583 KB unfiltered and 113 KB with these four. Invalid names 422 rather
# than being silently dropped, so a typo here fails loudly.
STREAM_TYPES = ("distance", "cadence", "step_length", "velocity_smooth")

# Mirrors metrics.MIN_DECAY_DISTANCE_MI. Duplicated rather than imported
# because metrics imports sources, which imports this module — and a constant
# copied without its reason drifts, so tests/test_intervals.py asserts the two
# stay equal.
MIN_STREAM_DISTANCE_MI = 5.0
MILE_M = 1609.344

# How far back to fetch and keep streams. metrics.FORM_WINDOW_DAYS = 14 is all
# the decay analysis reads; 30 is deliberately generous so a week off doesn't
# lose the runs either side of it, and it bounds a cache that is committed.
STREAM_WINDOW_DAYS = 30


def streams_path(activity_id: str) -> Path:
    return cfg.RAW_INTERVALS_DIR / "streams" / f"{activity_id}.json"


def pull_streams(client: httpx.Client, activity_id: str) -> dict[str, Any]:
    """Per-sample streams plus per-lap splits for one activity, cached together.

    Two calls, one file. The laps are here because intervals exposes **no
    per-sample GAP** (`types=gap` is a 422) but does give it per lap, and laps
    carry `start_index`/`end_index` into these very stream arrays — so a
    sample's grade-adjusted speed is its lap's, looked up by index. Storing
    them apart would mean two caches that can disagree about one run.
    """
    streams = _request(
        client,
        "GET",
        f"/api/v1/activity/{activity_id}/streams",
        description=f"GET streams({activity_id})",
        params={"types": ",".join(STREAM_TYPES)},
    ).json()

    laps = _request(
        client,
        "GET",
        f"/api/v1/activity/{activity_id}/intervals",
        description=f"GET intervals({activity_id})",
    ).json()

    payload = {"streams": streams, "laps": (laps or {}).get("icu_intervals") or []}
    _write_json(streams_path(activity_id), _envelope(payload, source="GET /streams+/intervals"))
    return payload


def pull_first_fix(client: httpx.Client, activity_id: str) -> tuple[float, float] | None:
    """Start coordinate, which exists nowhere on the activity object.

    `weather.location_from_activities` needs it to follow the athlete to
    Italy, and 123 KB downloaded for two floats is the price of intervals not
    putting them on the summary. Cached by activity id in `location.json` so
    it is fetched once, and only for the newest run that lacks one — older
    activities cannot change what "most recent GPS fix" means.

    An indoor run returns an empty stream list, which is a clean "no GPS".
    """
    payload = _request(
        client,
        "GET",
        f"/api/v1/activity/{activity_id}/streams",
        description=f"GET latlng({activity_id})",
        params={"types": "latlng"},
    ).json()
    for stream in payload or []:
        if not isinstance(stream, dict) or stream.get("type") != "latlng":
            continue
        lats, lons = stream.get("data") or [], stream.get("data2") or []
        for lat, lon in zip(lats, lons):
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    return None


def prune_streams(max_age_days: int = STREAM_WINDOW_DAYS, now: datetime | None = None) -> int:
    """Drop cached streams older than the window, returning how many went.

    This cache is committed so that ephemeral cloud sessions start warm, which
    means git keeps every version of it forever — an unbounded cache would be
    an unbounded repo. Age is taken from the envelope's `fetched_at` rather
    than mtime, which a fresh clone rewrites.
    """
    directory = cfg.RAW_INTERVALS_DIR / "streams"
    if not directory.exists():
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
    removed = 0
    for path in directory.glob("*.json"):
        try:
            fetched = datetime.fromisoformat(json.loads(path.read_text())["fetched_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue  # unreadable: leave it, prune is not a repair tool
        if fetched < cutoff:
            path.unlink()
            removed += 1
    return removed


def _run_distance_mi(activity: dict[str, Any]) -> float:
    try:
        return float(activity.get("distance") or 0) / MILE_M
    except (TypeError, ValueError):
        return 0.0


def _is_run(activity: dict[str, Any]) -> bool:
    return "run" in str(activity.get("type") or "").lower()


def sync_streams(
    client: httpx.Client, activities: list[dict[str, Any]], now: datetime | None = None
) -> tuple[int, int]:
    """Fetch streams for runs that need them. Returns (fetched, skipped).

    Only long enough runs, only recent ones, and **only when the file is
    absent** — the same warm-cache discipline `garmin.py` uses, and the reason
    a cloud session does not re-download the whole window every morning.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=STREAM_WINDOW_DAYS)).date()
    fetched = skipped = 0
    for activity in activities:
        if not _is_run(activity) or _run_distance_mi(activity) < MIN_STREAM_DISTANCE_MI:
            continue
        raw_start = str(activity.get("start_date_local") or "")[:10]
        try:
            if date.fromisoformat(raw_start) < cutoff:
                continue
        except ValueError:
            continue
        activity_id = str(activity.get("id") or "")
        if not activity_id:
            continue
        if streams_path(activity_id).exists():
            skipped += 1
            continue
        pull_streams(client, activity_id)
        fetched += 1
    return fetched, skipped


def sync_location(
    client: httpx.Client, activities: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Cache the start coordinate of the most recent outdoor activity.

    Walks newest-first and stops at the first success, because that is all
    `location_from_activities` ever asks for. Already-cached ids cost nothing.
    """
    path = cfg.RAW_INTERVALS_DIR / "location.json"
    cached = None
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            cached = None

    ordered = sorted(
        (a for a in activities if a.get("start_date_local")),
        key=lambda a: str(a.get("start_date_local")),
        reverse=True,
    )
    for activity in ordered[:5]:  # a whole week of indoor sessions, at most
        activity_id = str(activity.get("id") or "")
        if not activity_id:
            continue
        if cached and cached.get("activity_id") == activity_id:
            return cached
        fix = pull_first_fix(client, activity_id)
        if fix is None:
            continue  # indoor run, no GPS — try the one before it
        record = {
            "activity_id": activity_id,
            "start_date_local": activity.get("start_date_local"),
            "lat": fix[0],
            "lon": fix[1],
        }
        _write_json(path, record)
        return record
    return cached


@dataclass
class IntervalsPullResult:
    activities: list[dict[str, Any]]
    wellness: list[dict[str, Any]]
    events: list[dict[str, Any]]
    streams_fetched: int = 0
    streams_cached: int = 0
    streams_pruned: int = 0
    location: dict[str, Any] | None = None


def sync_intervals(since_days: int, with_streams: bool = True) -> IntervalsPullResult:
    client, athlete_id = get_client()
    try:
        activities = pull_activities(client, athlete_id, since_days)
        wellness = pull_wellness(client, athlete_id, since_days)
        events = pull_events(client, athlete_id, since_days)
        fetched = cached = pruned = 0
        location = None
        if with_streams:
            fetched, cached = sync_streams(client, activities)
            location = sync_location(client, activities)
            pruned = prune_streams()
    finally:
        client.close()
    return IntervalsPullResult(
        activities=activities,
        wellness=wellness,
        events=events,
        streams_fetched=fetched,
        streams_cached=cached,
        streams_pruned=pruned,
        location=location,
    )
