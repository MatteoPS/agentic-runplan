import json
from datetime import date, datetime

import pytest

from mc import metrics
from mc.weather import HourlyWeather


def activity(
    *,
    start="2026-08-03 20:13:06",
    type_key="running",
    distance=6676.25,
    duration=2222.25,
    cadence=167.65,
    gap_speed=3.019,
    elev_gain=61.0,
    elev_loss=65.0,
    hr=145.0,
):
    """Shaped from a real Garmin activity summary (23842793466)."""
    return {
        "startTimeLocal": start,
        "activityType": {"typeKey": type_key},
        "distance": distance,
        "duration": duration,
        "averageHR": hr,
        "averageRunningCadenceInStepsPerMinute": cadence,
        "avgGradeAdjustedSpeed": gap_speed,
        "elevationGain": elev_gain,
        "elevationLoss": elev_loss,
    }


AS_OF = date(2026, 8, 4)


# --- extraction --------------------------------------------------------------------


def test_extracts_the_fields_that_were_previously_dropped():
    row = metrics.build_run_metrics(activity())
    assert row.cadence_spm == 167.65
    assert round(row.elev_gain_ft) == 200
    assert round(row.elev_loss_ft) == 213
    assert row.gap_min_per_mi is not None


def test_pace_comes_from_distance_and_duration():
    row = metrics.build_run_metrics(activity(distance=1609.344, duration=540.0))
    assert row.pace_min_per_mi == 9.0


def test_gap_pace_converts_from_metres_per_second():
    # 1609.344 m in 540 s = 9:00/mi flat-equivalent
    row = metrics.build_run_metrics(activity(gap_speed=1609.344 / 540))
    assert round(row.gap_min_per_mi, 3) == 9.0


def test_terrain_cost_is_positive_when_the_route_cost_time():
    row = metrics.build_run_metrics(
        activity(distance=1609.344, duration=600.0, gap_speed=1609.344 / 540)
    )
    # ran 10:00, flat-equivalent 9:00 -> the hills cost 60 s/mi
    assert round(row.terrain_cost_sec_per_mi) == 60


def test_terrain_cost_is_negative_on_a_net_descent():
    row = metrics.build_run_metrics(
        activity(distance=1609.344, duration=540.0, gap_speed=1609.344 / 600)
    )
    assert round(row.terrain_cost_sec_per_mi) == -60


def test_zero_means_missing_not_measured():
    """Garmin writes 0 rather than omitting a field it has no reading for —
    an indoor run has no elevation or GPS-derived grade."""
    row = metrics.build_run_metrics(activity(cadence=0, elev_gain=0, gap_speed=0))
    assert row.cadence_spm is None
    assert row.elev_gain_ft is None
    assert row.gap_min_per_mi is None
    assert row.terrain_cost_sec_per_mi is None


def test_missing_fields_do_not_raise():
    row = metrics.build_run_metrics(
        {"startTimeLocal": "2026-08-03 20:13:06", "activityType": {"typeKey": "running"}}
    )
    assert row.cadence_spm is None and row.pace_min_per_mi is None


def test_activity_without_a_start_time_is_skipped():
    assert metrics.build_run_metrics({"activityType": {"typeKey": "running"}}) is None


# --- windowing ----------------------------------------------------------------------


def test_only_runs_are_included():
    rows = metrics.run_metrics(
        [activity(), activity(type_key="elliptical"), activity(type_key="cycling")], AS_OF
    )
    assert len(rows) == 1


def test_activities_outside_the_window_are_excluded():
    rows = metrics.run_metrics(
        [activity(start="2026-07-01 07:00:00"), activity()], AS_OF, days=14
    )
    assert len(rows) == 1


def test_future_activities_are_excluded():
    rows = metrics.run_metrics([activity(start="2026-08-09 07:00:00")], AS_OF)
    assert rows == []


def test_rows_are_newest_first():
    rows = metrics.run_metrics(
        [
            activity(start="2026-07-29 19:00:00"),
            activity(start="2026-08-03 20:13:06"),
            activity(start="2026-08-01 11:18:00"),
        ],
        AS_OF,
    )
    assert [r.label[:5] for r in rows] == ["03-08", "01-08", "29-07"]


# --- cadence baseline ----------------------------------------------------------------


def test_baseline_is_the_median_of_recent_runs():
    acts = [
        activity(start=f"{day} 07:00:00", cadence=c)
        for day, c in zip(
            ["2026-07-31", "2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"],
            [160, 165, 170, 175, 200],
        )
    ]
    baseline = metrics.cadence_baseline(acts, AS_OF)
    assert baseline.median_spm == 170  # median, so the 200 outlier doesn't drag it
    assert baseline.n_runs == 5
    assert baseline.usable


def test_baseline_below_the_minimum_sample_is_not_usable():
    baseline = metrics.cadence_baseline([activity()], AS_OF)
    assert baseline.n_runs == 1
    assert not baseline.usable


def test_runs_without_cadence_are_not_counted_in_the_baseline():
    baseline = metrics.cadence_baseline([activity(cadence=0), activity(cadence=None)], AS_OF)
    assert baseline.median_spm is None
    assert baseline.n_runs == 0


# --- cadence note ---------------------------------------------------------------------


def usable_baseline(median=168.0):
    return metrics.CadenceBaseline(median_spm=median, n_runs=10, window_days=28)


def test_note_fires_only_on_a_meaningful_drop():
    row = metrics.build_run_metrics(activity(cadence=160))
    assert metrics.cadence_note(row, usable_baseline()) is not None


def test_no_note_for_small_variation():
    row = metrics.build_run_metrics(activity(cadence=165))
    assert metrics.cadence_note(row, usable_baseline()) is None


def test_no_note_for_cadence_above_baseline():
    row = metrics.build_run_metrics(activity(cadence=180))
    assert metrics.cadence_note(row, usable_baseline()) is None


def test_no_note_without_a_usable_baseline():
    """Two runs is not a baseline — better silent than authoritative-sounding."""
    thin = metrics.CadenceBaseline(median_spm=168.0, n_runs=2, window_days=28)
    assert metrics.cadence_note(metrics.build_run_metrics(activity(cadence=150)), thin) is None


def test_note_quotes_pace_alongside_and_refuses_to_diagnose():
    """The likeliest cause of low cadence is simply running slower. Stating the
    drop without the pace would manufacture a worry; claiming a cause would
    break D6."""
    row = metrics.build_run_metrics(activity(cadence=158))
    note = metrics.cadence_note(row, usable_baseline())
    assert "min/mi" in note
    assert "a number, not a finding" in note


# --- rendering ---------------------------------------------------------------------------


def test_form_table_renders_em_dash_for_missing_values():
    rows = metrics.run_metrics([activity(cadence=0, elev_gain=0, gap_speed=0)], AS_OF)
    assert any("—" in line for line in metrics.form_table(rows))


def test_form_table_handles_no_runs():
    assert "No runs" in metrics.form_table([])[0]


def test_summary_says_so_when_the_baseline_is_too_thin():
    lines = metrics.form_summary_lines([], metrics.cadence_baseline([], AS_OF))
    assert any("not enough runs" in line for line in lines)


def test_summary_always_carries_the_descriptive_only_caveat():
    lines = metrics.form_summary_lines([], metrics.cadence_baseline([], AS_OF))
    assert any("D6" in line for line in lines)


def test_pace_formatting_rounds_up_to_the_next_minute():
    assert metrics._fmt_pace(8.999) == "9:00"
    assert metrics._fmt_pace(None) == "—"


# --- weather attribution ------------------------------------------------------------


def hour(when, feels=80.0, dew=70.0):
    return HourlyWeather(
        when=when, temp_f=feels, feels_like_f=feels, humidity_pct=70.0,
        dew_point_f=dew, precip_prob=0.0, precip_in=0.0, wind_mph=3.0,
    )


def test_run_is_joined_to_the_hour_it_happened_in():
    rows = metrics.run_metrics([activity(start="2026-08-03 20:13:06")], AS_OF)
    enriched = metrics.enrich_with_weather(
        rows,
        [hour(datetime(2026, 8, 3, 19), dew=60.0), hour(datetime(2026, 8, 3, 20), dew=72.0)],
    )
    assert enriched[0].dew_point_f == 72.0


def test_a_run_outside_the_cached_window_stays_unknown():
    """Never attribute a run to whatever weather happens to be nearest in the
    file — an uncovered day must read as unknown."""
    rows = metrics.run_metrics([activity(start="2026-08-03 20:13:06")], AS_OF)
    enriched = metrics.enrich_with_weather(rows, [hour(datetime(2026, 7, 20, 20))])
    assert enriched[0].dew_point_f is None
    assert "unknown" in metrics.conditions_clause(enriched[0])


def test_enrichment_without_any_weather_is_a_no_op():
    rows = metrics.run_metrics([activity()], AS_OF)
    assert metrics.enrich_with_weather(rows, [])[0].dew_point_f is None


def test_conditions_clause_keeps_unit_capitalisation():
    """str.capitalize() would render 65°F as 65°f."""
    rows = metrics.enrich_with_weather(
        metrics.run_metrics([activity(start="2026-08-03 20:13:06")], AS_OF),
        [hour(datetime(2026, 8, 3, 20), feels=65.0, dew=53.0)],
    )
    assert "53°F" in metrics._sentence(metrics.conditions_clause(rows[0]))


# --- pace outliers -------------------------------------------------------------------


def test_pace_note_fires_only_on_a_real_outlier():
    row = metrics.build_run_metrics(activity(distance=1609.344, duration=600.0, gap_speed=1609.344 / 600))
    assert metrics.pace_note(row, 9.0) is not None   # 10:00 vs 9:00 baseline
    assert metrics.pace_note(row, 9.9) is None       # within 30 s/mi


def test_pace_note_asks_rather_than_concludes():
    """Heat is the most convenient explanation available, so it is handed over
    as a question to confirm — never as a verdict (E3)."""
    row = metrics.build_run_metrics(activity(distance=1609.344, duration=600.0, gap_speed=1609.344 / 600))
    note = metrics.pace_note(row, 9.0)
    assert "was it hot" in note.lower()
    assert "conditions" in note.lower()


def test_no_pace_note_without_a_baseline():
    assert metrics.pace_note(metrics.build_run_metrics(activity()), None) is None


# --- within-run decay ------------------------------------------------------------------


def details_payload(
    cadences,
    distance_total=16093.44,
    strides=None,
    speeds=None,
    gap_speeds=None,
):
    """Shaped like a real get_activity_details response, whose metric indices
    genuinely vary between activities — hence the key lookup.

    `strides` are centimetres and `speeds`/`gap_speeds` m/s, matching what
    Garmin actually writes. Passing none of them models an older cached payload
    that predates those streams.
    """
    n = len(cadences)
    optional = {
        "directStrideLength": strides,
        "directSpeed": speeds,
        "directGradeAdjustedSpeed": gap_speeds,
    }
    descriptors = [
        {"key": "directHeartRate", "metricsIndex": 0},
        {"key": "sumDistance", "metricsIndex": 1},
        {"key": "directDoubleCadence", "metricsIndex": 2},
    ]
    present = [(key, values) for key, values in optional.items() if values is not None]
    for offset, (key, _) in enumerate(present):
        descriptors.append({"key": key, "metricsIndex": 3 + offset})

    rows = []
    for i, cadence in enumerate(cadences):
        row = [140.0, distance_total * i / n, cadence]
        row += [values[i] for _, values in present]
        rows.append({"metrics": row})

    return {"data": {"metricDescriptors": descriptors, "activityDetailMetrics": rows}}


@pytest.fixture
def details_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics.cfg, "RAW_GARMIN_DIR", tmp_path)
    d = tmp_path / "activities" / "details"
    d.mkdir(parents=True)
    return d


def write_details(details_dir, activity_id, cadences, **kw):
    (details_dir / f"{activity_id}.json").write_text(json.dumps(details_payload(cadences, **kw)))


def test_splits_are_taken_by_distance_not_sample_count(details_dir):
    write_details(details_dir, "1", [170.0] * 60 + [160.0] * 60)
    splits = metrics.run_splits("1")
    assert splits.cadence.first == 170.0
    assert splits.cadence.last == 160.0
    assert splits.drift_spm == -10.0


def test_stopped_samples_are_excluded(details_dir):
    """Cadence 0 is a traffic light, not a stride."""
    write_details(details_dir, "1", [170.0] * 60 + [0.0] * 30 + [170.0] * 60)
    assert metrics.run_splits("1").drift_spm == 0.0


def test_missing_details_file_is_not_an_error():
    assert metrics.run_splits("nope") is None
    assert metrics.run_splits(None) is None


def test_too_few_samples_to_split(details_dir):
    write_details(details_dir, "1", [170.0] * 10)
    assert metrics.run_splits("1") is None


def test_decay_note_needs_a_long_enough_run(details_dir):
    """'Did form hold up late' isn't a question a 2-miler asks."""
    write_details(details_dir, "1", [175.0] * 60 + [160.0] * 60)
    splits = metrics.run_splits("1")
    short = metrics.build_run_metrics(activity(distance=3218.0))  # 2 mi
    long = metrics.build_run_metrics(activity(distance=16093.44))  # 10 mi
    assert metrics.decay_note(short, splits) is None
    assert metrics.decay_note(long, splits) is not None


def test_no_decay_note_when_cadence_holds(details_dir):
    write_details(details_dir, "1", [167.0] * 60 + [165.0] * 60)
    long = metrics.build_run_metrics(activity(distance=16093.44))
    assert metrics.decay_note(long, metrics.run_splits("1")) is None


def test_decay_note_refuses_to_diagnose(details_dir):
    write_details(details_dir, "1", [175.0] * 60 + [160.0] * 60)
    long = metrics.build_run_metrics(activity(distance=16093.44))
    note = metrics.decay_note(long, metrics.run_splits("1"))
    assert "numbers, not a finding" in note


def test_stride_and_gap_thirds_are_read_from_the_same_payload(details_dir):
    """Both streams ship alongside cadence — reading them costs no API call."""
    write_details(
        details_dir,
        "1",
        [165.0] * 120,
        strides=[100.0] * 60 + [90.0] * 60,  # cm
        speeds=[2.75] * 60 + [2.50] * 60,  # m/s
        gap_speeds=[2.80] * 60 + [2.55] * 60,
    )
    splits = metrics.run_splits("1")
    assert splits.stride.first == 1.0
    assert splits.stride.last == 0.9
    assert splits.stride_drift_pct == -10.0
    # 2.80 m/s ≈ 9:35/mi, 2.55 m/s ≈ 10:31/mi — a ~56 s/mi grade-adjusted fade.
    assert splits.gap_drift_sec == pytest.approx(56, abs=1)
    assert splits.pace.first < splits.pace.last  # raw pace slowed too


def test_stride_collapse_is_caught_when_cadence_holds(details_dir):
    """The 2025 NYC marathon case: cadence rose while stride fell 10%.

    A cadence-only check reported nothing about the run most worth asking
    about, which is the whole reason stride length is read here.
    """
    write_details(
        details_dir,
        "1",
        [160.0] * 60 + [166.0] * 60,  # cadence *rose*
        strides=[97.0] * 60 + [85.0] * 60,
    )
    splits = metrics.run_splits("1")
    assert splits.drift_spm == 6.0  # cadence alone would say all is well
    long = metrics.build_run_metrics(activity(distance=16093.44))
    note = metrics.decay_note(long, splits)
    assert note is not None
    assert "stride" in note


def test_gap_decay_alone_does_not_fire_the_note(details_dir):
    """A warmup and a cooldown live in the first and last thirds, so pace fade
    is real often enough to report and spurious often enough not to trigger."""
    write_details(
        details_dir,
        "1",
        [165.0] * 120,
        strides=[100.0] * 120,
        gap_speeds=[2.80] * 60 + [2.55] * 60,
    )
    long = metrics.build_run_metrics(activity(distance=16093.44))
    assert metrics.decay_note(long, metrics.run_splits("1")) is None


def test_gap_rides_along_as_context_when_stride_trips(details_dir):
    write_details(
        details_dir,
        "1",
        [165.0] * 120,
        strides=[100.0] * 60 + [90.0] * 60,
        speeds=[2.75] * 60 + [2.40] * 60,
        gap_speeds=[2.80] * 60 + [2.55] * 60,
    )
    long = metrics.build_run_metrics(activity(distance=16093.44))
    note = metrics.decay_note(long, metrics.run_splits("1"))
    assert "grade-adjusted pace" in note
    assert "terrain" in note


def test_terrain_cost_separates_uphill_from_slower(details_dir):
    """Last third raw-vs-GAP wide open: that stretch was uphill, not a fade."""
    write_details(
        details_dir,
        "1",
        [165.0] * 120,
        speeds=[2.75] * 60 + [2.40] * 60,  # raw slowed
        gap_speeds=[2.78] * 60 + [2.76] * 60,  # grade-adjusted barely moved
    )
    splits = metrics.run_splits("1")
    assert splits.terrain_cost_sec_per_mi("first") == pytest.approx(4, abs=2)
    assert splits.terrain_cost_sec_per_mi("last") == pytest.approx(87, abs=2)
    assert abs(splits.gap_drift_sec) < 5  # no fade once the hill is accounted for


def test_no_decay_note_when_all_three_hold(details_dir):
    write_details(
        details_dir,
        "1",
        [167.0] * 60 + [165.0] * 60,
        strides=[100.0] * 60 + [99.0] * 60,
        gap_speeds=[2.80] * 60 + [2.78] * 60,
    )
    long = metrics.build_run_metrics(activity(distance=16093.44))
    assert metrics.decay_note(long, metrics.run_splits("1")) is None


def test_pattern_gloss_names_which_of_the_two_fell(details_dir):
    """Cadence easing with stride intact is a cooldown; the reverse is not."""
    long = metrics.build_run_metrics(activity(distance=16093.44))

    write_details(
        details_dir, "1", [160.0] * 60 + [166.0] * 60, strides=[97.0] * 60 + [85.0] * 60
    )
    assert "Stride shortened while cadence held" in metrics.decay_note(
        long, metrics.run_splits("1")
    )

    write_details(
        details_dir, "2", [174.0] * 60 + [166.0] * 60, strides=[100.0] * 60 + [106.0] * 60
    )
    assert "looks more like backing off or a cooldown" in metrics.decay_note(
        long, metrics.run_splits("2")
    )

    write_details(
        details_dir, "3", [174.0] * 60 + [164.0] * 60, strides=[100.0] * 60 + [90.0] * 60
    )
    assert "Both fell" in metrics.decay_note(long, metrics.run_splits("3"))


def test_older_payloads_without_the_new_streams_still_work(details_dir):
    """Cached details predating these streams degrade to cadence only."""
    write_details(details_dir, "1", [175.0] * 60 + [160.0] * 60)
    splits = metrics.run_splits("1")
    assert splits.stride.first is None
    assert splits.stride_drift_pct is None
    assert splits.gap_drift_sec is None
    long = metrics.build_run_metrics(activity(distance=16093.44))
    note = metrics.decay_note(long, splits)
    assert "cadence" in note
    assert "stride" not in note


def test_stopped_samples_do_not_become_absurd_paces(details_dir):
    """A red light is 0 m/s; a median of paces would let it dominate."""
    write_details(
        details_dir,
        "1",
        [165.0] * 120,
        speeds=[2.75] * 50 + [0.0] * 10 + [2.75] * 60,
    )
    splits = metrics.run_splits("1")
    assert splits.pace.first == pytest.approx(splits.pace.last, abs=0.01)
