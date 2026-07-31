from datetime import date

from mc.rules import (
    ITALY_ARRIVAL,
    US_RETURN,
    LongRunResolution,
    ProposedSchedule,
    check_long_run_resolution,
    check_schedule,
)


def _schedule(**overrides):
    defaults = dict(week=1, long_run_date=date(2026, 8, 2))  # a Sunday
    defaults.update(overrides)
    return ProposedSchedule(**defaults)


# --- B2: >=48h between long run and any quality session ------------------------


def test_b2_quality_session_within_48h_rejected(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), quality_session_dates=[date(2026, 8, 1)])
    result = check_schedule(proposed, synthetic_plan)
    assert any(v.rule_id == "B2" for v in result.violations)


def test_b2_quality_session_at_exactly_48h_passes(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), quality_session_dates=[date(2026, 7, 31)])
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B2" for v in result.violations)


# --- B3: consecutive long runs 5-10 days apart / the stacking trap -------------


def test_b3_sunday_to_monday_stacking_trap_rejected():
    """The canonical failure case named in the spec: a long run shuffled from
    Sunday to the very next Monday stacks two long runs 24h apart."""
    from mc.plan import PlanBlock, PlanLock, PlanWeek
    from datetime import datetime

    weeks = [
        PlanWeek(week=1, wc=date(2026, 7, 27), long_run_mi=10, run_miles=22, run_days=4,
                 cross_minutes=40, quality_sessions=0, long_run_ratio_max=0.40, block="build"),
        PlanWeek(week=2, wc=date(2026, 8, 3), long_run_mi=12, run_miles=25, run_days=4,
                 cross_minutes=40, quality_sessions=0, long_run_ratio_max=0.42, block="build"),
    ]
    plan = PlanLock(
        race_date=date(2026, 10, 5), plan="stack test", units="miles",
        locked_at=datetime(2026, 7, 28, 12, 0, 0), weeks=weeks,
        blocks={"build": PlanBlock(weeks=(1, 2), compliance_floor=0.90)},
    )
    # week1's long run stays Sunday 02-08; week2's long run shuffles to
    # Monday 03-08 -- only 1 day after week1's, not the required 5-10.
    proposed = ProposedSchedule(
        week=2, long_run_date=date(2026, 8, 3), prev_long_run_date=date(2026, 8, 2),
    )
    result = check_schedule(proposed, plan)
    assert not result.allowed
    b3 = [v for v in result.violations if v.rule_id == "B3"]
    assert b3, "Sunday->Monday stacking must be rejected outright by B3"


def test_b3_normal_weekly_spacing_passes(synthetic_plan):
    proposed = _schedule(
        long_run_date=date(2026, 8, 2), prev_long_run_date=date(2026, 7, 26),
        next_long_run_date=date(2026, 8, 9),
    )
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B3" for v in result.violations)


def test_b3_too_far_apart_rejected(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), prev_long_run_date=date(2026, 7, 18))
    result = check_schedule(proposed, synthetic_plan)
    assert any(v.rule_id == "B3" for v in result.violations)


# --- B4: crossing into an adjacent week, max once per 4-week block -------------


def test_b4_first_cross_into_adjacent_week_allowed(synthetic_plan):
    # week1's own range is 27-07..02-08; 03-08 is outside it (next week)
    proposed = _schedule(
        week=1, long_run_date=date(2026, 8, 3), prev_long_run_date=date(2026, 7, 27),
    )
    result = check_schedule(proposed, synthetic_plan, crossed_adjacent_week_count_in_block=0)
    assert not any(v.rule_id == "B4" for v in result.violations)


def test_b4_second_cross_in_same_block_rejected(synthetic_plan):
    proposed = _schedule(
        week=1, long_run_date=date(2026, 8, 3), prev_long_run_date=date(2026, 7, 27),
    )
    result = check_schedule(proposed, synthetic_plan, crossed_adjacent_week_count_in_block=1)
    assert any(v.rule_id == "B4" for v in result.violations)


# --- B5: split / swap / reduce escalation ---------------------------------------


def test_b5_split_forbidden_for_protected_week(synthetic_plan):
    resolution = LongRunResolution(
        week=3, resolution="split", split_ratio=(0.6, 0.4), split_gap_hours=4,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_split_allowed_for_unprotected_week(synthetic_plan):
    resolution = LongRunResolution(
        week=1, resolution="split", split_ratio=(0.6, 0.4), split_gap_hours=4,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert result.allowed


def test_b5_split_used_twice_already_rejected(synthetic_plan):
    resolution = LongRunResolution(
        week=1, resolution="split", split_ratio=(0.6, 0.4), split_gap_hours=4,
    )
    result = check_long_run_resolution(resolution, synthetic_plan, splits_used_so_far=2)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_split_wrong_ratio_rejected(synthetic_plan):
    resolution = LongRunResolution(
        week=1, resolution="split", split_ratio=(0.5, 0.5), split_gap_hours=4,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_split_too_far_apart_rejected(synthetic_plan):
    resolution = LongRunResolution(
        week=1, resolution="split", split_ratio=(0.6, 0.4), split_gap_hours=8,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_cross_week_swap_with_shorter_adjacent_week_allowed(synthetic_plan):
    """Week 2 (6mi, stepback) swaps its slot with week 1 (8mi) -- wait, must
    swap with a SHORTER run: week 1 swapping with week 2's shorter 6mi long
    run is the valid direction."""
    resolution = LongRunResolution(
        week=1, resolution="swap", swap_week=2, swap_week_long_run_mi=6,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert result.allowed


def test_b5_swap_carrying_longer_run_forward_rejected(synthetic_plan):
    """Week 2 (6mi) may not swap in week 3's longer 18mi run -- never carry
    the longer one forward into what would become a peak week."""
    resolution = LongRunResolution(
        week=2, resolution="swap", swap_week=3, swap_week_long_run_mi=18,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_swap_with_nonadjacent_week_rejected(synthetic_plan):
    resolution = LongRunResolution(
        week=1, resolution="swap", swap_week=4, swap_week_long_run_mi=5,
    )
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_reduce_forbidden_for_protected_week(synthetic_plan):
    resolution = LongRunResolution(week=8, resolution="reduce", reduce_pct=10, reason_code="TRAVEL")
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_reduce_over_25_pct_rejected(synthetic_plan):
    resolution = LongRunResolution(week=1, resolution="reduce", reduce_pct=30, reason_code="TRAVEL")
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_reduce_without_reason_code_rejected(synthetic_plan):
    resolution = LongRunResolution(week=1, resolution="reduce", reduce_pct=15, reason_code=None)
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert any(v.rule_id == "B5" for v in result.violations)


def test_b5_reduce_valid_passes(synthetic_plan):
    resolution = LongRunResolution(week=1, resolution="reduce", reduce_pct=15, reason_code="TRAVEL")
    result = check_long_run_resolution(resolution, synthetic_plan)
    assert result.allowed


# --- B6: no long run within 24h of a flight over 4h -----------------------------


def test_b6_long_run_day_of_long_flight_rejected(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), flight_dates=[(date(2026, 8, 2), 8.0)])
    result = check_schedule(proposed, synthetic_plan)
    assert any(v.rule_id == "B6" for v in result.violations)


def test_b6_short_flight_under_4h_exempt(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), flight_dates=[(date(2026, 8, 2), 2.0)])
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B6" for v in result.violations)


def test_b6_flight_well_before_long_run_passes(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), flight_dates=[(date(2026, 7, 20), 8.0)])
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B6" for v in result.violations)


# --- B7: first 3 days after Italy arrival / US return, easy only ---------------
# Uses the real plan since ITALY_ARRIVAL/US_RETURN are the real trip dates.


def test_b7_long_run_on_arrival_day_rejected(real_plan):
    week = real_plan.week_for_date(ITALY_ARRIVAL)
    proposed = ProposedSchedule(week=week.week, long_run_date=ITALY_ARRIVAL)
    result = check_schedule(proposed, real_plan)
    assert any(v.rule_id == "B7" for v in result.violations)


def test_b7_long_run_two_days_after_arrival_rejected(real_plan):
    d = ITALY_ARRIVAL + __import__("datetime").timedelta(days=2)
    week = real_plan.week_for_date(d)
    proposed = ProposedSchedule(week=week.week, long_run_date=d)
    result = check_schedule(proposed, real_plan)
    assert any(v.rule_id == "B7" for v in result.violations)


def test_b7_long_run_four_days_after_arrival_passes(real_plan):
    d = ITALY_ARRIVAL + __import__("datetime").timedelta(days=4)
    week = real_plan.week_for_date(d)
    proposed = ProposedSchedule(week=week.week, long_run_date=d)
    result = check_schedule(proposed, real_plan)
    assert not any(v.rule_id == "B7" for v in result.violations)


def test_b7_quality_session_on_return_day_rejected(real_plan):
    week = real_plan.week_for_date(US_RETURN)
    proposed = ProposedSchedule(
        week=week.week, long_run_date=US_RETURN + __import__("datetime").timedelta(days=10),
        quality_session_dates=[US_RETURN],
    )
    result = check_schedule(proposed, real_plan)
    assert any(v.rule_id == "B7" for v in result.violations)


def test_full_italy_block_realistic_scenario_flags_correctly(real_plan):
    """A realistic Italy-week proposal: opportunistic long run 5 days after
    arrival (fine), nothing scheduled in the easy-only window."""
    week8 = real_plan.week_by_number(8)
    long_run_date = ITALY_ARRIVAL + __import__("datetime").timedelta(days=5)
    proposed = ProposedSchedule(week=week8.week, long_run_date=long_run_date)
    result = check_schedule(proposed, real_plan)
    assert not any(v.rule_id == "B7" for v in result.violations)


# --- B8: max 5 consecutive running days, at most once per 4-week block ---------


def _consecutive_days(start: date, n: int) -> list[date]:
    return [start + __import__("datetime").timedelta(days=i) for i in range(n)]


def test_b8_six_consecutive_days_rejected(synthetic_plan):
    proposed = _schedule(running_days=_consecutive_days(date(2026, 7, 27), 6))
    result = check_schedule(proposed, synthetic_plan)
    assert any(v.rule_id == "B8" for v in result.violations)


def test_b8_five_consecutive_days_first_time_passes(synthetic_plan):
    proposed = _schedule(running_days=_consecutive_days(date(2026, 7, 27), 5))
    result = check_schedule(proposed, synthetic_plan, five_day_streaks_in_block=0)
    assert not any(v.rule_id == "B8" for v in result.violations)


def test_b8_five_consecutive_days_second_time_in_block_rejected(synthetic_plan):
    proposed = _schedule(running_days=_consecutive_days(date(2026, 7, 27), 5))
    result = check_schedule(proposed, synthetic_plan, five_day_streaks_in_block=1)
    assert any(v.rule_id == "B8" for v in result.violations)


def test_b8_four_consecutive_days_always_fine(synthetic_plan):
    proposed = _schedule(running_days=_consecutive_days(date(2026, 7, 27), 4))
    result = check_schedule(proposed, synthetic_plan, five_day_streaks_in_block=1)
    assert not any(v.rule_id == "B8" for v in result.violations)


# --- B9: Saturday-pace / Sunday-long pairing ------------------------------------


def test_b9_pairing_preserved_passes(synthetic_plan):
    proposed = _schedule(
        long_run_date=date(2026, 8, 2), quality_session_dates=[date(2026, 8, 1)],
    )
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B9" for v in result.violations)


def test_b9_pairing_broken_without_reason_rejected(synthetic_plan):
    proposed = _schedule(long_run_date=date(2026, 8, 2), quality_session_dates=[])
    result = check_schedule(proposed, synthetic_plan)
    assert any(v.rule_id == "B9" for v in result.violations)


def test_b9_pairing_broken_with_stated_reason_passes(synthetic_plan):
    proposed = _schedule(
        long_run_date=date(2026, 8, 2), quality_session_dates=[],
        pairing_broken_reason="moved for travel, see notes",
    )
    result = check_schedule(proposed, synthetic_plan)
    assert not any(v.rule_id == "B9" for v in result.violations)
