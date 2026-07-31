import pytest

from mc import plan as plan_mod


def test_load_real_plan_lock():
    p = plan_mod.load_plan()
    assert p.race_date.isoformat() == "2026-11-01"
    assert len(p.weeks) == 14


def test_week_by_number(synthetic_plan):
    w = synthetic_plan.week_by_number(3)
    assert w.long_run_mi == 18


def test_week_by_number_missing_raises(synthetic_plan):
    with pytest.raises(KeyError):
        synthetic_plan.week_by_number(99)


def test_block_for(synthetic_plan):
    w = synthetic_plan.week_by_number(5)
    block = synthetic_plan.block_for(w)
    assert block.long_run_opportunistic is True
    assert block.no_gym is True


def test_adjacent_week(synthetic_plan):
    assert synthetic_plan.adjacent_week(3, 1).week == 4
    assert synthetic_plan.adjacent_week(1, -1) is None


def test_write_plan_lock_refuses_when_exists(tmp_path, synthetic_plan):
    path = tmp_path / "plan.lock.json"
    plan_mod.write_plan_lock(synthetic_plan, path=path)
    assert path.exists()
    with pytest.raises(plan_mod.PlanImmutableError):
        plan_mod.write_plan_lock(synthetic_plan, path=path)


def test_write_plan_lock_force_overwrites(tmp_path, synthetic_plan):
    path = tmp_path / "plan.lock.json"
    plan_mod.write_plan_lock(synthetic_plan, path=path)
    plan_mod.write_plan_lock(synthetic_plan, path=path, force=True)  # does not raise
