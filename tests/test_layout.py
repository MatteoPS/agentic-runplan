import json

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


# --- 0.5mi quantum on prescriptions (added 14-08-2026) ------------------------
# w/c 10-08 carried days of 5.11 and 3.87mi after eight revisions — hundredths
# that were the arithmetic of forcing a weekly total into its band, not a
# distance anyone could run. See layout.QUANTUM_MI.


def test_quantize_snaps_to_the_nearest_half_mile():
    assert layout.quantize(5.11) == 5.0
    assert layout.quantize(3.87) == 4.0
    assert layout.quantize(4.24) == 4.0
    assert layout.quantize(4.26) == 4.5
    assert layout.quantize(0) == 0.0


def test_prescriptions_are_quantized_on_write():
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:5.11", "29-07:3.87", "02-08:11:long"), "02-08")
    wl = layout.get_layout(WEEK)
    assert wl.day_for("28-07").miles == 5.0
    assert wl.day_for("29-07").miles == 4.0


def test_the_long_run_is_exempt_from_quantization():
    """Its distance is frozen in plan.lock.json under A1/A3, and week 14's is
    the marathon itself — 26.2 must survive intact."""
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:4", "02-08:26.2:long"), "02-08")
    assert layout.get_layout(WEEK).day_for("02-08").miles == 26.2


def test_cross_minutes_are_not_quantized():
    """A cross day's number is minutes, not miles."""
    layout.set_layout(WEEK, days("27-07:40:cross", "28-07:4", "02-08:11:long"), "02-08")
    wl = layout.get_layout(WEEK)
    assert wl.day_for("27-07").cross_minutes == 40.0
    assert wl.total_cross_minutes == 40.0


def test_revise_also_quantizes():
    layout.set_layout(WEEK, days(*FULL_WEEK), "02-08")
    layout.revise(WEEK, days("27-07:0:rest", "28-07:4.13", "02-08:11:long"), "02-08")
    assert layout.get_layout(WEEK).day_for("28-07").miles == 4.0


def test_no_layout_on_disk_can_carry_hundredths():
    """Asserts against the raw JSON, not get_layout — reads are normalized too,
    so going through the accessor would pass this trivially."""
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:5.11", "29-07:3.87", "02-08:9:long"), "02-08")
    stored = json.loads(layout.STATE_PATH.read_text())[WEEK]["days"]
    assert [d["miles"] for d in stored] == [0.0, 5.0, 4.0, 9.0]


def test_hundredths_written_by_an_older_client_are_normalized_on_read():
    """This file is tracked state synced between devices; a phone on an older
    client can still write hundredths. A read must not propagate them."""
    layout.STATE_PATH.write_text(
        json.dumps(
            {
                WEEK: {
                    "long_run_day": "02-08",
                    "revised": 8,
                    "days": [
                        {"day": "28-07", "miles": 5.11, "session": "easy", "cross_minutes": 0.0},
                        {"day": "02-08", "miles": 9.0, "session": "long", "cross_minutes": 0.0},
                    ],
                }
            }
        )
    )
    wl = layout.get_layout(WEEK)
    assert wl.day_for("28-07").miles == 5.0
    assert wl.day_for("02-08").miles == 9.0  # long run still exempt
    assert wl.revised == 8


def test_totals_are_reported_to_one_decimal_place():
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:4.4", "29-07:3.4", "02-08:9:long"), "02-08")
    # 4.5 + 3.5 + 9 — a sum of quantized parts, no float dust
    assert layout.get_layout(WEEK).total_miles == 17.0


def test_a_race_distance_survives_quantization():
    """A 5K is 3.1mi because that is what a 5K is. Snapping it to 3.0 discards
    a fact to satisfy a display convention — the Percy Sutton 5K on 08-08 was
    being silently rewritten before `race` existed."""
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:3.1:race", "02-08:9:long"), "02-08")
    assert layout.get_layout(WEEK).day_for("28-07").miles == 3.1


def test_a_race_counts_as_a_running_day():
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:3.1:race", "02-08:9:long"), "02-08")
    wl = layout.get_layout(WEEK)
    assert wl.run_days == 2
    assert wl.day_for("28-07").is_running


def test_a_pace_run_is_still_quantized():
    """Only the event distance is fixed — a 5.5mi pace run is a prescription
    like any other and must snap."""
    layout.set_layout(WEEK, days("27-07:0:rest", "28-07:5.4:pace", "02-08:9:long"), "02-08")
    assert layout.get_layout(WEEK).day_for("28-07").miles == 5.5
