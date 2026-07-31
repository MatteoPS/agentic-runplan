from datetime import date, datetime

import pytest

from mc.plan import PlanBlock, PlanLock, PlanWeek


@pytest.fixture
def synthetic_plan() -> PlanLock:
    """A compact, self-contained plan exercising every block type and
    milestone shape, independent of the real frozen plan's specific numbers
    — lets rule tests construct precise edge cases without being constrained
    by real-plan quirks."""
    weeks = [
        PlanWeek(
            week=1, wc=date(2026, 7, 27), long_run_mi=8, run_miles=20, run_days=4,
            cross_minutes=45, quality_sessions=0, long_run_ratio_max=0.35, block="build",
        ),
        PlanWeek(
            week=2, wc=date(2026, 8, 3), long_run_mi=6, run_miles=16, run_days=4,
            cross_minutes=45, quality_sessions=0, long_run_ratio_max=0.35, is_stepback=True,
            block="build",
        ),
        PlanWeek(
            week=3, wc=date(2026, 8, 10), long_run_mi=18, run_miles=40, run_days=5,
            cross_minutes=125, quality_sessions=0, long_run_ratio_max=0.35, block="build",
        ),
        PlanWeek(
            week=4, wc=date(2026, 8, 17), long_run_mi=10, run_miles=22, run_days=4,
            cross_minutes=40, quality_sessions=0, long_run_ratio_max=0.40, block="pre_travel",
        ),
        PlanWeek(
            week=5, wc=date(2026, 8, 24), long_run_mi=12, run_miles=18, run_days=3,
            cross_minutes=0, quality_sessions=0, long_run_ratio_max=0.70, block="travel_italy",
        ),
        PlanWeek(
            week=6, wc=date(2026, 8, 31), long_run_mi=12, run_miles=20, run_days=4,
            cross_minutes=0, quality_sessions=0, long_run_ratio_max=0.60, block="travel_italy",
        ),
        PlanWeek(
            week=7, wc=date(2026, 9, 7), long_run_mi=12, run_miles=20, run_days=3,
            cross_minutes=45, quality_sessions=0, long_run_ratio_max=0.50, block="return",
        ),
        PlanWeek(
            week=8, wc=date(2026, 9, 14), long_run_mi=20, run_miles=45, run_days=5,
            cross_minutes=70, quality_sessions=0, long_run_ratio_max=0.40, is_twenty=True,
            block="push",
        ),
        PlanWeek(
            week=9, wc=date(2026, 9, 21), long_run_mi=12, run_miles=28, run_days=4,
            cross_minutes=0, quality_sessions=0, long_run_ratio_max=0.45, is_taper=True,
            block="taper",
        ),
        PlanWeek(
            week=10, wc=date(2026, 9, 28), long_run_mi=8, run_miles=21, run_days=4,
            cross_minutes=0, quality_sessions=0, long_run_ratio_max=0.40, is_taper=True,
            block="taper",
        ),
    ]
    blocks = {
        "build": PlanBlock(weeks=(1, 3), compliance_floor=0.90),
        "pre_travel": PlanBlock(weeks=(4, 4), compliance_floor=0.85),
        "travel_italy": PlanBlock(
            weeks=(5, 6), compliance_floor=0.40,
            long_run_opportunistic=True, no_quality=True, no_gym=True,
        ),
        "return": PlanBlock(weeks=(7, 7), compliance_floor=0.55),
        "push": PlanBlock(weeks=(8, 8), compliance_floor=0.95),
        "taper": PlanBlock(weeks=(9, 10), compliance_floor=1.00, frozen=True),
    }
    return PlanLock(
        race_date=date(2026, 10, 5),
        plan="synthetic test plan",
        units="miles",
        locked_at=datetime(2026, 7, 28, 12, 0, 0),
        weeks=weeks,
        blocks=blocks,
    )


@pytest.fixture
def real_plan() -> PlanLock:
    """The actual frozen plan.lock.json — used for B7 tests (which need the
    real Italy arrival/return dates) and integration-style sanity checks."""
    from mc.plan import load_plan

    return load_plan()
