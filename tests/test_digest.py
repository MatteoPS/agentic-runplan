"""The digest's Max HR line.

Where Max HR lives was a finding, not a contract: it is on the HR *zone*
configuration as `maxHeartRateUsed`, not on either endpoint whose name suggests
it (`get_userprofile_settings()` is locale and display preferences;
`get_user_profile().userData` has VO2max and lactate-threshold HR but no
maximum). Nothing in garminconnect types this, so these tests pin the confirmed
path — and, just as importantly, pin what happens when it is absent: the two
"no number" cases mean different things and must not collapse into one line.
"""

from __future__ import annotations

import dataclasses

import pytest

from mc import digest


@pytest.fixture
def empty_snapshot() -> digest.WellnessSnapshot:
    """Everything absent, so the Max HR line is the only thing under test."""
    return digest.WellnessSnapshot(
        training_readiness=None, hrv=None, sleep=None, stats=None, stress=None,
        training_status=None, max_metrics=None, intervals_ctl_atl_tsb=None,
        hr_settings=None,
    )


def max_hr_line(snapshot: digest.WellnessSnapshot) -> str:
    return next(line for line in digest._wellness_snapshot_lines(snapshot)
                if line.startswith("- Max HR:"))


# The live 20-08-2026 payload, trimmed to the fields under test.
LIVE_SNAPSHOT = {
    "user_settings": {"userData": {"vo2MaxRunning": 50.0, "lactateThresholdHeartRate": 162}},
    "heart_rate_zones": [{
        "trainingMethod": "HR_MAX", "restingHeartRateUsed": 59,
        "lactateThresholdHeartRateUsed": 162, "zone1Floor": 92, "zone5Floor": 165,
        "maxHeartRateUsed": 183, "sport": "DEFAULT",
    }],
}


def test_max_hr_reads_the_confirmed_field_path():
    assert digest.extract_max_hr(LIVE_SNAPSHOT) == 183


def test_the_default_sport_profile_wins_over_a_sport_specific_one():
    """Zones are per sport profile; DEFAULT is the account-wide one, and list
    order is not a guarantee."""
    data = {"heart_rate_zones": [
        {"sport": "CYCLING", "maxHeartRateUsed": 175},
        {"sport": "DEFAULT", "maxHeartRateUsed": 183},
    ]}
    assert digest.extract_max_hr(data) == 183


def test_a_sport_profile_is_used_when_there_is_no_default():
    """An added sport profile must not blank the line."""
    data = {"heart_rate_zones": [{"sport": "RUNNING", "maxHeartRateUsed": 183}]}
    assert digest.extract_max_hr(data) == 183


def test_lactate_threshold_hr_is_not_mistaken_for_max_hr():
    """Both numbers sit in the same object and one is plausible as the other —
    exactly the failure that does not crash."""
    data = {"heart_rate_zones": [
        {"sport": "DEFAULT", "lactateThresholdHeartRateUsed": 162, "restingHeartRateUsed": 59},
    ]}
    assert digest.extract_max_hr(data) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"heart_rate_zones": []},
        {"heart_rate_zones": [{"sport": "DEFAULT"}]},
        {"heart_rate_zones": [{"sport": "DEFAULT", "maxHeartRateUsed": None}]},
        # A zero is not a heart rate.
        {"heart_rate_zones": [{"sport": "DEFAULT", "maxHeartRateUsed": 0}]},
        {"heart_rate_zones": "not a list"},
        {"heart_rate_zones": ["not a dict"]},
        # The endpoint that looks right and is not.
        {"user_settings": {"userData": {"heartRateFormat": {"formatKey": "bpm"}}}},
        None,
        [],
    ],
)
def test_max_hr_is_none_rather_than_a_plausible_number(payload):
    assert digest.extract_max_hr(payload) is None


def test_line_names_the_snapshot_date_and_source(empty_snapshot):
    snapshot = dataclasses.replace(empty_snapshot, hr_settings=("2026-08-22", LIVE_SNAPSHOT))
    assert max_hr_line(snapshot) == "- Max HR: 183 bpm (2026-08-22 · garmin)"


def test_never_synced_and_shape_changed_are_different_lines(empty_snapshot):
    """Both print no number, and conflating them would hide a real regression
    behind an instruction to run a sync that has already been run."""
    never = max_hr_line(empty_snapshot)
    changed = max_hr_line(
        dataclasses.replace(empty_snapshot, hr_settings=("2026-08-22", {"heart_rate_zones": []}))
    )
    assert "no snapshot yet" in never
    assert "shape may have changed" in changed
    assert never != changed
