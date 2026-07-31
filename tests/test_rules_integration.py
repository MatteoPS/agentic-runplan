"""Integration sanity checks: the real frozen plan.lock.json must pass its
own rule engine, week by week, with zero violations when proposed exactly
as locked. If this ever fails, either the plan or the rule engine has drifted
from the other."""

from mc.rules import ProposedWeek, check_week


def test_every_real_week_passes_check_week_at_exact_plan_values(real_plan):
    failures = []
    for week in real_plan.weeks:
        proposed = ProposedWeek(
            week=week.week,
            long_run_mi=week.long_run_mi,
            run_miles=week.run_miles,
            run_days=week.run_days,
            cross_minutes=week.cross_minutes,
        )
        result = check_week(proposed, real_plan)
        if not result.allowed:
            failures.append((week.week, [v.model_dump() for v in result.violations]))
    assert not failures, f"Real plan weeks fail their own rule engine: {failures}"


def test_real_plan_race_date_matches_a7(real_plan):
    from mc.rules import check_race_date

    result = check_race_date(real_plan.race_date, real_plan)
    assert result.allowed
