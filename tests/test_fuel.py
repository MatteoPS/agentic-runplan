from mc import fuel


def test_short_runs_get_no_plan():
    """A run that finishes inside 75 min doesn't need in-run carbohydrate, and a
    prompt that fires on every easy day stops being read."""
    assert fuel.build_plan(5.0, week_num=5) is None
    assert not fuel.needs_fuelling(5.0)
    assert fuel.plan_lines(None) == []


def test_long_runs_get_a_plan():
    assert fuel.needs_fuelling(16.0)
    plan = fuel.build_plan(16.0, week_num=5)
    assert plan is not None
    assert plan.target_g_per_hr == 60


def test_target_ramps_rather_than_jumping_to_race_rate():
    """The gut is the thing being trained; 43 g/hr -> race rate overnight buys
    GI distress instead of adaptation."""
    early = fuel.target_for_week(1)
    mid = fuel.target_for_week(6)
    rehearsal = fuel.target_for_week(11)
    assert early < mid < rehearsal
    assert rehearsal == fuel.RACE_TARGET_G_PER_HR


def test_italy_block_holds_rather_than_climbing():
    """Weeks 8-9 are opportunistic and travel is the wrong place for a new GI
    stressor -- same reasoning as B7's easy days after each flight."""
    assert fuel.target_for_week(8) == fuel.target_for_week(7)
    assert fuel.target_for_week(9) == fuel.target_for_week(7)
    assert fuel.target_for_week(10) > fuel.target_for_week(9)


def test_week_11_is_flagged_as_the_dress_rehearsal():
    """A4 freezes the taper, so the 20 is the last run that can test race day."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.is_dress_rehearsal
    assert "dress rehearsal" in " ".join(fuel.plan_lines(plan))
    assert not fuel.build_plan(18.0, week_num=6).is_dress_rehearsal


def test_gel_arithmetic_is_internally_consistent():
    """The stated total and the schedule beneath it must agree, or the digest
    prints a number the plan doesn't deliver."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.grams_from_gels == round(plan.n_gels * fuel.GRAMS_PER_GEL)
    assert plan.grams_from_gels + plan.grams_from_drink == plan.total_grams


def test_first_gel_is_not_at_the_gun():
    """The opening half hour runs on breakfast; the count reflects that."""
    plan = fuel.build_plan(20.0, week_num=11)
    naive = int(plan.duration_min // plan.gel_every_min) + 1
    assert plan.n_gels < naive


def test_transporter_note_only_above_60():
    below = fuel.build_plan(16.0, week_num=1)  # 50 g/hr
    above = fuel.build_plan(16.0, week_num=11)  # 80 g/hr
    assert not any("transporter" in line for line in fuel.plan_lines(below))
    assert any("transporter" in line for line in fuel.plan_lines(above))


def test_higher_target_means_more_frequent_gels():
    early = fuel.build_plan(16.0, week_num=1)
    late = fuel.build_plan(16.0, week_num=11)
    assert late.gel_every_min < early.gel_every_min
    assert late.total_grams > early.total_grams


def test_intervals_are_round_numbers_a_runner_can_follow():
    for week in fuel.FUEL_RAMP_G_PER_HR:
        plan = fuel.build_plan(16.0, week_num=week)
        assert plan.gel_every_min % 5 == 0


def test_hydration_and_carbohydrate_are_reported_as_separate_jobs():
    """An electrolyte tab is ~11 g carb: an hour's sodium, half a gel of fuel.
    Conflating the two is how 27 g/hr gets mistaken for enough."""
    lines = " ".join(fuel.plan_lines(fuel.build_plan(16.0, week_num=5)))
    assert "Fluid & sodium" in lines
    assert "hydration, not fuel" in lines
    assert str(fuel.ELECTROLYTE_TAB_SODIUM_MG) in lines


def test_gels_and_drink_have_different_timing():
    """A gel is a bolus and waits; drink carbs are sipped from the start."""
    lines = " ".join(fuel.plan_lines(fuel.build_plan(20.0, week_num=11)))
    assert "first at 35 min" in lines
    assert "continuously from the start" in lines


def test_carry_assumes_one_carb_bottle_not_two():
    """The other bottle holds water and electrolyte. Counting both as carb mix
    would contradict the split this module recommends and imply drinking a 16%
    solution with no water alongside it."""
    plan = fuel.build_plan(20.0, week_num=11)
    both_bottles = (plan.refills + 1) * fuel.CARB_MIX_G_PER_500ML
    assert plan.carbs_from_bottles == round(both_bottles / 2)


def test_long_runs_outgrow_the_belt():
    """500 ml at a time can't fuel a 20-miler however often it's re-dosed."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert not plan.liquid_only_is_enough
    assert plan.gel_gap_g > 0
    assert plan.carbs_from_bottles + plan.gel_gap_g == plan.total_grams
    assert "of gels minimum" in " ".join(fuel.plan_lines(plan))


def test_shorter_long_runs_can_go_liquid_only():
    plan = fuel.build_plan(9.0, week_num=3)
    assert plan.liquid_only_is_enough
    assert plan.gel_gap_g == 0


def test_refills_count_stops_not_bottlefuls():
    """The belt leaves home full, so 1500 ml means two refills, not three."""
    plan = fuel.build_plan(9.0, week_num=3)
    mid = sum(fuel.FLUID_ML_PER_HR) / 2
    needed = mid * plan.duration_min / 60
    assert plan.refills == int(-(-needed // fuel.BELT_CAPACITY_ML)) - 1


def test_gels_are_the_default_even_when_liquid_could_cover_it():
    """Specificity, not preference: race day is gel-dominant because 500 ml
    can't fuel four hours, so a bolus every 20 min is what the gut must
    tolerate. Training mostly on sipped carbs adapts it to the wrong pattern."""
    plan = fuel.build_plan(9.0, week_num=3)
    assert plan.liquid_only_is_enough  # it could
    lines = " ".join(fuel.plan_lines(plan))
    assert "Gels carry the session" in lines
    assert "not the bulk" in lines
    # ...and the gel schedule is still the bulk of the target
    assert plan.grams_from_gels > plan.grams_from_drink


def test_gel_flask_suggested_only_when_the_count_gets_silly():
    assert "gel flask" in " ".join(fuel.plan_lines(fuel.build_plan(20.0, week_num=11)))
    assert "gel flask" not in " ".join(fuel.plan_lines(fuel.build_plan(9.0, week_num=3)))
