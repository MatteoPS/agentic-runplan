from mc.rules import ProposedWeek, check_race_date, check_week, week_band
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


# --- half-mile tolerance on the week-sum rules (added 14-08-2026) --------------
# A distance is not a precise quantity: an outdoor route is eyeballed to avoid
# a long walk home. A2/A4/A5/A6/A9 are judged to the nearest half mile so that
# a week 0.05mi off the line stops producing warnings that are arithmetic
# rather than findings. See rules._WEEK_TOLERANCE_MI.


def test_a2_just_under_floor_is_tolerated(synthetic_plan):
    # build floor 0.90 * 20mi = 18mi; 17.6 is inside the 0.5mi tolerance.
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=17.6, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A2" for v in result.violations)


def test_a2_beyond_tolerance_still_fires(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=17.4, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A2" for v in result.violations)


def test_a2_tolerance_cannot_hide_a_skipped_session(synthetic_plan):
    """The whole safety argument for the tolerance: the shortest run anywhere
    in the real plan is 3mi, six times the tolerance, so a missed session can
    never be absorbed by it."""
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=15, run_days=3, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A2" for v in result.violations)


def test_a6_just_over_ceiling_is_tolerated(synthetic_plan):
    # 105% of 20mi = 21.0mi
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=21.4, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A6" for v in result.violations)


def test_a6_beyond_tolerance_still_fires(synthetic_plan):
    proposed = ProposedWeek(week=1, long_run_mi=8, run_miles=21.6, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A6" for v in result.violations)


def test_a4_taper_tolerates_a_slightly_long_route(synthetic_plan):
    """Confirmed 14-08-2026: the tolerance applies in the taper too, where
    compliance_floor is 1.0 and A2's floor IS the plan value."""
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=28.4, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A4" for v in result.violations)


def test_a4_taper_still_blocks_real_additions(synthetic_plan):
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=31, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A4" for v in result.violations)


def test_a4_taper_week_is_satisfiable_at_exactly_plan(synthetic_plan):
    """A2's floor and A4's ceiling coincide in the taper, so the strict band
    is a single point. Both must pass at the plan value or the taper is
    unsatisfiable by construction."""
    proposed = ProposedWeek(week=9, long_run_mi=12, run_miles=28, run_days=4, cross_minutes=0)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id in ("A2", "A4") for v in result.violations)


def test_a5_stepback_tolerates_a_slightly_long_route(synthetic_plan):
    proposed = ProposedWeek(week=2, long_run_mi=6, run_miles=16.4, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert not any(v.rule_id == "A5" for v in result.violations)


def test_a5_stepback_still_blocks_a_real_top_up(synthetic_plan):
    proposed = ProposedWeek(week=2, long_run_mi=6, run_miles=19, run_days=4, cross_minutes=45)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A5" for v in result.violations)


def test_a9_tolerance_is_applied_in_miles_not_ratio(synthetic_plan):
    """A9's cap is a ratio but the tolerance is a statement about distance, so
    it is converted: allowance = ratio_max * total, +0.5mi."""
    # week 1, ratio_max 0.35, total 20mi (no cross) => allowance 7.0mi
    ok = ProposedWeek(week=1, long_run_mi=7.4, run_miles=20, run_days=4, cross_minutes=0)
    assert not any(v.rule_id == "A9" for v in check_week(ok, synthetic_plan).violations)

    over = ProposedWeek(week=1, long_run_mi=7.6, run_miles=20, run_days=4, cross_minutes=0)
    assert any(v.rule_id == "A9" for v in check_week(over, synthetic_plan).violations)


def test_a1_a3_keep_their_own_tighter_tolerance(synthetic_plan):
    """The week-sum tolerance is deliberately NOT extended to the rules that
    judge a single locked event — A3 protects the 18 and the 20."""
    proposed = ProposedWeek(week=3, long_run_mi=17.6, run_miles=40, run_days=5, cross_minutes=125)
    result = check_week(proposed, synthetic_plan)
    assert any(v.rule_id == "A3" for v in result.violations)


# --- WeekBand: the legal range, printed so layouts stop hugging the edge -------


def test_week_band_ceiling_is_a6_on_an_ordinary_week(synthetic_plan):
    band = week_band(synthetic_plan.week_by_number(1), synthetic_plan)
    assert (band.floor_mi, band.ceiling_mi, band.ceiling_rule) == (18.0, 21.0, "A6")
    assert not band.is_degenerate


def test_week_band_ceiling_is_a5_on_a_stepback_week(synthetic_plan):
    """A6's 105% is not the binding ceiling on a stepback — A5 caps at the
    plan value itself, which is tighter and was not being printed anywhere."""
    band = week_band(synthetic_plan.week_by_number(2), synthetic_plan)
    assert (band.ceiling_mi, band.ceiling_rule) == (16.0, "A5")


def test_week_band_ceiling_is_a4_in_the_taper(synthetic_plan):
    band = week_band(synthetic_plan.week_by_number(9), synthetic_plan)
    assert (band.floor_mi, band.ceiling_mi, band.ceiling_rule) == (28.0, 28.0, "A4")


def test_taper_band_is_degenerate_and_says_so(synthetic_plan):
    band = week_band(synthetic_plan.week_by_number(9), synthetic_plan)
    assert band.is_degenerate
    assert band.width_mi == 0.0
    assert "tolerance" in band.note


def test_ordinary_week_carries_no_degenerate_note(synthetic_plan):
    assert week_band(synthetic_plan.week_by_number(1), synthetic_plan).note == ""


def test_week_band_headroom_reports_both_directions(synthetic_plan):
    band = week_band(synthetic_plan.week_by_number(1), synthetic_plan)
    assert band.headroom(20.0) == (2.0, 1.0)
    assert band.midpoint_mi == 19.5


def test_week_band_describe_names_the_binding_rule(synthetic_plan):
    text = week_band(synthetic_plan.week_by_number(2), synthetic_plan).describe(16.0)
    assert "A5 ceiling" in text and "A2 floor" in text
