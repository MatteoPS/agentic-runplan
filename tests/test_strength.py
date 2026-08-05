import pytest

from mc import strength


def test_tier_advances_every_three_weeks():
    assert strength.tier_for_week(1) == 0
    assert strength.tier_for_week(3) == 0
    assert strength.tier_for_week(4) == 1
    assert strength.tier_for_week(6) == 1
    assert strength.tier_for_week(7) == 2


def test_tier_caps_at_last_defined_tier():
    assert strength.tier_for_week(14) == 2
    assert strength.tier_for_week(100) == 2


def test_items_for_week_all_sourced():
    for item in strength.items_for_week(5):
        assert item.source


def test_set_fixed_days_picks_shortest_non_long_run_days(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    day_miles = {
        "27-07": 6.1,
        "28-07": 0,
        "29-07": 3,
        "30-07": 0,
        "31-07": 0,
        "01-08": 2,
        "02-08": 10,
    }
    days = strength.set_fixed_days("27-07", day_miles, long_run_day="02-08")
    assert days == ["01-08", "29-07"]


def test_set_fixed_days_excludes_rest_days_and_long_run(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    day_miles = {"a": 0, "b": 5, "c": 0}
    days = strength.set_fixed_days("wk", day_miles, long_run_day="b")
    assert days == []


def test_set_fixed_days_is_sticky_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    first = strength.set_fixed_days("27-07", {"a": 3, "b": 2, "c": 10}, long_run_day="c")
    second = strength.set_fixed_days("27-07", {"a": 1, "b": 1, "c": 10}, long_run_day="c")
    assert first == second


def test_get_fixed_days_returns_none_when_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    assert strength.get_fixed_days("never-set") is None


def test_pending_confirmation_flags_past_fixed_day(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    assert strength.pending_confirmation("27-07", as_of="30-07") == "29-07"


def test_pending_confirmation_none_before_any_fixed_day_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    # as_of == the fixed day itself -- not "the day after" yet
    assert strength.pending_confirmation("27-07", as_of="29-07") is None


def test_pending_confirmation_clears_after_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    strength.confirm_day("27-07", "29-07", done=True)
    assert strength.pending_confirmation("27-07", as_of="30-07") is None


def test_confirm_day_unknown_day_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    with pytest.raises(KeyError):
        strength.confirm_day("27-07", "30-07", done=True)


def test_reschedule_missed_moves_to_shortest_remaining_day(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    strength.confirm_day("27-07", "29-07", done=False)
    new_day = strength.reschedule_missed(
        "27-07", "29-07", {"30-07": 4, "31-07": 0, "01-08": 2, "02-08": 10}, long_run_day="02-08"
    )
    assert new_day == "30-07"
    days = strength.get_fixed_days("27-07")
    assert "29-07" not in days
    assert "30-07" in days
    assert "01-08" in days  # the other original fixed day is untouched


def test_reschedule_missed_returns_none_when_nothing_suitable_left(tmp_path, monkeypatch):
    monkeypatch.setattr(strength, "STATE_PATH", tmp_path / "strength_schedule.json")
    strength.set_fixed_days("27-07", {"29-07": 3, "01-08": 2, "02-08": 10}, long_run_day="02-08")
    strength.confirm_day("27-07", "29-07", done=False)
    new_day = strength.reschedule_missed(
        "27-07", "29-07", {"30-07": 0, "31-07": 0, "02-08": 10}, long_run_day="02-08"
    )
    assert new_day is None
    # missed day is recorded but not silently dropped -- still shows as this
    # week's (missed) fixed day, just nothing to reschedule it onto
    assert set(strength.get_fixed_days("27-07")) == {"29-07", "01-08"}


def test_shin_check_scale_has_four_levels_with_actions():
    assert len(strength.SHIN_CHECK_SCALE) == 4
    for lvl in strength.SHIN_CHECK_SCALE:
        assert lvl.meaning
        assert lvl.action


def test_format_shin_check_prompt_includes_all_levels():
    prompt = strength.format_shin_check_prompt()
    for n in range(4):
        assert f"{n} =" in prompt


def test_bodyweight_swap_steps_down_one_tier_not_all_the_way():
    """Weights aren't always findable while travelling (confirmed 05-08-2026),
    so this takes the hardest equipment-free variant rather than tier 1."""
    from mc import strength

    full = strength.items_for_week(8)  # tier 3, weighted
    swapped = strength.items_for_week(8, bodyweight_only=True)
    assert any(not i.bodyweight_only for i in full)
    assert all(i.bodyweight_only for i in swapped)
    assert "slow eccentric" in swapped[0].name  # tier 2, not tier 1
    assert len(swapped) == len(full)


def test_bodyweight_swap_is_a_noop_at_lower_tiers():
    from mc import strength

    assert strength.items_for_week(2) == strength.items_for_week(2, bodyweight_only=True)
