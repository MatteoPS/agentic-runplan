from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

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
    oldest = (date.today() - timedelta(days=since_days)).isoformat()
    newest = date.today().isoformat()
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
    oldest = (date.today() - timedelta(days=since_days)).isoformat()
    newest = date.today().isoformat()
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
    oldest = (date.today() - timedelta(days=since_days)).isoformat()
    newest = (date.today() + timedelta(days=days_forward)).isoformat()
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


@dataclass
class IntervalsPullResult:
    activities: list[dict[str, Any]]
    wellness: list[dict[str, Any]]
    events: list[dict[str, Any]]


def sync_intervals(since_days: int) -> IntervalsPullResult:
    client, athlete_id = get_client()
    try:
        activities = pull_activities(client, athlete_id, since_days)
        wellness = pull_wellness(client, athlete_id, since_days)
        events = pull_events(client, athlete_id, since_days)
    finally:
        client.close()
    return IntervalsPullResult(activities=activities, wellness=wellness, events=events)
