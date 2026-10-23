"""intervals.icu fetching — the streams cache, its bounds, and its selection.

This module had no test file until it became the primary source. What is
covered here is the part with consequences: which activities get fetched (an
over-eager rule means a large download every morning in a session that starts
cold), what gets kept (the cache is committed, so git holds every version
forever), and the location fallback that exists only because intervals puts no
coordinates on an activity.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mc import config as cfg
from mc import intervals, metrics


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "RAW_INTERVALS_DIR", tmp_path / "intervals")
    (tmp_path / "intervals" / "streams").mkdir(parents=True)
    return tmp_path / "intervals"


def run(activity_id: str, *, miles: float, days_ago: int, kind: str = "Run") -> dict:
    day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
    return {
        "id": activity_id,
        "type": kind,
        "distance": miles * intervals.MILE_M,
        "start_date_local": f"{day.isoformat()}T07:00:00",
    }


class FakeClient:
    """Records what would have been fetched instead of fetching it."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, path, **kwargs):  # pragma: no cover - not used directly
        raise AssertionError("tests stub pull_streams/pull_first_fix instead")


# --- the constant that is duplicated on purpose --------------------------------


def test_stream_threshold_matches_the_decay_threshold():
    """MIN_STREAM_DISTANCE_MI is a copy of metrics.MIN_DECAY_DISTANCE_MI, made
    because metrics imports sources which imports this module. A copy without
    its reason drifts, so this is the thing that notices."""
    assert intervals.MIN_STREAM_DISTANCE_MI == metrics.MIN_DECAY_DISTANCE_MI


# --- which activities get streams fetched ---------------------------------------


@pytest.fixture
def capture_fetches(monkeypatch, state):
    fetched: list[str] = []

    def fake_pull(client, activity_id):
        fetched.append(activity_id)
        intervals._write_json(
            intervals.streams_path(activity_id),
            intervals._envelope({"streams": [], "laps": []}, source="test"),
        )
        return {"streams": [], "laps": []}

    monkeypatch.setattr(intervals, "pull_streams", fake_pull)
    return fetched


def test_only_long_enough_runs_are_fetched(capture_fetches):
    intervals.sync_streams(FakeClient(), [
        run("long", miles=12, days_ago=1),
        run("short", miles=3, days_ago=1),
    ])
    assert capture_fetches == ["long"]


def test_non_runs_are_never_fetched(capture_fetches):
    """A 20-mile bike ride is long, and the decay analysis says nothing about
    it — fetching its streams would be pure download."""
    intervals.sync_streams(FakeClient(), [
        run("ride", miles=20, days_ago=1, kind="Ride"),
        run("swim", miles=6, days_ago=1, kind="Swim"),
    ])
    assert capture_fetches == []


def test_activities_outside_the_window_are_not_fetched(capture_fetches):
    intervals.sync_streams(FakeClient(), [
        run("recent", miles=10, days_ago=2),
        run("ancient", miles=10, days_ago=intervals.STREAM_WINDOW_DAYS + 5),
    ])
    assert capture_fetches == ["recent"]


def test_already_cached_streams_are_not_refetched(capture_fetches):
    """The warm-cache discipline: this is what stops a cold cloud session
    re-downloading the whole window every morning."""
    activities = [run("a", miles=10, days_ago=1)]
    fetched, cached = intervals.sync_streams(FakeClient(), activities)
    assert (fetched, cached) == (1, 0)

    fetched, cached = intervals.sync_streams(FakeClient(), activities)
    assert (fetched, cached) == (0, 1)
    assert capture_fetches == ["a"]  # still just the one


def test_undated_activity_is_skipped_not_crashed(capture_fetches):
    intervals.sync_streams(FakeClient(), [{"id": "x", "type": "Run", "distance": 30000}])
    assert capture_fetches == []


# --- pruning, because the cache is committed ------------------------------------


def write_cached_stream(state, activity_id: str, age_days: int):
    when = datetime.now(timezone.utc) - timedelta(days=age_days)
    (state / "streams" / f"{activity_id}.json").write_text(
        json.dumps({"fetched_at": when.isoformat(), "source": "t", "data": {}})
    )


def test_prune_drops_only_what_is_past_the_window(state):
    write_cached_stream(state, "fresh", 2)
    write_cached_stream(state, "stale", intervals.STREAM_WINDOW_DAYS + 3)
    assert intervals.prune_streams() == 1
    remaining = {p.stem for p in (state / "streams").glob("*.json")}
    assert remaining == {"fresh"}


def test_prune_uses_the_envelope_not_mtime(state):
    """A fresh clone rewrites every mtime, which would make prune either a
    no-op or a massacre depending on the direction."""
    write_cached_stream(state, "stale", intervals.STREAM_WINDOW_DAYS + 3)
    (state / "streams" / "stale.json").touch()  # mtime is now
    assert intervals.prune_streams() == 1


def test_prune_leaves_unreadable_files_alone(state):
    """Prune is not a repair tool; deleting something it cannot parse is how a
    cache silently loses data it was only confused by."""
    (state / "streams" / "junk.json").write_text("{not json")
    assert intervals.prune_streams() == 0
    assert (state / "streams" / "junk.json").exists()


def test_prune_on_a_missing_directory_is_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "RAW_INTERVALS_DIR", tmp_path / "nothing")
    assert intervals.prune_streams() == 0


# --- the location fallback -------------------------------------------------------


def test_location_stops_at_the_newest_outdoor_run(monkeypatch, state):
    """Indoor runs have no latlng stream. The walk must step past them rather
    than concluding there is no location."""
    seen: list[str] = []

    def fake_fix(client, activity_id):
        seen.append(activity_id)
        return (40.8, -73.9) if activity_id == "outdoor" else None

    monkeypatch.setattr(intervals, "pull_first_fix", fake_fix)
    record = intervals.sync_location(FakeClient(), [
        run("treadmill", miles=4, days_ago=0),
        run("outdoor", miles=6, days_ago=1),
        run("older", miles=6, days_ago=2),
    ])
    assert record["activity_id"] == "outdoor"
    assert (record["lat"], record["lon"]) == (40.8, -73.9)
    assert seen == ["treadmill", "outdoor"]  # stopped, did not keep walking


def test_location_is_not_refetched_when_the_newest_run_is_unchanged(monkeypatch, state):
    calls: list[str] = []
    monkeypatch.setattr(
        intervals, "pull_first_fix", lambda c, a: calls.append(a) or (40.8, -73.9)
    )
    activities = [run("a", miles=6, days_ago=0)]
    intervals.sync_location(FakeClient(), activities)
    intervals.sync_location(FakeClient(), activities)
    assert calls == ["a"]


def test_location_survives_a_corrupt_cache(monkeypatch, state):
    (state / "location.json").write_text("{not json")
    monkeypatch.setattr(intervals, "pull_first_fix", lambda c, a: (1.0, 2.0))
    record = intervals.sync_location(FakeClient(), [run("a", miles=6, days_ago=0)])
    assert record["lat"] == 1.0
