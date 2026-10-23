"""Shared fixtures — and the sandbox that keeps the suite out of the real
state repo.

`uv run pytest` used to write into `data/` and `log/` for real: `mc digest`,
invoked unmocked by test_cli.py, rewrote `data/digest/latest.md` and backfilled
`log/training-log.md`, once flipping a `*(pending)*` row to `Nothing logged`
before the activity for that day had synced. The training log is a whole-file
rewrite with no merge logic, so that is the exact class of silent loss
`mc state` exists to prevent — caused by running the tests.

It had been noticed once and fixed one path at a time (test_render_all_does_
not_crash still monkeypatches `cfg.OUT_DIR`, with a comment about a test that
"destroys data every time the suite runs"). Redirecting paths individually
fails open: the next writable path anyone adds leaks, and nothing says so. So
the isolation is structural instead, on the same argument the public/private
repo split was made on — point `MC_STATE_DIR` at a throwaway directory before
anything imports `mc.config`, and there is no path left to leak through.

Why this block sits above the imports, and why it is not a fixture: `config.py`
resolves `STATE_ROOT` and every path under it **at import time**, and
`layout.STATE_PATH` / `strength.STATE_PATH` are derived from `cfg.DATA_DIR` the
same way. Setting the environment first is what puts those derived constants in
the sandbox too — a fixture monkeypatching `cfg` attributes cannot reach them.
`load_dotenv(override=False)` means this also beats a laptop `.env` that sets
`MC_STATE_DIR` itself.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_REAL_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = Path(tempfile.mkdtemp(prefix="mc-test-state-"))

os.environ["MC_STATE_DIR"] = str(_SANDBOX)
# No test copies anything into whatever folder the phone syncs.
os.environ.pop("MC_EXPORT_DIR", None)
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)


def _seed_sandbox() -> None:
    """Real data to read, throwaway copies to write.

    `data/raw` is symlinked rather than copied: it is tens of megabytes, and
    `mc sync` — the only thing that writes there — is deliberately not
    exercised by this suite. Everything the tests actually rewrite is a small
    file, and gets a copy.
    """
    # Deliberately not a git repo: state.save()/claim() no-op against a root
    # with no .git, so the default path cannot commit or push anything. The
    # tests that exercise the git machinery build their own repos in tmp_path
    # and pass explicit roots, so MC_STATE_GIT stays untouched here — setting
    # it off globally would disable the very behaviour test_state.py asserts.
    for sub in ("data", "log", "out"):
        (_SANDBOX / sub).mkdir(parents=True, exist_ok=True)

    raw = _REAL_ROOT / "data" / "raw"
    if raw.exists():
        (_SANDBOX / "data" / "raw").symlink_to(raw, target_is_directory=True)

    for name in ("week_layout.json", "strength_schedule.json", "pushed.json"):
        real = _REAL_ROOT / "data" / name
        if real.exists():
            shutil.copy2(real, _SANDBOX / "data" / name)

    training_log = _REAL_ROOT / "log" / "training-log.md"
    if training_log.exists():
        shutil.copy2(training_log, _SANDBOX / "log" / "training-log.md")


_seed_sandbox()

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402

from mc.plan import PlanBlock, PlanLock, PlanWeek  # noqa: E402


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
