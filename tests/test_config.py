"""The suite must not be able to write to the real state repo.

Enforced rather than documented, in the spirit of the writer guard: the
sandbox in conftest.py is one environment variable set before one import, and
an assertion is the only thing that would notice if that ever stopped working
(a plugin importing mc.config first, a change to how STATE_ROOT resolves, a
stray MC_STATE_DIR in the environment).
"""

from mc import config as cfg
from mc import layout as layout_mod
from mc import strength as strength_mod


def test_state_root_is_sandboxed():
    assert cfg.STATE_ROOT != cfg.PROJECT_ROOT


def test_no_writable_path_points_into_the_checkout():
    """Every path the code writes to, including the two derived in other
    modules from cfg.DATA_DIR at import time."""
    writable = [
        cfg.DATA_DIR,
        cfg.DIGEST_DIR,
        cfg.RAW_WEATHER_DIR,
        cfg.SYNC_REPORT_PATH,
        cfg.PUSHED_PATH,
        cfg.LOG_DIR,
        cfg.LOG_SESSIONS_DIR,
        cfg.TRAINING_LOG_PATH,
        cfg.OVERRIDES_LOG_PATH,
        cfg.OUT_DIR,
        layout_mod.STATE_PATH,
        strength_mod.STATE_PATH,
    ]
    for path in writable:
        assert not path.is_relative_to(cfg.PROJECT_ROOT), f"{path} would write into the checkout"


def test_the_sandbox_is_not_a_git_repo():
    """What keeps `state.save()` from committing or pushing on the default
    root: there is no repo under it. Left to that rather than MC_STATE_GIT=off,
    which would disable the machinery test_state.py exists to check."""
    assert not (cfg.STATE_ROOT / ".git").exists()
