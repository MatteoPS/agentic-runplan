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


# --- the blended week: actuals for elapsed days, layout for the rest ----------------
# The regression these guard: §6's A-rules are whole-week metrics, so judging
# actuals-so-far against them made every mid-week `mc check` report violations
# that were arithmetic rather than findings.


def day_actuals(**by_day: tuple[float, bool]) -> dict:
    """{"28-07": (4.0, True)} -> {"28-07": DayActuals(run_miles=4.0, ...)}"""
    from mc.digest import DayActuals

    return {
        d: DayActuals(run_miles=mi, longest_run_mi=mi, ran=ran)
        for d, (mi, ran) in by_day.items()
    }


def test_full_compliance_midweek_projects_the_whole_planned_week(synthetic_plan):
    """Everything through Wednesday done as planned: the projection is the
    full 20mi week, so A2's 95% floor passes. This is the false warning that
    started it. Note the Monday cross session has to be there — week 1's plan
    leans on it to stay under A9's long-run ratio cap."""
    from mc.digest import DayActuals

    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    actuals = day_actuals(**{"28-07": (4.0, True), "29-07": (4.0, True)})
    actuals["27-07"] = DayActuals(cross_minutes=45.0)
    proj = planning.project_week(week, wl, actuals, date(2026, 7, 30))
    assert proj.banked_miles == 8.0
    assert proj.remaining_miles == 12.0  # 31-07 easy 4 + 02-08 long 8
    assert proj.proposed.run_miles == 20.0
    assert proj.proposed.long_run_mi == 8.0  # from the layout — its day is still ahead
    assert proj.proposed.run_days == 4
    from mc import rules

    assert rules.check_week(proj.proposed, synthetic_plan).allowed


def test_a_skipped_elapsed_day_is_a_real_shortfall(synthetic_plan):
    """The point of the blend: it silences arithmetic, not findings. Tuesday
    missed entirely and the week no longer reaches its floor."""
    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    proj = planning.project_week(week, wl, day_actuals(), date(2026, 7, 30))
    assert proj.banked_miles == 0.0  # 28-07 and 29-07 both passed unrun
    assert proj.proposed.run_miles == 12.0
    from mc import rules

    result = rules.check_week(proj.proposed, synthetic_plan)
    assert not result.allowed
    assert "A2" in {v.rule_id for v in result.violations}


def test_long_run_day_passed_unrun_stops_counting_toward_a1(synthetic_plan):
    """Once the long-run day is behind you and it didn't happen, the shortfall
    is the finding — the layout's figure must not paper over it."""
    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    actuals = day_actuals(**{"28-07": (4.0, True), "29-07": (4.0, True), "31-07": (4.0, True)})
    proj = planning.project_week(week, wl, actuals, date(2026, 8, 3))
    assert proj.proposed.long_run_mi == 4.0  # longest actual, not the planned 8
    from mc import rules

    assert "A1" in {v.rule_id for v in rules.check_week(proj.proposed, synthetic_plan).violations}


def test_actuals_beat_the_layout_on_a_day_already_run(synthetic_plan):
    """/preview runs in the evening, after the session. A day run longer than
    planned counts what was run."""
    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    actuals = day_actuals(**{"31-07": (6.0, True)})  # planned 4, ran 6
    proj = planning.project_week(week, wl, actuals, date(2026, 7, 31))
    assert "31-07" in proj.elapsed_days
    assert "31-07" not in proj.remaining_days
    assert proj.banked_miles == 6.0


def test_rest_days_are_not_counted_as_missed(synthetic_plan):
    """A planned rest day contributes 0 whether it is past or future — an
    absent actual on a rest day is compliance, not a gap."""
    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    proj = planning.project_week(week, wl, day_actuals(), date(2026, 8, 3))
    assert proj.proposed.run_miles == 0.0
    assert proj.proposed.run_days == 0


def test_cross_minutes_blend_from_both_sides(synthetic_plan):
    """Week 1's layout opens with a 45-minute cross day; it counts from the
    layout while ahead, and from actuals once it has happened."""
    wl = set_week_1_layout()
    week = synthetic_plan.week_by_number(1)
    ahead = planning.project_week(week, wl, day_actuals(), date(2026, 7, 27))
    assert ahead.proposed.cross_minutes == 45.0

    from mc.digest import DayActuals

    done = planning.project_week(
        week, wl, {"27-07": DayActuals(cross_minutes=30.0)}, date(2026, 7, 28)
    )
    assert done.proposed.cross_minutes == 30.0
