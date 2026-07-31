from datetime import date

from mc import traininglog as tlog


def _activity(day: str, type_key: str, distance_m=None, duration_s=None, avg_hr=None):
    return {
        "startTimeLocal": f"2026-{day} 07:00:00",
        "activityType": {"typeKey": type_key},
        "distance": distance_m,
        "duration": duration_s,
        "averageHR": avg_hr,
    }


# --- load/save round-trip ------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "training-log.md"
    rows = [
        tlog.LogRow(date=date(2026, 7, 28), proposed="Elliptical 60min", actual=tlog.PENDING),
        tlog.LogRow(date=date(2026, 7, 27), proposed="6 mi easy", actual="run 6.1mi 54min HR153"),
    ]
    tlog.save_log(rows, path=path)
    loaded = tlog.load_log(path=path)
    assert len(loaded) == 2
    # sorted by date ascending regardless of input order
    assert [r.date for r in loaded] == [date(2026, 7, 27), date(2026, 7, 28)]
    assert loaded[1].proposed == "Elliptical 60min"
    assert loaded[1].actual == tlog.PENDING


def test_load_missing_file_returns_empty(tmp_path):
    assert tlog.load_log(path=tmp_path / "nope.md") == []


def test_save_produces_valid_markdown_table(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.save_log([tlog.LogRow(date=date(2026, 7, 28), proposed="X", actual="Y")], path=path)
    content = path.read_text()
    assert "# Training log" in content
    assert "| Date | Proposed | Actual |" in content
    assert "| 28-07 | X | Y |" in content


# --- record_proposed -----------------------------------------------------------------


def test_record_proposed_appends_new_row(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.record_proposed(date(2026, 7, 28), "Elliptical 60min", path=path)
    rows = tlog.load_log(path=path)
    assert len(rows) == 1
    assert rows[0].proposed == "Elliptical 60min"
    assert rows[0].actual == tlog.PENDING


def test_record_proposed_updates_existing_row_without_duplicating(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.record_proposed(date(2026, 7, 28), "Elliptical 60min", path=path)
    tlog.record_proposed(date(2026, 7, 28), "Elliptical 45min (revised)", path=path)
    rows = tlog.load_log(path=path)
    assert len(rows) == 1
    assert rows[0].proposed == "Elliptical 45min (revised)"


def test_record_proposed_preserves_actual_when_updating_proposed(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.save_log([tlog.LogRow(date=date(2026, 7, 27), proposed="old", actual="run 6.1mi")], path=path)
    tlog.record_proposed(date(2026, 7, 27), "new proposal", path=path)
    rows = tlog.load_log(path=path)
    assert rows[0].actual == "run 6.1mi"


# --- describe_actual_session ----------------------------------------------------------


def test_describe_actual_session_run():
    activities = [_activity("07-27", "running", distance_m=9824.5, duration_s=3258, avg_hr=153)]
    desc = tlog.describe_actual_session(activities, date(2026, 7, 27))
    assert "run" in desc
    assert "6.1mi" in desc
    assert "54min" in desc
    assert "HR153" in desc


def test_describe_actual_session_cross_training_no_distance():
    activities = [_activity("07-28", "elliptical", distance_m=8000, duration_s=3600, avg_hr=140)]
    desc = tlog.describe_actual_session(activities, date(2026, 7, 28))
    assert "cross" in desc
    assert "8000" not in desc and "5.0mi" not in desc  # elliptical distance is meaningless, never shown
    assert "60min" in desc


def test_describe_actual_session_nothing_logged():
    assert tlog.describe_actual_session([], date(2026, 7, 28)) == "Nothing logged"


def test_describe_actual_session_ignores_other_dates():
    activities = [_activity("07-27", "running", distance_m=8000, duration_s=1800, avg_hr=140)]
    assert tlog.describe_actual_session(activities, date(2026, 7, 28)) == "Nothing logged"


def test_describe_actual_session_multiple_activities_same_day():
    activities = [
        _activity("07-27", "running", distance_m=8000, duration_s=1800, avg_hr=140),
        _activity("07-27", "elliptical", distance_m=5000, duration_s=1200, avg_hr=130),
    ]
    desc = tlog.describe_actual_session(activities, date(2026, 7, 27))
    assert "run" in desc and "cross" in desc
    assert ";" in desc


# --- fill_pending_actuals --------------------------------------------------------------


def test_fill_pending_actuals_backfills_past_pending_rows(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.save_log(
        [tlog.LogRow(date=date(2026, 7, 27), proposed="6 mi easy", actual=tlog.PENDING)], path=path
    )
    activities = [_activity("07-27", "running", distance_m=9824.5, duration_s=3258, avg_hr=153)]
    count = tlog.fill_pending_actuals(activities, up_to=date(2026, 7, 28), path=path)
    assert count == 1
    rows = tlog.load_log(path=path)
    assert rows[0].actual != tlog.PENDING
    assert "run" in rows[0].actual


def test_fill_pending_actuals_does_not_touch_future_rows(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.save_log(
        [tlog.LogRow(date=date(2026, 7, 28), proposed="Elliptical", actual=tlog.PENDING)], path=path
    )
    count = tlog.fill_pending_actuals([], up_to=date(2026, 7, 27), path=path)  # today is after up_to
    assert count == 0
    rows = tlog.load_log(path=path)
    assert rows[0].actual == tlog.PENDING


def test_fill_pending_actuals_skips_already_filled_rows(tmp_path):
    path = tmp_path / "training-log.md"
    tlog.save_log(
        [tlog.LogRow(date=date(2026, 7, 27), proposed="6 mi easy", actual="run 6.1mi 54min HR153")],
        path=path,
    )
    count = tlog.fill_pending_actuals([], up_to=date(2026, 7, 28), path=path)
    assert count == 0


def test_fill_pending_actuals_default_up_to_is_yesterday(tmp_path, monkeypatch):
    import datetime as dt_module

    class FixedDate(dt_module.date):
        @classmethod
        def today(cls):
            return dt_module.date(2026, 7, 28)

    monkeypatch.setattr(tlog, "date", FixedDate)
    path = tmp_path / "training-log.md"
    tlog.save_log(
        [
            tlog.LogRow(date=dt_module.date(2026, 7, 27), proposed="a", actual=tlog.PENDING),
            tlog.LogRow(date=dt_module.date(2026, 7, 28), proposed="b", actual=tlog.PENDING),
        ],
        path=path,
    )
    count = tlog.fill_pending_actuals([], path=path)  # no explicit up_to -> yesterday
    assert count == 1  # only 27-07, not today (28-07)
    rows = {r.date: r for r in tlog.load_log(path=path)}
    assert rows[dt_module.date(2026, 7, 27)].actual != tlog.PENDING
    assert rows[dt_module.date(2026, 7, 28)].actual == tlog.PENDING
