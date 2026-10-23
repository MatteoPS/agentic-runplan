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
    assert plan.n_gels > 0


def test_cadence_is_fixed_regardless_of_week():
    """The whole point of the 17-08-2026 inversion: the interval no longer moves
    week to week, because a schedule that changes is one that gets counted wrong
    at mile 8."""
    intervals = {
        fuel.build_plan(16.0, week_num=w).gel_every_min for w in fuel.FUEL_RAMP_G_PER_HR
    }
    assert intervals == {fuel.GEL_EVERY_MIN}
    assert fuel.GEL_EVERY_MIN == 20


def test_g_per_hr_is_an_outcome_not_an_input():
    """Delivered rate falls out of the fixed cadence; it is not solved for."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.total_grams == plan.grams_from_gels + plan.grams_from_liquid
    assert plan.delivered_g_per_hr == round(plan.total_grams / (plan.duration_min / 60))


def test_first_gel_waits_for_breakfast_but_not_when_there_was_none():
    fed = fuel.build_plan(13.0, week_num=4)
    fasted = fuel.build_plan(13.0, week_num=4, fasted=True)
    assert fed.first_gel_at_min == fuel.FIRST_GEL_FED_MIN == 40
    assert fasted.first_gel_at_min == fuel.FIRST_GEL_FASTED_MIN == 20
    assert fasted.n_gels > fed.n_gels


def test_the_big_three_start_at_20_even_fed():
    """Week 6's 18, week 11's 20 and race day carry the denser start, because
    race day is the reason and A4 closes the door after week 11."""
    assert fuel.build_plan(18.0, week_num=6).first_gel_at_min == 20
    assert fuel.build_plan(20.0, week_num=11).first_gel_at_min == 20
    assert fuel.build_plan(26.2, week_num=14).first_gel_at_min == 20
    # ...and an ordinary long run in an ordinary week does not
    assert fuel.build_plan(16.0, week_num=5).first_gel_at_min == 40


def test_dense_start_needs_the_distance_not_just_the_week():
    """A long run shortened by a reshuffle drops back to the ordinary offset --
    the denser start was chosen for the 18 and the 20, not for whatever week 6
    ends up holding."""
    assert fuel.build_plan(12.0, week_num=6).first_gel_at_min == 40


def test_gel_times_are_readable_off_the_plan():
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.gel_times_min[0] == 20
    assert plan.gel_times_min[1] - plan.gel_times_min[0] == 20
    assert len(plan.gel_times_min) == plan.n_gels
    assert plan.gel_times_min[-1] <= plan.duration_min


def test_first_gel_is_not_at_the_gun_when_fed():
    """The opening 40 min run on breakfast; the count reflects that."""
    plan = fuel.build_plan(16.0, week_num=5)
    naive = int(plan.duration_min // plan.gel_every_min) + 1
    assert plan.n_gels < naive


def test_liquid_packet_only_from_14_mi():
    assert fuel.build_plan(13.0, week_num=4).liquid_packets == 0
    assert fuel.build_plan(14.0, week_num=10).liquid_packets == 1
    assert fuel.build_plan(20.0, week_num=11).liquid_packets == 1


def test_italy_runs_on_gels_alone():
    """Weeks 8-9 buy a 6-pack locally rather than sourcing drink mix abroad for
    two opportunistic sessions."""
    assert fuel.build_plan(14.0, week_num=9).liquid_packets == 0
    assert fuel.build_plan(12.0, week_num=8).liquid_packets == 0
    # the same distance outside the travel block does get a packet
    assert fuel.build_plan(14.0, week_num=10).liquid_packets == 1


def test_liquid_is_a_whole_packet_not_a_computed_shortfall():
    """Carried as it is bought and as it goes into the bottle -- the old code
    printed gram figures no packet size actually matches."""
    plan = fuel.build_plan(16.0, week_num=5)
    assert plan.grams_from_liquid == fuel.LIQUID_PACKET_CARB_G


def test_week_11_is_flagged_as_the_dress_rehearsal():
    """A4 freezes the taper, so the 20 is the last run that can test race day."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.is_dress_rehearsal
    assert "dress rehearsal" in " ".join(fuel.plan_lines(plan))
    assert not fuel.build_plan(18.0, week_num=6).is_dress_rehearsal


def test_reference_ramp_survives_as_a_yardstick():
    """It no longer drives the schedule, but it is still what the plan designed
    for, and the gap has to be reportable."""
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


def test_shortfall_against_the_ramp_is_reported_not_corrected():
    """E3 applies to fuelling too: week 13 delivers well under the ramp's 80,
    and the plan says so rather than squeezing in another gel."""
    plan = fuel.build_plan(8.0, week_num=13)
    assert plan.shortfall_is_material
    assert plan.shortfall_vs_reference == plan.reference_g_per_hr - plan.delivered_g_per_hr
    lines = " ".join(fuel.plan_lines(plan))
    assert "under" in lines and "not corrected" in lines


def test_no_shortfall_note_when_the_cadence_keeps_up():
    plan = fuel.build_plan(20.0, week_num=11)
    assert not plan.shortfall_is_material
    assert "not corrected" not in " ".join(fuel.plan_lines(plan))


def test_transporter_note_tracks_what_is_delivered():
    below = fuel.build_plan(12.0, week_num=12)  # gels only, ~51 g/hr
    above = fuel.build_plan(20.0, week_num=11)  # ~77 g/hr
    assert not any("transporter" in line for line in fuel.plan_lines(below))
    assert any("transporter" in line for line in fuel.plan_lines(above))


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
    assert "first at 20 min" in lines
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


def test_shorter_long_runs_could_go_liquid_only():
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
    # ...and the gel schedule is the whole of the delivered carbohydrate
    assert plan.grams_from_gels > plan.grams_from_liquid


def test_gel_flask_suggested_only_when_the_count_gets_silly():
    """A carrying decision, so it belongs to prep rather than the in-run
    schedule — and it fires on the actual count, not on the belt falling short."""
    assert "flask" in " ".join(fuel.prep_lines(fuel.build_plan(20.0, week_num=11)))
    assert "flask" not in " ".join(fuel.prep_lines(fuel.build_plan(9.0, week_num=3)))


def test_race_day_matches_the_dress_rehearsal_schedule():
    """Nothing new on 01-11: same interval, same offset as week 11 rehearsed."""
    rehearsal = fuel.build_plan(20.0, week_num=11)
    race = fuel.build_plan(26.2, week_num=14)
    assert race.first_gel_at_min == rehearsal.first_gel_at_min
    assert race.gel_every_min == rehearsal.gel_every_min
    assert race.liquid_packets == rehearsal.liquid_packets


def test_the_whole_plan_matches_the_agreed_table():
    """context/fueling.md's table is the agreed protocol; this is the executable
    half of it, and the two drifting apart is exactly the failure that file
    exists to prevent. Distances are plan.lock.json's frozen long runs."""
    expected = {  # week: (miles, gels, liquid packets)
        1: (11, 4, 0),
        2: (12, 4, 0),
        3: (9, 3, 0),
        4: (13, 5, 0),
        5: (16, 6, 1),
        6: (18, 8, 1),
        7: (15, 6, 1),
        8: (12, 4, 0),
        9: (14, 5, 0),
        10: (14, 5, 1),
        11: (20, 9, 1),
        12: (12, 4, 0),
        13: (8, 2, 0),
        14: (26.2, 12, 1),
    }
    for week, (miles, gels, packets) in expected.items():
        plan = fuel.build_plan(miles, week_num=week)
        assert plan is not None, f"week {week} lost its plan"
        assert plan.n_gels == gels, f"week {week}: {plan.n_gels} gels, expected {gels}"
        assert plan.liquid_packets == packets, f"week {week} liquid"
    assert sum(fuel.build_plan(m, week_num=w).n_gels for w, (m, _, _) in expected.items()) == 77


def test_prep_is_silent_for_runs_too_short_to_need_it():
    assert fuel.prep_lines(None) == []
    assert fuel.prep_lines(fuel.build_plan(5.0, week_num=5)) == []


def test_prep_leads_with_the_counts_to_have_ready():
    """The question the night before is "how many gels", and it has to be
    answerable without reading a schedule of when to take them."""
    plan = fuel.build_plan(16.0, week_num=6)
    first = fuel.prep_lines(plan)[0]
    assert str(plan.n_gels) in first
    assert str(plan.carb_sachets) in first
    assert str(plan.electrolyte_tabs) in first


def test_tabs_are_per_fill_but_carb_mix_is_not():
    """The two lines diverge on purpose. Electrolyte is re-dosed at every
    fountain stop, so it is refills + 1. Carb mix is **one packet, once, at the
    start** -- packing three sachets for a 20-miler because the belt gets
    refilled three times would quietly reinstate the drink-led fuelling the
    fixed cadence moved away from."""
    plan = fuel.build_plan(20.0, week_num=11)
    assert plan.electrolyte_tabs == plan.refills + 1
    assert plan.refills >= 2  # the case that used to inflate the sachet count
    assert plan.carb_sachets == plan.liquid_packets == 1
    lines = " ".join(fuel.prep_lines(plan))
    assert "once, at the start" in lines


def test_prep_says_plainly_when_there_is_no_carb_mix():
    """Under 14 mi and in Italy the answer is "none" -- which has to be stated,
    not left as an absent bullet the reader has to notice."""
    lines = " ".join(fuel.prep_lines(fuel.build_plan(12.0, week_num=12)))
    assert "no carb mix" in lines.lower()


def test_prep_carries_the_buying_constraint_it_is_the_last_chance_to_act_on():
    """Above 60 g/hr the product must be mixed-sugar. Saying so only in the
    in-run schedule says it the morning after the shop was the answer.

    Keyed on the **delivered** rate, which under a fixed cadence is a property
    of the session rather than of the week -- the same 16-miler now delivers the
    same g/hr in week 1 as in week 11, so a week-vs-week comparison here would
    be asserting something that is no longer true of the design."""
    over = fuel.build_plan(20.0, week_num=11)  # ~77 g/hr
    under = fuel.build_plan(12.0, week_num=12)  # gels only, ~51 g/hr
    assert over.delivered_g_per_hr > 60 >= under.delivered_g_per_hr
    assert "fructose" in " ".join(fuel.prep_lines(over))
    assert "fructose" not in " ".join(fuel.prep_lines(under))


def test_prep_and_schedule_are_separate_readings():
    """`/preview` prints prep alone, so anything that has to happen before the
    run must be in prep — the meal timing included — and the in-run schedule
    must not be needed to act on it."""
    plan = fuel.build_plan(16.0, week_num=6)
    prep = " ".join(fuel.prep_lines(plan))
    during = " ".join(fuel.plan_lines(plan))
    assert "night before" in prep
    assert "2-3 h beforehand" in prep
    assert "beforehand" not in during
    assert "every" in during and "min" in during  # the schedule stays in plan_lines
