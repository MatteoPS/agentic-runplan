"""The HR-settings pull, and its place in a sync that must not abort.

Max HR has no history anywhere in Garmin Connect, so the dated file this pull
writes is the *only* record this system will ever have of when the setting
changed. Two things therefore matter and are tested here: that a dated file is
written (not just latest.json, which a later sync overwrites), and that a
failure to fetch it never discards the activities and wellness already pulled.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from mc import garmin


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(garmin.cfg, "RAW_GARMIN_DIR", tmp_path / "garmin")
    return tmp_path / "garmin"


class FakeClient:
    def __init__(self, settings=None, zones=None, device=None):
        self._settings = settings if settings is not None else {"userData": {"maxHeartRate": 183}}
        self._zones = zones if zones is not None else [{"sport": "RUNNING", "maxHeartRate": 183}]
        self._device = device if device is not None else {"deviceId": 3472039812}
        self.device_ids_asked: list[str] = []

    def get_user_profile(self):
        return self._settings

    def get_heart_rate_zones(self):
        return self._zones

    def get_device_settings(self, device_id):
        self.device_ids_asked.append(device_id)
        return self._device


def test_pull_writes_a_dated_file_as_well_as_latest(raw_dir):
    """The dated file is the entire point — latest.json alone would be
    overwritten tomorrow and the time series would never exist."""
    garmin.pull_user_hr_settings(FakeClient())
    hr_dir = raw_dir / "wellness" / "hr_settings"
    dated = hr_dir / f"{date.today().isoformat()}.json"
    assert dated.exists()
    assert (hr_dir / "latest.json").exists()
    data = json.loads(dated.read_text())["data"]
    assert data["user_settings"]["userData"]["maxHeartRate"] == 183
    assert data["heart_rate_zones"] == [{"sport": "RUNNING", "maxHeartRate": 183}]


def test_the_snapshot_lands_under_wellness_which_is_tracked_in_git(raw_dir):
    """data/raw/garmin/activities/ is gitignored and re-fetchable by id;
    wellness/ is tracked because a 7-day window cannot be re-fetched. A
    settings change is less recoverable still, so it belongs here."""
    garmin.pull_user_hr_settings(FakeClient())
    assert (raw_dir / "wellness" / "hr_settings").is_dir()


def test_the_envelope_names_both_endpoints(raw_dir):
    """The two calls share one envelope, so the source string has to say so —
    "get_user_profile" alone would misdescribe half the file."""
    garmin.pull_user_hr_settings(FakeClient())
    payload = json.loads((raw_dir / "wellness" / "hr_settings" / "latest.json").read_text())
    assert payload["source"] == "get_user_profile+get_heart_rate_zones"
    assert payload["fetched_at"]


def test_device_id_is_read_off_the_cached_training_status(raw_dir):
    """Rather than spending a get_devices() call to learn something already on
    disk."""
    status = raw_dir / "wellness" / "training_status"
    status.mkdir(parents=True)
    (status / "2026-08-20.json").write_text(json.dumps({
        "data": {"mostRecentTrainingStatus": {
            "latestTrainingStatusData": {"3472039812": {"trainingStatus": 3}}}}
    }))
    assert garmin.resolve_device_id() == "3472039812"


def test_device_id_prefers_the_newest_cached_day(raw_dir):
    status = raw_dir / "wellness" / "training_status"
    status.mkdir(parents=True)
    for day, dev in (("2026-08-01", "111"), ("2026-08-20", "222")):
        (status / f"{day}.json").write_text(json.dumps({
            "data": {"mostRecentTrainingStatus": {"latestTrainingStatusData": {dev: {}}}}
        }))
    assert garmin.resolve_device_id() == "222"


def test_no_cached_training_status_is_none_not_an_error(raw_dir):
    """A first-ever sync has nothing cached yet. That is not a failure, and it
    must not cost a call to find out."""
    assert garmin.resolve_device_id() is None


def test_pull_device_settings_writes_a_dated_file(raw_dir):
    client = FakeClient()
    garmin.pull_device_settings(client, "3472039812")
    assert client.device_ids_asked == ["3472039812"]
    dated = raw_dir / "wellness" / "device_settings" / f"{date.today().isoformat()}.json"
    assert dated.exists()


def test_a_failed_hr_settings_pull_does_not_abort_the_sync(raw_dir, monkeypatch):
    """It is supplementary: no §6 rule reads Max HR, so losing the activities
    and wellness already fetched over it would be a bad trade."""
    monkeypatch.setattr(garmin, "get_client", lambda interactive=None: FakeClient())
    monkeypatch.setattr(garmin, "pull_activities", lambda *a, **k: [{"activityId": 1}])
    monkeypatch.setattr(garmin, "pull_daily_wellness", lambda *a, **k: ({"hrv": {}}, []))
    monkeypatch.setattr(garmin, "pull_body_battery", lambda *a, **k: [])
    monkeypatch.setattr(garmin, "pull_race_predictions", lambda *a, **k: {})
    monkeypatch.setattr(garmin, "pull_lactate_threshold", lambda *a, **k: {})

    def boom(_client):
        raise garmin.GarminConnectionFailedError("get_user_profile(): 500")

    monkeypatch.setattr(garmin, "pull_user_hr_settings", boom)

    result = garmin.sync_garmin(since_days=7)
    assert result.activities == [{"activityId": 1}]
    assert result.user_hr_settings is None
    assert "user_hr_settings" in result.supplementary_failures


def test_the_call_estimate_counts_the_new_pulls():
    """A pre-flight estimate that undercounts is worse than none — it is read
    to decide whether a sync is safe against rate limits."""
    est = garmin.estimate_call_count(since_days=7)
    assert est["fixed"] == 6
