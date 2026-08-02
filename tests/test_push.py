from datetime import date

import pytest

from mc import push
from mc import rules as rules_mod


# --- pace / target helpers ---------------------------------------------------------


def test_pace_to_mps():
    # 10:00/mi -> 1609.344m / 600s
    assert push.pace_to_mps(10.0) == pytest.approx(1609.344 / 600, rel=1e-6)


def test_fmt_pace():
    assert push._fmt_pace(9.75) == "9:45"
    assert push._fmt_pace(10.0) == "10:00"


def test_hr_zone_target_structure():
    target = push._hr_zone_target(135, 150)
    assert target["targetType"]["workoutTargetTypeId"] == 4
    assert target["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert target["targetValueOne"] == 135
    assert target["targetValueTwo"] == 150


# --- workout construction ----------------------------------------------------------


def test_workout_name_format(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    assert workout.workoutName == "MC W1 29-07 easy"


def test_constant_hr_collapses_to_a_single_step(synthetic_plan):
    """A warmup/cooldown split at the same HR as the main set is three alerts
    for one instruction -- see push._build_steps."""
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    steps = workout.workoutSegments[0].workoutSteps
    assert len(steps) == 1
    assert steps[0].stepType["stepTypeKey"] == "interval"
    # the single step spans the whole session -- no time is lost to phases
    # that no longer exist
    assert steps[0].endConditionValue == pytest.approx(8 * 9.75 * 60)


def test_pace_session_also_collapses(synthetic_plan):
    """Pace days carry no distinct warmup target today either, so they take
    the same path. This test is the tripwire: give warmup its own target and
    this is the assertion that should be revisited."""
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="pace", distance_mi=6, hr_low=150, hr_high=160)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    assert len(workout.workoutSegments[0].workoutSteps) == 1


def test_differing_targets_still_produce_three_steps():
    """The split path is retained for the day warmup gets its own target."""
    easy = push._hr_zone_target(120, 135)
    hard = push._hr_zone_target(150, 165)
    steps = push._build_steps(3600, easy, hard, easy)
    assert len(steps) == 3
    assert [s.stepType["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert steps[0].endConditionValue == push.WARMUP_SECONDS
    assert steps[1].endConditionValue == 3600 - push.WARMUP_SECONDS - push.COOLDOWN_SECONDS
    assert steps[2].endConditionValue == push.COOLDOWN_SECONDS


def test_estimated_duration_unchanged_by_step_collapse(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    assert workout.estimatedDurationInSecs == round(8 * 9.75 * 60)


def test_all_steps_carry_hr_target(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    for step in workout.workoutSegments[0].workoutSteps:
        assert step.targetType["workoutTargetTypeId"] == 4
        assert step.targetValueOne == 135
        assert step.targetValueTwo == 145


def test_long_run_pace_is_ceiling_not_hard_target(synthetic_plan):
    week = synthetic_plan.week_by_number(3)  # 18mi week
    session = push.SessionSpec(session_type="long", distance_mi=18, hr_low=130, hr_high=150, pace_min_per_mi=10.5)
    workout = push.build_workout(week, date(2026, 8, 16), session, easy_pace_min_per_mi=9.75)
    assert "ceiling" in workout.description
    assert "not a hard target" in workout.description
    # and never a pace-zone Garmin target on any step -- HR only
    for step in workout.workoutSegments[0].workoutSteps:
        assert step.targetType["workoutTargetTypeKey"] == "heart.rate.zone"


def test_easy_session_description_has_no_ceiling_language(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145, pace_min_per_mi=9.5)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    assert "ceiling" not in workout.description


def test_to_dict_round_trips_as_json_serializable(synthetic_plan):
    import json

    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 29), session, easy_pace_min_per_mi=9.75)
    payload = workout.to_dict()
    json.dumps(payload)  # must not raise


# --- modality (elliptical/bike) workout construction --------------------------------


def test_elliptical_workout_uses_cardio_training_sport_type(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", modality="elliptical", duration_min=60, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 28), session, easy_pace_min_per_mi=9.75)
    assert workout.sportType["sportTypeId"] == 6
    assert workout.sportType["sportTypeKey"] == "cardio_training"
    assert workout.estimatedDurationInSecs == 3600  # exactly 60 min, not distance*pace
    assert workout.workoutName == "MC W1 28-07 elliptical"


def test_bike_workout_uses_cycling_sport_type(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", modality="bike", duration_min=60, hr_low=130, hr_high=140)
    workout = push.build_workout(week, date(2026, 7, 28), session, easy_pace_min_per_mi=9.75)
    assert workout.sportType["sportTypeId"] == 2
    assert workout.sportType["sportTypeKey"] == "cycling"
    assert workout.workoutName == "MC W1 28-07 bike"


def test_run_workout_still_uses_distance_times_pace(synthetic_plan):
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", modality="run", distance_mi=8, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 28), session, easy_pace_min_per_mi=9.75)
    assert workout.estimatedDurationInSecs == round(8 * 9.75 * 60)


def test_duration_min_override_takes_precedence_over_distance(synthetic_plan):
    # if both are set, an explicit duration_min always wins for non-run modalities
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", modality="elliptical", distance_mi=999, duration_min=45, hr_low=135, hr_high=145)
    workout = push.build_workout(week, date(2026, 7, 28), session, easy_pace_min_per_mi=9.75)
    assert workout.estimatedDurationInSecs == 2700  # 45 min, ignores distance_mi entirely


# --- parsing out/today.md -----------------------------------------------------------


def test_parse_session_happy_path():
    md = "# 29-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\n## Today — 8 mi easy @ HR 135–145\n"
    s = push.parse_session_from_today_md(md, date(2026, 7, 29))
    assert s.session_type == "easy"
    assert s.distance_mi == 8.0
    assert (s.hr_low, s.hr_high) == (135, 145)


def test_parse_session_wrong_date_raises():
    md = "# 29-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\n## Today — 8 mi easy @ HR 135–145\n"
    with pytest.raises(push.SessionParseError, match="29-07"):
        push.parse_session_from_today_md(md, date(2026, 7, 30))


def test_parse_session_missing_header_raises():
    md = "## Today — 8 mi easy @ HR 135–145\n"
    with pytest.raises(push.SessionParseError):
        push.parse_session_from_today_md(md, date(2026, 7, 29))


def test_parse_session_missing_today_line_raises():
    md = "# 29-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\nnothing here\n"
    with pytest.raises(push.SessionParseError):
        push.parse_session_from_today_md(md, date(2026, 7, 29))


def test_parse_session_no_hr_falls_back_to_default():
    md = "# 29-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\n## Today — 8 mi easy\n"
    s = push.parse_session_from_today_md(md, date(2026, 7, 29))
    assert (s.hr_low, s.hr_high) == (push.DEFAULT_HR_LOW, push.DEFAULT_HR_HIGH)


def test_parse_session_long_gets_pace_ceiling():
    md = "# 06-09 · Week 6/14 · w/c 31-08 · 9 weeks to NYC\n\n## Today — 18 mi long @ HR 130–150\n"
    s = push.parse_session_from_today_md(md, date(2026, 9, 6), easy_pace_min_per_mi=9.75)
    assert s.session_type == "long"
    assert s.pace_min_per_mi == 9.75


def test_parse_session_easy_has_no_pace_ceiling():
    md = "# 29-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\n## Today — 8 mi easy @ HR 135–145\n"
    s = push.parse_session_from_today_md(md, date(2026, 7, 29))
    assert s.pace_min_per_mi is None


# --- parsing modality (elliptical/bike) from today.md --------------------------------


_ELLIPTICAL_TODAY_MD = (
    "# 28-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC\n\n"
    "## Today — Elliptical 60 min @ HR 135–145\n"
    "Usual slot: ~20:09.\n\n"
    "## If you can't do the elliptical\n"
    "| Option | Duration | Est. equivalent | Verdict |\n"
    "|---|---|---|---|\n"
    "| Elliptical (planned) | 60 min @ HR 135–145 | ~90% | ✅ good substitute |\n"
    "| Bike | 60 min @ HR 130–140 | ~78% | ⚠️ aerobic only |\n"
    "| Rest instead | — | 0% | ❌ not recommended |\n"
)


def test_parse_session_regression_60min_is_not_60_miles():
    # this is the actual bug that motivated the fix -- "60 min" must never
    # be read as "60 mi"
    s = push.parse_session_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28))
    assert s.modality == "elliptical"
    assert s.duration_min == 60.0
    assert s.distance_mi == 0.0


def test_parse_session_elliptical_today_line():
    s = push.parse_session_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28))
    assert s.modality == "elliptical"
    assert (s.hr_low, s.hr_high) == (135, 145)


def test_parse_option_bike_selects_bike_row():
    s = push.parse_option_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28), "bike")
    assert s.modality == "bike"
    assert s.duration_min == 60.0
    assert (s.hr_low, s.hr_high) == (130, 140)


def test_parse_option_elliptical_selects_elliptical_row():
    s = push.parse_option_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28), "elliptical")
    assert s.modality == "elliptical"
    assert (s.hr_low, s.hr_high) == (135, 145)


def test_parse_option_case_insensitive():
    s = push.parse_option_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28), "BIKE")
    assert s.modality == "bike"


def test_parse_option_no_match_raises():
    with pytest.raises(push.SessionParseError, match="swim"):
        push.parse_option_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 28), "swim")


def test_parse_option_wrong_date_raises():
    with pytest.raises(push.SessionParseError):
        push.parse_option_from_today_md(_ELLIPTICAL_TODAY_MD, date(2026, 7, 29), "bike")


# --- check_before_push --------------------------------------------------------------


def test_check_before_push_protects_a3(synthetic_plan):
    week = synthetic_plan.week_by_number(3)  # protected 18mi week
    actuals = rules_mod.ProposedWeek(week=3, long_run_mi=0, run_miles=22, run_days=3, cross_minutes=125)
    session = push.SessionSpec(session_type="long", distance_mi=15, hr_low=130, hr_high=150)  # short of 18mi
    result = push.check_before_push(session, week, actuals, synthetic_plan)
    assert not result.allowed
    assert any(v.rule_id == "A3" for v in result.violations)


def test_check_before_push_a1_a3_do_not_fire_on_non_long_pushes(synthetic_plan):
    # regression: pushing an early-week easy/cross session on a protected
    # (18mi) week must not be blocked by "the long run is short" (A1/A3) --
    # the long run hasn't happened yet, it's not what's being pushed
    week = synthetic_plan.week_by_number(3)
    actuals = rules_mod.ProposedWeek(week=3, long_run_mi=0, run_miles=0, run_days=0, cross_minutes=0)
    session = push.SessionSpec(session_type="easy", modality="elliptical", duration_min=45, hr_low=135, hr_high=145)
    result = push.check_before_push(session, week, actuals, synthetic_plan)
    assert not any(v.rule_id in ("A1", "A3") for v in result.violations)


def test_check_before_push_allows_compliant_session(synthetic_plan):
    week = synthetic_plan.week_by_number(3)
    actuals = rules_mod.ProposedWeek(week=3, long_run_mi=0, run_miles=22, run_days=3, cross_minutes=125)
    session = push.SessionSpec(session_type="long", distance_mi=18, hr_low=130, hr_high=150)
    result = push.check_before_push(session, week, actuals, synthetic_plan)
    assert result.allowed


def test_check_before_push_routes_cross_training_to_cross_minutes_not_run_miles(synthetic_plan, monkeypatch):
    # pushing an elliptical session must never be misread as running volume
    captured = {}
    original_check_week = rules_mod.check_week

    def spy(proposed, plan):
        captured["proposed"] = proposed
        return original_check_week(proposed, plan)

    monkeypatch.setattr(rules_mod, "check_week", spy)

    week = synthetic_plan.week_by_number(1)
    actuals = rules_mod.ProposedWeek(week=1, long_run_mi=6.1, run_miles=6.1, run_days=1, cross_minutes=0)
    session = push.SessionSpec(session_type="easy", modality="elliptical", duration_min=60, hr_low=135, hr_high=145)
    push.check_before_push(session, week, actuals, synthetic_plan)

    assert captured["proposed"].run_miles == 6.1
    assert captured["proposed"].run_days == 1
    assert captured["proposed"].cross_minutes == 60


def test_check_before_push_only_blocks_on_immediate_rules_not_end_of_week_ones(synthetic_plan):
    # day-2-of-7 style scenario: week barely started, would fail A2/A9/A10 if
    # those were checked, but a plain compliant elliptical session must not
    # be blocked by metrics that are only meaningful once the week is over
    week = synthetic_plan.week_by_number(1)
    actuals = rules_mod.ProposedWeek(week=1, long_run_mi=6.1, run_miles=6.1, run_days=1, cross_minutes=0)
    session = push.SessionSpec(session_type="easy", modality="elliptical", duration_min=60, hr_low=135, hr_high=145)
    result = push.check_before_push(session, week, actuals, synthetic_plan)
    assert result.allowed
    assert result.violations == []


# --- push_workout / unpush_workout: only the network-free paths --------------------


def test_push_workout_dry_run_never_touches_network(synthetic_plan, monkeypatch):
    def _fail(*a, **kw):
        raise AssertionError("dry_run must never call garmin.get_client")

    monkeypatch.setattr("mc.garmin.get_client", _fail)
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    result = push.push_workout(date(2026, 7, 29), week, session, 9.75, dry_run=True, yes=True)
    assert result.action == "dry_run"
    assert result.workout_id is None


def test_push_workout_without_yes_raises_before_network(synthetic_plan, monkeypatch):
    def _fail(*a, **kw):
        raise AssertionError("must refuse before calling garmin.get_client")

    monkeypatch.setattr("mc.garmin.get_client", _fail)
    week = synthetic_plan.week_by_number(1)
    session = push.SessionSpec(session_type="easy", distance_mi=8, hr_low=135, hr_high=145)
    with pytest.raises(push.PushError, match="--yes"):
        push.push_workout(date(2026, 7, 29), week, session, 9.75, dry_run=False, yes=False)


def test_unpush_returns_false_when_nothing_pushed(tmp_path, monkeypatch):
    monkeypatch.setattr("mc.config.PUSHED_PATH", tmp_path / "pushed.json")

    def _fail(*a, **kw):
        raise AssertionError("must not call garmin.get_client when there's nothing to unpush")

    monkeypatch.setattr("mc.garmin.get_client", _fail)
    assert push.unpush_workout(date(2026, 7, 29)) is False


def test_pushed_json_persistence_round_trip(tmp_path, monkeypatch):
    pushed_path = tmp_path / "pushed.json"
    monkeypatch.setattr("mc.config.PUSHED_PATH", pushed_path)
    push._save_pushed({"2026-07-29": {"workout_id": "123"}})
    assert push._load_pushed() == {"2026-07-29": {"workout_id": "123"}}
    assert pushed_path.exists()
