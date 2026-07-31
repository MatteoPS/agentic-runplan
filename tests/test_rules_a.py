from mc.rules import ProposedWeek, check_race_date, check_week
from datetime import date


def test_happy_path_exact_plan_passes(synthetic_plan):
    w = synthetic_plan.week_by_number(1)
    proposed = ProposedWeek(
        week=1, long_run_mi=w.long_run_mi, run_miles=w.run_miles,
        run_days=w.run_days, cross_minutes=w.cross_minutes,
    )
    result = check_week(proposed, synthetic_plan)
    assert result.allowed
    assert result.violations == []


# --- A1: long run must not shrink (except travel_italy) ------------------------


def test_a1_long_run_shrink_rejected(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=5, run_miles=20, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not result.allowed
    assert any(v.rule_id == "A1" for v in result.violations)


def test_a1_long_run_shrink_allowed_in_travel_italy(synthetic_plan):
    proposed = ProposedWeek(week=5, long_run_mi=6, run_miles=14, run_days=3, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A1" for v in result.violations)


def test_a1_tiny_gps_variance_tolerated(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=7.9, run_miles=20, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A1" for v in result.violations)


# --- A2: weekly total >= block compliance floor --------------------------------


def test_a2_below_floor_rejected(synthetic_plan):
    # build floor 0.90 * 20mi = 18mi
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=17, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A2" for v in result.violations)


def test_a2_at_exact_floor_passes(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=18, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A2" for v in result.violations)


# --- A3: protected milestone long runs (18mi+/is_twenty) never shortened -------


def test_a3_protects_18mi_week(synthetic_plan):
    proposed = ProposedWeek(week=3, long_run_mi=16, run_miles=40, run_days=5, cross_minutes=125)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A3" for v in result.violations)


def test_a3_protects_twenty_week(synthetic_plan):
    proposed = ProposedWeek(week=8, long_run_mi=18, run_miles=45, run_days=5, cross_minutes=70)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A3" for v in result.violations)


def test_a3_unprotected_week_can_shrink_within_a1_tolerance(synthetic_plan):
    # week 1 (8mi) isn't protected -- only A1's 0.2mi tolerance applies
    proposed = ProposedWeek(week=1, long_run_mi=7.9, run_miles=20, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A3" for v in result.violations)


# --- A4: taper is frozen, zero tolerance for additions --------------------------


def test_a4_taper_addition_rejected(synthetic_plan):
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=30, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A4" for v in result.violations)


def test_a4_taper_exact_passes(synthetic_plan):
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=28, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A4" for v in result.violations)


def test_a4_taper_undershoot_is_not_an_a4_violation_but_is_a2(synthetic_plan):
    # A4 is about additions; running less is caught by A2 (floor 1.00 for taper)
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=25, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A4" for v in result.violations)
    assert any(v.rule_id == "A2" for v in result.violations)


# --- A5: stepback weeks never topped up -----------------------------------------


def test_a5_stepback_topped_up_rejected(synthetic_plan):
    proposed = ProposedWeek(week=2, long_run_mi=6, run_miles=20, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A5" for v in result.violations)


def test_a5_stepback_at_plan_passes(synthetic_plan):
    proposed = ProposedWeek(week=2, long_run_mi=6, run_miles=16, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A5" for v in result.violations)


# --- A6: no increases beyond 105% of plan ---------------------------------------


def test_a6_over_105_pct_rejected_even_if_feeling_great(synthetic_plan):
    # 20mi * 1.05 = 21mi ceiling
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=22, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A6" for v in result.violations)


def test_a6_at_exactly_105_pct_passes(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=21, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A6" for v in result.violations)


# --- A7: race date fixed --------------------------------------------------------


def test_a7_race_date_change_rejected(synthetic_plan):
    result = check_race_date(date(2026, 10, 12), synthetic_plan)
    assert not result.allowed
    assert result.violations[0].rule_id == "A7"


def test_a7_race_date_unchanged_passes(synthetic_plan):
    result = check_race_date(synthetic_plan.race_date, synthetic_plan)
    assert result.allowed


# --- A8: non-running load <= 35%, outside travel --------------------------------


def test_a8_excess_cross_training_rejected(synthetic_plan):
    # push huge cross minutes to blow past 35% nonrun share
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=20, run_days=4, cross_minutes=400)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A8" for v in result.violations)


def test_a8_exempt_inside_travel_italy(synthetic_plan):
    # travel_italy has no_gym=True -- A8 doesn't apply there regardless
    proposed = ProposedWeek(week=5, long_run_mi=12, run_miles=18, run_days=3, cross_minutes=400)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A8" for v in result.violations)


# --- A9: long run <= per-week ratio cap -----------------------------------------


def test_a9_ratio_breach_rejected(synthetic_plan):
    # cutting midweek miles down inflates the long-run ratio past the cap
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=10, run_days=2, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A9" for v in result.violations)


def test_a9_within_cap_passes(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=20, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A9" for v in result.violations)


def test_a9_uses_per_week_ratio_cap_not_global_default(synthetic_plan):
    # week 5 (travel_italy) has ratio_max=0.70, well above the spec's 0.32 default
    proposed = ProposedWeek(week=5, long_run_mi=12, run_miles=18, run_days=3, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A9" for v in result.violations)


# --- A10: minimum 3 running days/week, outside travel and taper ----------------


def test_a10_below_minimum_rejected(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=20, run_days=2, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A10" for v in result.violations)


def test_a10_exempt_in_travel_italy(synthetic_plan):
    proposed = ProposedWeek(week=5, long_run_mi=12, run_miles=18, run_days=1, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A10" for v in result.violations)


def test_a10_exempt_in_taper(synthetic_plan):
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=28, run_days=2, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A10" for v in result.violations)


# --- multiple simultaneous violations ------------------------------------------


def test_multiple_violations_all_reported(synthetic_plan):
    proposed = ProposedWeek(week=2, long_run_mi=2, run_miles=25, run_days=1, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    ids = {v.rule_id for v in result.violations}
    assert not result.allowed
    assert "A1" in ids  # shrunk below plan (stepback week, not travel_italy)
    assert "A5" in ids  # stepback topped up
    assert "A6" in ids  # over 105%
    assert "A10" in ids  # too few run days
