from datetime import date, timedelta

import pytest

from mc import layout
from mc import planning
from mc import strength


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(layout, "STATE_PATH", tmp_path / "week_layout.json")
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")


def set_week_1_layout():
    """synthetic_plan's week 1 is w/c 27-07: 8mi long, 20mi, 4 run days."""
    days, long_day = layout.parse_day_spec(
        "27-07:45:cross,28-07:4,29-07:4,30-07:0:rest,31-07:4,01-08:0:rest,02-08:8:long"
    )
    return layout.set_layout("27-07", days, long_day)


# --- basis: the property this module exists to enforce ------------------------------


def test_first_day_is_actual_and_the_rest_projected(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=3)
    assert [d.basis for d in look.days] == [
        planning.Basis.ACTUAL,
        planning.Basis.PROJECTED,
        planning.Basis.PROJECTED,
    ]
    assert not look.days[0].is_provisional
    assert all(d.is_provisional for d in look.days[1:])
    assert len(look.provisional_days) == 2


def test_single_day_lookahead_has_no_projections(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=1)
    assert look.provisional_days == []


def test_rejects_zero_days(synthetic_plan):
    with pytest.raises(ValueError):
        planning.lookahead(synthetic_plan, date(2026, 7, 28), days=0)


def test_assumptions_are_stated_not_implied():
    text = planning.format_assumptions()
    for assumption in planning.PROJECTION_ASSUMPTIONS:
        assert assumption in text


# --- reading the layout -------------------------------------------------------------


def test_days_come_from_the_persisted_layout(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=3)
    assert [(d.ddmm, d.miles, d.session) for d in look.days] == [
        ("28-07", 4.0, "easy"),
        ("29-07", 4.0, "easy"),
        ("30-07", 0.0, "rest"),
    ]


def test_long_run_is_flagged(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 8, 1), days=2)
    assert [d.is_long_run for d in look.days] == [False, True]
    assert look.days[1].miles == 8


def test_fixed_strength_days_are_flagged(synthetic_plan):
    wl = set_week_1_layout()
    fixed = strength.set_fixed_days("27-07", layout.day_miles(wl), "02-08")
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=5)
    flagged = {d.ddmm for d in look.days if d.is_fixed_strength}
    assert flagged == set(fixed) & {d.ddmm for d in look.days}
    assert flagged  # the fixture must actually exercise this


# --- no layout: say so, don't invent one -------------------------------------------


def test_missing_layout_is_reported_not_guessed(synthetic_plan):
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=3)
    assert look.missing_layout_weeks == ["27-07"]
    assert all(not d.layout_known for d in look.days)


def test_missing_layout_falls_back_to_weekly_average(synthetic_plan):
    """20mi over 4 run days -> 5mi/day. A stated average, never presented as
    a real day-of-week placement."""
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=1)
    assert look.days[0].miles == 5.0
    assert look.days[0].layout_known is False


def test_no_week_check_without_a_layout(synthetic_plan):
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=3)
    assert look.week_check is None


def test_week_check_runs_against_the_layout(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 7, 28), days=3)
    assert look.week_check is not None
    assert look.week_check.allowed  # 20mi / 8mi long is exactly week 1's plan


# --- boundaries ---------------------------------------------------------------------


def test_lookahead_spanning_two_weeks_reports_both(synthetic_plan):
    set_week_1_layout()
    look = planning.lookahead(synthetic_plan, date(2026, 8, 1), days=4)
    assert {d.week_num for d in look.days} == {1, 2}
    assert {d.week_start for d in look.days} == {"27-07", "03-08"}
    # only the second week lacks a layout
    assert look.missing_layout_weeks == ["03-08"]


def test_running_past_the_end_of_the_plan_stops_rather_than_extrapolating(synthetic_plan):
    """Nothing follows the last taper week, so the lookahead ends there rather
    than inventing days past race day."""
    last = max(w.wc for w in synthetic_plan.weeks)
    look = planning.lookahead(synthetic_plan, last, days=14)
    assert len(look.days) == 7  # the final week only
    assert max(d.date for d in look.days) == last + timedelta(days=6)
