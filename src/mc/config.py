from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Where personal state lives. Defaults to PROJECT_ROOT, so an existing
# checkout behaves exactly as before until MC_STATE_DIR is set.
#
# The split exists because this repo is public and everything /daily reads --
# log/, data/, out/ -- is real training and health data, gitignored for that
# reason. Pointing STATE_ROOT at a separate *private* repo makes the leak
# structurally impossible rather than carefully avoided, and gives a second
# machine somewhere to sync from. Git is the sync layer on purpose: three of
# these state files are whole-file rewrites with no merge logic
# (log/training-log.md, data/strength_schedule.json, data/pushed.json), and a
# cloud drive would resolve that class of conflict silently while git refuses
# and makes you look. See TODO.md.
#
# What deliberately does NOT move: plan/ (frozen, versioned, part of the
# public showcase) and context/equivalence.md (research notes, no personal
# data). context/overrides.md does move -- it accumulates the reasons real
# life diverged from the plan.
STATE_ROOT = Path(os.environ.get("MC_STATE_DIR") or PROJECT_ROOT).expanduser()

DATA_DIR = STATE_ROOT / "data"
RAW_GARMIN_DIR = DATA_DIR / "raw" / "garmin"
RAW_INTERVALS_DIR = DATA_DIR / "raw" / "intervals"
RAW_WEATHER_DIR = DATA_DIR / "raw" / "weather"
GARMIN_TOKENS_DIR = DATA_DIR / ".garmin_tokens"
DIGEST_DIR = DATA_DIR / "digest"
SYNC_REPORT_PATH = DATA_DIR / "sync_report.json"
PUSHED_PATH = DATA_DIR / "pushed.json"

PLAN_DIR = PROJECT_ROOT / "plan"
PLAN_LOCK_PATH = PLAN_DIR / "plan.lock.json"
PLAN_MD_PATH = PLAN_DIR / "plan.md"

CONTEXT_DIR = PROJECT_ROOT / "context"  # equivalence.md — research notes, stays public
OVERRIDES_LOG_PATH = STATE_ROOT / "context" / "overrides.md"

LOG_DIR = STATE_ROOT / "log"
LOG_SESSIONS_DIR = LOG_DIR / "sessions"
TRAINING_LOG_PATH = LOG_DIR / "training-log.md"

OUT_DIR = STATE_ROOT / "out"


def state_is_split() -> bool:
    """True once MC_STATE_DIR points somewhere other than the code checkout.

    Descriptive only. This is *not* the right gate for the writer guard — see
    state_git_enabled().
    """
    return STATE_ROOT != PROJECT_ROOT


_OFF_VALUES = {"off", "0", "false", "no"}


def state_git_enabled() -> bool:
    """Whether the writer guard should do git work: run the behind-check,
    commit/push the lease, commit state.

    This used to be state_is_split(), which was a proxy that quietly stopped
    being true the moment code and state lived in one repo — and then the guard
    silently did nothing. That is exactly backwards: the guard exists because
    three state files are whole-file rewrites with no merge logic
    (log/training-log.md, data/strength_schedule.json, data/pushed.json), and
    that is a property of *those files*, not of whether they happen to sit
    beside the code. What actually matters is whether STATE_ROOT is a git repo
    — i.e. whether there is any history to lose a write from.

    MC_STATE_GIT=off opts out entirely, for a plain local checkout with no
    second machine and no wish for per-ritual commits.
    """
    return (os.environ.get("MC_STATE_GIT") or "").strip().lower() not in _OFF_VALUES


class ConfigError(Exception):
    """Raised only when a caller actually needs a missing/invalid setting."""


@dataclass(frozen=True)
class Settings:
    garmin_email: str | None
    garmin_password: str | None
    intervals_api_key: str | None
    intervals_athlete_id: str | None


def load_settings() -> Settings:
    return Settings(
        garmin_email=os.environ.get("GARMIN_EMAIL") or None,
        garmin_password=os.environ.get("GARMIN_PASSWORD") or None,
        intervals_api_key=os.environ.get("INTERVALS_API_KEY") or None,
        intervals_athlete_id=os.environ.get("INTERVALS_ATHLETE_ID") or None,
    )


settings = load_settings()


def require_intervals_credentials(s: Settings = settings) -> tuple[str, str]:
    """Hard gate — intervals.icu has no equivalent to Garmin's cached-token
    login path, so a missing key/athlete id is always a real error."""
    missing = [
        name
        for name, value in [
            ("INTERVALS_API_KEY", s.intervals_api_key),
            ("INTERVALS_ATHLETE_ID", s.intervals_athlete_id),
        ]
        if not value
    ]
    if missing:
        raise ConfigError(
            f"Missing required env var(s): {', '.join(missing)}. "
            f"Set them in .env (see .env.example)."
        )
    assert s.intervals_api_key is not None
    assert s.intervals_athlete_id is not None
    return s.intervals_api_key, s.intervals_athlete_id


def ensure_data_dirs() -> None:
    for d in (RAW_GARMIN_DIR, RAW_INTERVALS_DIR, RAW_WEATHER_DIR, GARMIN_TOKENS_DIR, DIGEST_DIR):
        d.mkdir(parents=True, exist_ok=True)
