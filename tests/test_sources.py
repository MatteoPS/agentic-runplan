"""The source adapter, and above all its unit conversions.

A wrong factor here does not crash — it produces a plausible number. The decay
thresholds (DECAY_NOTE_SPM = 4 spm, DECAY_NOTE_STRIDE_PCT = 5%) are calibrated
on Garmin's units, so a silent factor of two would make every run a finding or
none of them one, and the digest would look entirely normal either way. That is
why the cross-source test below exists and why it is written as an equality
rather than a smoke test.

The constants themselves were pinned against 28 runs present in both caches
(see the module docstring in sources.py). Those caches are gitignored, so the
fixtures here encode the *verified* relationship rather than reading real data.
"""

from __future__ import annotations

from datetime import date

import json

import pytest

from mc import metrics, sources

# One run, expressed the way each API expresses it. Same six samples.
# Garmin: cadence both-legs, stride in centimetres.
# intervals: cadence per-leg (half), step length in millimetres (×10 of cm).
DISTANCE_M = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0]
CADENCE_BOTH_LEGS = [170.0, 172.0, 168.0, 166.0, 164.0, 160.0]
STRIDE_CM = [110.0, 112.0, 108.0, 104.0, 100.0, 96.0]
SPEED_MS = [3.0, 3.1, 3.0, 2.9, 2.8, 2.7]


def garmin_payload(n_repeat: int = 6) -> dict:
    """Garmin's row-per-sample layout with a name→index map."""
    rows = []
    for _ in range(n_repeat):
        for d, c, s, v in zip(DISTANCE_M, CADENCE_BOTH_LEGS, STRIDE_CM, SPEED_MS):
            rows.append({"metrics": [d, c, s, v]})
    return {
        "data": {
            "metricDescriptors": [
                {"key": "sumDistance", "metricsIndex": 0},
                {"key": "directDoubleCadence", "metricsIndex": 1},
                {"key": "directStrideLength", "metricsIndex": 2},
                {"key": "directSpeed", "metricsIndex": 3},
            ],
            "activityDetailMetrics": rows,
        }
    }


def intervals_payload(n_repeat: int = 6) -> list[dict]:
    """intervals' column-per-metric layout, in intervals' own units."""
    distance, cadence, stride, speed = [], [], [], []
    for _ in range(n_repeat):
        distance += DISTANCE_M
        cadence += [c / 2 for c in CADENCE_BOTH_LEGS]  # per leg
        stride += [s * 10 for s in STRIDE_CM]  # cm → mm
        speed += SPEED_MS
    return [
        {"type": "distance", "data": distance},
        {"type": "cadence", "data": cadence},
        {"type": "step_length", "data": stride},
        {"type": "velocity_smooth", "data": speed},
    ]


# --- the load-bearing check ---------------------------------------------------


def test_both_sources_normalize_to_identical_streams():
    """The whole point of the adapter: after normalization, the source is
    unknowable. This is the test that catches a ×2 or ÷10 mistake."""
    g = sources.parse_garmin_streams(garmin_payload())
    i = sources.parse_intervals_streams(intervals_payload())

    assert g is not None and i is not None
    assert g.distance == i.distance
    assert g.cadence == i.cadence
    assert g.stride == pytest.approx(i.stride)
    assert g.speed == i.speed


def test_both_sources_produce_identical_thirds():
    """Same again one level up — the numbers a human actually reads."""
    g = metrics.splits_from_streams(sources.parse_garmin_streams(garmin_payload()))
    i = metrics.splits_from_streams(sources.parse_intervals_streams(intervals_payload()))

    assert g is not None and i is not None
    assert g.cadence == i.cadence
    assert g.stride == i.stride
    assert g.pace == i.pace


def test_cadence_is_doubled_not_halved():
    """Direction matters: intervals counts one leg, so normalized cadence must
    come out ABOVE the raw intervals figure, in Garmin's range."""
    s = sources.parse_intervals_streams(intervals_payload())
    assert s is not None
    assert max(s.cadence) == pytest.approx(172.0)
    assert min(s.cadence) == pytest.approx(160.0)


def test_stride_normalizes_to_metres_from_both_units():
    """110 cm and 1100 mm are both 1.10 m — a plausible stride. 11.0 or 0.011
    would also 'work' arithmetically, which is exactly the danger."""
    g = sources.parse_garmin_streams(garmin_payload())
    i = sources.parse_intervals_streams(intervals_payload())
    assert g is not None and i is not None
    assert g.stride[0] == pytest.approx(1.10)
    assert i.stride[0] == pytest.approx(1.10)


# --- shape handling -----------------------------------------------------------


def test_intervals_streams_without_cadence_or_distance_are_unusable():
    assert sources.parse_intervals_streams([{"type": "heartrate", "data": [140, 141]}]) is None
    assert sources.parse_intervals_streams([]) is None


def test_garmin_streams_tolerate_varying_index_order():
    """Real payloads genuinely differ in metric order — 9 metrics in one, 17 in
    another — which is why lookup is by key name."""
    payload = garmin_payload()
    payload["data"]["metricDescriptors"] = [
        {"key": "directSpeed", "metricsIndex": 3},
        {"key": "directDoubleCadence", "metricsIndex": 1},
        {"key": "sumDistance", "metricsIndex": 0},
    ]
    s = sources.parse_garmin_streams(payload)
    assert s is not None
    assert s.cadence[0] == 170.0
    assert all(v is None for v in s.stride)  # absent stream, not a crash


def test_intervals_has_no_per_sample_gap_without_laps():
    """`types=gap` is a 422. With no laps supplied the slot stays honestly
    empty rather than being quietly filled with raw pace."""
    s = sources.parse_intervals_streams(intervals_payload())
    assert s is not None
    assert all(v is None for v in s.gap_speed)


# --- GAP, which comes from laps rather than samples ---------------------------


def test_lap_gap_is_expanded_across_its_sample_range():
    laps = [
        {"start_index": 0, "end_index": 3, "gap": 3.0},
        {"start_index": 3, "end_index": 6, "gap": 2.5},
    ]
    s = sources.parse_intervals_streams(
        {"streams": intervals_payload(n_repeat=1), "laps": laps}
    )
    assert s is not None
    assert s.gap_speed == [3.0, 3.0, 3.0, 2.5, 2.5, 2.5]


def test_lap_gap_is_read_from_the_original_index_not_the_filtered_one():
    """The subtle one. parse_intervals_streams DROPS samples with zero cadence,
    so a lap lookup done against the output position would slide every GAP
    later in the run — plausible numbers, silently attached to the wrong
    stretch. Sample 1 is dropped here; sample 3 must still get lap 2's GAP."""
    streams = [
        {"type": "distance", "data": [0.0, 50.0, 100.0, 150.0, 200.0, 250.0]},
        {"type": "cadence", "data": [85.0, 0.0, 85.0, 85.0, 85.0, 85.0]},
    ]
    laps = [
        {"start_index": 0, "end_index": 3, "gap": 3.0},
        {"start_index": 3, "end_index": 6, "gap": 2.5},
    ]
    s = sources.parse_intervals_streams({"streams": streams, "laps": laps})
    assert s is not None
    assert len(s) == 5  # the zero-cadence sample is gone
    assert s.gap_speed == [3.0, 3.0, 2.5, 2.5, 2.5]


def test_laps_without_gap_or_indices_are_ignored():
    laps = [{"start_index": 0, "end_index": 3}, {"gap": 2.5}, {"nonsense": True}]
    s = sources.parse_intervals_streams(
        {"streams": intervals_payload(n_repeat=1), "laps": laps}
    )
    assert s is not None
    assert all(v is None for v in s.gap_speed)


def test_cached_envelope_is_unwrapped():
    """What sits on disk is {fetched_at, source, data: {streams, laps}}."""
    payload = {
        "fetched_at": "2026-08-12T00:00:00+00:00",
        "source": "GET /streams+/intervals",
        "data": {"streams": intervals_payload(n_repeat=1),
                 "laps": [{"start_index": 0, "end_index": 6, "gap": 3.0}]},
    }
    s = sources.parse_intervals_streams(payload)
    assert s is not None
    assert len(s) == 6
    assert s.gap_speed == [3.0] * 6


# --- the latlng stream, which is the only place coordinates exist -------------


def test_first_fix_reads_two_parallel_arrays():
    payload = [{"type": "latlng", "data": [40.79967, 40.79964], "data2": [-73.957855, -73.95786]}]
    assert sources.first_fix(payload) == (40.79967, -73.957855)


def test_first_fix_skips_leading_nulls():
    payload = [{"type": "latlng", "data": [None, 40.5], "data2": [None, -73.9]}]
    assert sources.first_fix(payload) == (40.5, -73.9)


def test_first_fix_on_an_indoor_run_is_none():
    """An indoor run returns an empty stream list — a clean 'no GPS', not an
    error, and location_from_activities should simply skip it."""
    assert sources.first_fix([]) is None
    assert sources.first_fix([{"type": "cadence", "data": [80]}]) is None


# --- activity normalization ---------------------------------------------------


INTERVALS_RUN = {
    "id": "i172711843",
    "type": "Run",
    "start_date_local": "2026-08-05T06:18:28",
    "start_date": "2026-08-05T10:18:28Z",
    "distance": 20135.18,
    "moving_time": 6988,
    "average_heartrate": 145,
    "average_cadence": 83.215195,
    "gap": 2.9680283,
    "total_elevation_gain": 322.28827,
}


def test_normalized_activity_is_garmin_shaped():
    a = sources.normalize_intervals_activity(INTERVALS_RUN)
    assert a["activityId"] == "i172711843"
    assert a["activityType"]["typeKey"] == "Run"
    # Garmin's startTimeLocal is space-separated; metrics parses it with
    # "%Y-%m-%d %H:%M:%S", so a stray T would silently drop the activity.
    assert a["startTimeLocal"] == "2026-08-05 06:18:28"
    assert a["distance"] == 20135.18
    assert a["duration"] == 6988
    assert a["averageHR"] == 145
    assert a["avgGradeAdjustedSpeed"] == pytest.approx(2.9680283)
    assert a["elevationGain"] == pytest.approx(322.28827)


def test_normalized_activity_cadence_matches_garmins_scale():
    """The real Garmin figure for this same run was 167.109375."""
    a = sources.normalize_intervals_activity(INTERVALS_RUN)
    assert a["averageRunningCadenceInStepsPerMinute"] == pytest.approx(167.11, abs=0.7)


def test_normalized_activity_parses_through_metrics():
    """End to end: an intervals activity must survive the Garmin-shaped
    reader that every call site uses."""
    row = metrics.build_run_metrics(sources.normalize_intervals_activity(INTERVALS_RUN))
    assert row is not None
    assert row.day.isoformat() == "2026-08-05"
    assert row.distance_mi == pytest.approx(12.51, abs=0.01)
    assert row.cadence_spm == pytest.approx(167.11, abs=0.7)


def test_normalized_activity_carries_no_coordinates():
    """Documents a real gap rather than papering over it: intervals exposes no
    lat/lon on the activity at all, so weather location must come from the
    latlng stream. Asserting None keeps that honest if someone 'fixes' it by
    inventing a field."""
    a = sources.normalize_intervals_activity(INTERVALS_RUN)
    assert a["startLatitude"] is None
    assert a["startLongitude"] is None


# --- merging the two sources ---------------------------------------------------


GARMIN_RUN = {
    "activityId": 23861431946,
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-08-05 06:18:28",
    "startTimeGMT": "2026-08-05 10:18:28",
    "distance": 20135.18,
    "duration": 6988,
    "averageRunningCadenceInStepsPerMinute": 167.109375,
}


@pytest.fixture
def caches(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.cfg, "RAW_GARMIN_DIR", tmp_path / "garmin")
    monkeypatch.setattr(sources.cfg, "RAW_INTERVALS_DIR", tmp_path / "intervals")

    def write(root, kind, records):
        d = root / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.json").write_text(json.dumps({"data": records}))

    return lambda g, i: (
        write(tmp_path / "garmin", "activities", g),
        write(tmp_path / "intervals", "activities", i),
    )


def test_garmin_wins_where_both_have_the_same_session(caches):
    caches([GARMIN_RUN], [INTERVALS_RUN])
    out = sources.activities()
    assert len(out) == 1
    assert out[0]["_source"] == sources.GARMIN


def test_intervals_only_sessions_are_included(caches):
    """The case that matters on a laptop that has been shut: Garmin's cache is
    days old, and this morning's run exists only in intervals. Preferring
    Garmin wholesale would hide it."""
    caches([], [INTERVALS_RUN])
    out = sources.activities()
    assert len(out) == 1
    assert out[0]["_source"] == sources.INTERVALS
    assert out[0]["activityId"] == "i172711843"


def test_a_stale_garmin_cache_does_not_hide_a_newer_intervals_run(caches):
    older = {**GARMIN_RUN, "startTimeLocal": "2026-08-01 07:00:00",
             "startTimeGMT": "2026-08-01 11:00:00"}
    caches([older], [INTERVALS_RUN])
    out = sources.activities()
    assert len(out) == 2
    assert {a["_source"] for a in out} == {sources.GARMIN, sources.INTERVALS}


def test_no_caches_at_all_is_empty_not_an_error(caches):
    caches([], [])
    assert sources.activities() == []


# --- wellness: the readings C2 actually spends ---------------------------------


@pytest.fixture
def wellness(tmp_path, monkeypatch):
    """Write into both caches independently, so each precedence case is exact."""
    monkeypatch.setattr(sources.cfg, "RAW_GARMIN_DIR", tmp_path / "garmin")
    monkeypatch.setattr(sources.cfg, "RAW_INTERVALS_DIR", tmp_path / "intervals")

    def put_garmin(metric: str, day: str, data):
        d = tmp_path / "garmin" / "wellness" / metric
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{day}.json").write_text(json.dumps({"data": data}))

    def put_intervals(records):
        d = tmp_path / "intervals" / "wellness"
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.json").write_text(json.dumps({"data": records}))

    return put_garmin, put_intervals


AS_OF = date(2026, 8, 11)


def test_intervals_fills_in_when_garmin_has_nothing(wellness):
    _, put_intervals = wellness
    put_intervals([{"id": "2026-08-11", "hrv": 45.0, "restingHR": 42, "sleepSecs": 28920}])

    day, data, source = sources.wellness_value("hrv", AS_OF)
    assert (day, source) == ("2026-08-11", sources.INTERVALS)
    assert data["hrvSummary"]["lastNightAvg"] == 45.0

    day, data, source = sources.wellness_value("sleep", AS_OF)
    assert data["dailySleepDTO"]["sleepTimeSeconds"] == 28920

    day, data, source = sources.wellness_value("stats", AS_OF)
    assert data["restingHeartRate"] == 42


def test_garmin_wins_a_tie_because_it_carries_more(wellness):
    put_garmin, put_intervals = wellness
    put_garmin("hrv", "2026-08-11", {"hrvSummary": {"lastNightAvg": 44, "status": "BALANCED"}})
    put_intervals([{"id": "2026-08-11", "hrv": 44.0}])

    day, data, source = sources.wellness_value("hrv", AS_OF)
    assert source == sources.GARMIN
    assert data["hrvSummary"]["status"] == "BALANCED"


def test_a_fresher_intervals_reading_beats_an_older_garmin_one(wellness):
    """Both caches walk back a week. Preferring Garmin outright would answer a
    question about last night with a reading from four days ago whenever the
    watch missed a night."""
    put_garmin, put_intervals = wellness
    put_garmin("hrv", "2026-08-07", {"hrvSummary": {"lastNightAvg": 40, "status": "LOW"}})
    put_intervals([{"id": "2026-08-11", "hrv": 45.0}])

    day, _, source = sources.wellness_value("hrv", AS_OF)
    assert (day, source) == ("2026-08-11", sources.INTERVALS)


def test_a_garmin_payload_with_a_null_value_does_not_block_the_fallback(wellness):
    """The real case, found on 11-08: Garmin writes a populated dailySleepDTO
    whose sleepTimeSeconds is null on a night it tracked nothing. That is a
    record that looks like data and carries none — and sleep <6h is a C2
    readiness signal, so silently losing it costs a decision."""
    put_garmin, put_intervals = wellness
    put_garmin("sleep", "2026-08-11", {"dailySleepDTO": {"sleepTimeSeconds": None}})
    put_intervals([{"id": "2026-08-11", "sleepSecs": 28920}])

    day, data, source = sources.wellness_value("sleep", AS_OF)
    assert source == sources.INTERVALS
    assert data["dailySleepDTO"]["sleepTimeSeconds"] == 28920


def test_garmin_only_metrics_have_no_intervals_shape(wellness):
    """intervals has a `readiness` field, but it is not Garmin's training
    readiness score. Absent beats wrong under someone else's label."""
    _, put_intervals = wellness
    put_intervals([{"id": "2026-08-11", "readiness": 77, "hrv": 45.0}])
    assert sources.wellness_value("training_readiness", AS_OF) is None
    assert sources.wellness_value("max_metrics", AS_OF) is None


def test_a_null_intervals_field_is_not_a_reading(wellness):
    """`stress` is null on every recent real record — that must read as no
    data, not as a stress level of None."""
    _, put_intervals = wellness
    put_intervals([{"id": "2026-08-11", "stress": None, "hrv": 45.0}])
    assert sources.wellness_value("stress", AS_OF) is None


def test_wellness_outside_the_lookback_is_not_reported(wellness):
    _, put_intervals = wellness
    put_intervals([{"id": "2026-07-01", "hrv": 45.0}])
    assert sources.wellness_value("hrv", AS_OF) is None


# --- HR settings: a snapshot, not a daily reading -------------------------------


@pytest.fixture
def hr_settings_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sources.cfg, "RAW_GARMIN_DIR", tmp_path / "garmin")

    def put(day: str, data):
        d = tmp_path / "garmin" / "wellness" / "hr_settings"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{day}.json").write_text(json.dumps({"data": data}))

    return put


def test_hr_settings_has_no_lookback_window(hr_settings_cache):
    """The point of the whole feature. A setting is true until it is changed,
    so a snapshot from months ago is still the right answer — unlike HRV,
    where a reading that old is no answer at all."""
    hr_settings_cache("2026-01-05", {"userData": {"maxHeartRate": 181}})
    got = sources.garmin_hr_settings(date(2026, 8, 20))
    assert got is not None
    assert got[0] == "2026-01-05"


def test_hr_settings_takes_the_newest_snapshot_at_or_before_as_of(hr_settings_cache):
    """`mc digest --date` must not leak a setting change that happened after
    the day being rendered."""
    hr_settings_cache("2026-08-01", {"userData": {"maxHeartRate": 180}})
    hr_settings_cache("2026-08-19", {"userData": {"maxHeartRate": 183}})
    hr_settings_cache("2026-08-25", {"userData": {"maxHeartRate": 190}})
    day, data = sources.garmin_hr_settings(date(2026, 8, 20))
    assert (day, data["userData"]["maxHeartRate"]) == ("2026-08-19", 183)


def test_no_hr_settings_cache_is_none_not_an_error(hr_settings_cache):
    assert sources.garmin_hr_settings(date(2026, 8, 20)) is None
