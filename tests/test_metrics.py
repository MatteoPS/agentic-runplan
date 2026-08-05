from datetime import date

from mc import metrics


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
