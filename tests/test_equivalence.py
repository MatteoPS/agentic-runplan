from mc import equivalence as eq


def test_parse_session_distance_and_type():
    s = eq.parse_session("8 mi easy")
    assert s.distance_mi == 8.0
    assert s.session_type == "easy"


def test_parse_session_does_not_mistake_minutes_for_miles():
    # regression: "min" starts with "mi", a naive regex misreads "60 min" as "60 mi"
    s = eq.parse_session("60 min elliptical")
    assert s.distance_mi == 0.0


def test_parse_session_still_matches_miles_and_mile_forms():
    assert eq.parse_session("8 mi easy").distance_mi == 8.0
    assert eq.parse_session("18 miles long").distance_mi == 18.0


def test_parse_session_long():
    s = eq.parse_session("18 mi long run")
    assert s.session_type == "long"


def test_parse_session_pace():
    s = eq.parse_session("5 mi pace")
    assert s.session_type == "pace"


def test_long_run_has_no_substitute():
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="long", distance_mi=18))
    assert len(table) == 1
    assert table[0].verdict == eq.VERDICT_NOT_A_SUBSTITUTE


def test_easy_session_returns_four_options():
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=8))
    labels = [o.option for o in table]
    assert labels[0] == "Elliptical"
    assert labels[1] == "Bike"
    assert labels[2].startswith("Ellip ")
    assert labels[3] == "Treadmill"


def test_elliptical_verdict_good():
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=8))
    ellip = next(o for o in table if o.option == "Elliptical")
    assert ellip.verdict == eq.VERDICT_GOOD
    assert ellip.equivalent_pct == eq.ELLIPTICAL_TRANSFER


def test_bike_verdict_aerobic_only():
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=8))
    bike = next(o for o in table if o.option == "Bike")
    assert bike.verdict == eq.VERDICT_AEROBIC_ONLY


def test_treadmill_under_limit_is_good():
    # 4mi @ 9.75 min/mi = 39min, under the 45min cap
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=4))
    treadmill = next(o for o in table if o.option == "Treadmill")
    assert treadmill.verdict == eq.VERDICT_GOOD


def test_treadmill_over_limit_not_recommended():
    # 8mi @ 9.75 min/mi = 78min, over the 45min cap
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=8))
    treadmill = next(o for o in table if o.option == "Treadmill")
    assert treadmill.verdict == eq.VERDICT_NOT_RECOMMENDED
    assert treadmill.equivalent_pct == 1.0  # still 100% physiologically, just impractical


def test_summary_line_states_pct_and_loss_and_count():
    table = eq.build_substitution_table(eq.PrescribedSession(session_type="easy", distance_mi=8))
    line = eq.summary_line(table[0], substitutions_used_this_week=2)
    assert "90%" in line
    assert "impact" in line
    assert "2" in line


def test_no_verdict_vocabulary_drift():
    """Every verdict emitted must be one of the four fixed strings (§4) --
    guards against a future edit accidentally inventing a new label."""
    fixed = {eq.VERDICT_GOOD, eq.VERDICT_AEROBIC_ONLY, eq.VERDICT_NOT_RECOMMENDED, eq.VERDICT_NOT_A_SUBSTITUTE}
    for distance in (2, 4, 8, 12, 18):
        for session_type in ("easy", "pace", "long"):
            table = eq.build_substitution_table(
                eq.PrescribedSession(session_type=session_type, distance_mi=distance)
            )
            for option in table:
                assert option.verdict in fixed


# --- strength & mobility ----------------------------------------------------------


def test_strength_mobility_all_bodyweight():
    items = eq.propose_strength_mobility()
    assert items
    assert all(item.bodyweight_only for item in items)


def test_strength_mobility_respects_target_minutes():
    items = eq.propose_strength_mobility(target_minutes=10)
    assert sum(i.minutes for i in items) <= 10


def test_strength_mobility_every_item_has_a_source():
    for item in eq.propose_strength_mobility(target_minutes=30):
        assert item.source
