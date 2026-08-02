import pytest

from mc import layout
from mc import strength


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(layout, "STATE_PATH", tmp_path / "week_layout.json")
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")


def days(*specs: str) -> list[layout.DayPlan]:
    parsed, _ = layout.parse_day_spec(",".join(specs))
    return parsed


WEEK = "27-07"
FULL_WEEK = ("27-07:0:rest", "28-07:4", "29-07:5", "30-07:45:cross", "31-07:4", "01-08:3", "02-08:11:long")


# --- round trip --------------------------------------------------------------------


def test_set_and_get_round_trip():
    layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    wl = layout.get_layout(WEEK)
    assert wl.long_run_day == "02-08"
    assert wl.total_miles == 27.0
    assert wl.run_days == 5
    assert wl.day_for("29-07").miles == 5


def test_get_returns_none_when_unset():
    assert layout.get_layout("01-01") is None
    assert layout.day_for("01-01", "01-01") is None


def test_days_are_stored_in_date_order():
    layout.set_layout(WEEK, days("02-08:11:long", "28-07:4", "27-07:0:rest"), "02-08")
    assert [d.day for d in layout.get_layout(WEEK).days] == ["27-07", "28-07", "02-08"]


# --- set vs revise -----------------------------------------------------------------


def test_set_layout_is_first_write_wins():
    layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    unchanged = layout.set_layout(WEEK, days("27-07:99:easy", "02-08:11:long"), "02-08")
    assert unchanged.total_miles == 27.0


def test_revise_overwrites_and_counts():
    layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    revised = layout.revise(WEEK, days("28-07:6", "02-08:11:long"), "02-08")
    assert revised.total_miles == 17.0
    assert revised.revised == 1
    assert layout.revise(WEEK, days("28-07:6", "02-08:11:long"), "02-08").revised == 2


def test_revise_does_not_disturb_fixed_strength_days():
    """The whole point of the split: C1 may reshuffle easy runs freely, but
    strength.set_fixed_days is first-write-wins so 'unskippable' keeps meaning
    something. A revision must not silently re-pick them."""
    wl = layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    fixed_before = strength.set_fixed_days(WEEK, layout.day_miles(wl), "02-08")

    # reshuffle so the *shortest* days are now different ones entirely
    layout.revise(WEEK, days("28-07:9", "29-07:1", "31-07:1", "02-08:11:long"), "02-08")

    assert strength.get_fixed_days(WEEK) == fixed_before


# --- validation --------------------------------------------------------------------


def test_rejects_unknown_session_type():
    with pytest.raises(layout.LayoutError, match="Unknown session type"):
        layout.set_layout(WEEK, days("28-07:4:sprint", "02-08:11:long"), "02-08")


def test_rejects_duplicate_days():
    with pytest.raises(layout.LayoutError, match="Duplicate"):
        layout.set_layout(WEEK, days("28-07:4", "28-07:5", "02-08:11:long"), "02-08")


def test_rejects_long_run_day_not_in_layout():
    with pytest.raises(layout.LayoutError, match="not one of"):
        layout.set_layout(WEEK, days("28-07:4", "02-08:11:long"), "03-08")


def test_rejects_long_run_day_disagreeing_with_long_session():
    with pytest.raises(layout.LayoutError, match="session=long"):
        layout.set_layout(WEEK, days("28-07:4", "02-08:11:long"), "28-07")


def test_rejects_layout_with_no_long_session():
    with pytest.raises(layout.LayoutError, match="session=long"):
        layout.set_layout(WEEK, days("28-07:4", "02-08:11"), "02-08")


# --- spec parsing ------------------------------------------------------------------


def test_parse_infers_session_type_from_mileage():
    parsed, long_day = layout.parse_day_spec("28-07:4,29-07:0")
    assert [d.session for d in parsed] == ["easy", "rest"]
    assert long_day is None


def test_parse_infers_long_day():
    _, long_day = layout.parse_day_spec("28-07:4,02-08:11:long")
    assert long_day == "02-08"


def test_parse_rejects_two_long_days():
    with pytest.raises(layout.LayoutError, match="Two days marked long"):
        layout.parse_day_spec("01-08:11:long,02-08:11:long")


@pytest.mark.parametrize("spec", ["28-07", "28-07:4:easy:extra", "28-07:notanumber", ""])
def test_parse_rejects_malformed_specs(spec):
    with pytest.raises(layout.LayoutError):
        layout.parse_day_spec(spec)


# --- interop -----------------------------------------------------------------------


def test_day_miles_matches_strength_input_shape():
    wl = layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    dm = layout.day_miles(wl)
    assert dm == {"27-07": 0.0, "28-07": 4.0, "29-07": 5.0, "30-07": 0.0, "31-07": 4.0, "01-08": 3.0, "02-08": 11.0}
    assert wl.total_cross_minutes == 45  # the cross day's number is minutes, not miles
    # feeding it straight to strength must work — that's the point
    assert len(strength.set_fixed_days(WEEK, dm, "02-08")) == 2


def test_as_proposed_week_counts_running_only(synthetic_plan):
    wl = layout.set_layout(WEEK, days("28-07:4", "29-07:45:cross", "02-08:11:long"), "02-08")
    proposed = layout.as_proposed_week(wl, week_num=1)
    assert proposed.long_run_mi == 11
    assert proposed.run_miles == 15  # the cross day contributes no miles
    assert proposed.run_days == 2
    assert proposed.cross_minutes == 45  # taken from the layout's own cross day


def test_week_start_for_returns_monday():
    from datetime import date

    assert layout.week_start_for(date(2026, 8, 2)) == "27-07"  # a Sunday
    assert layout.week_start_for(date(2026, 7, 27)) == "27-07"  # the Monday itself
