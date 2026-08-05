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
