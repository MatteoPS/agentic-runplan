"""Fixed, unskippable strength sessions (added 29-07-2026 at my
request, on top of C4's "free to adjust" strength/mobility work) -- the
progressive-overload counterpart to the ad hoc strength block. Two sessions
per week, tied to that week's two shortest running days, done after the run.
Governed by C4 (strength/mobility needs no plan approval to add), not §6's
running-volume rules -- this module never touches plan.lock.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from mc import config as cfg
from mc.equivalence import (
    CALF_RAISE_TIERS,
    HAMSTRING_SAFE_ITEMS,
    TIBIALIS_RAISE_TIERS,
    StrengthMobilityItem,
)

STATE_PATH = cfg.DATA_DIR / "strength_schedule.json"

SESSIONS_PER_WEEK = 2
WEEKS_PER_TIER = 3


def tier_for_week(week_num: int) -> int:
    """Advances every WEEKS_PER_TIER weeks, capped at the last defined tier."""
    return min((max(week_num, 1) - 1) // WEEKS_PER_TIER, len(CALF_RAISE_TIERS) - 1)


def items_for_week(week_num: int) -> list[StrengthMobilityItem]:
    tier = tier_for_week(week_num)
    return [CALF_RAISE_TIERS[tier], TIBIALIS_RAISE_TIERS[tier], HAMSTRING_SAFE_ITEMS[0]]


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def get_fixed_days(week_start: str) -> list[str] | None:
    """week_start is the DD-MM Monday key used elsewhere in this project."""
    week = _load_state().get(week_start)
    return list(week["status"].keys()) if week else None


def _week_entry(state: dict, week_start: str) -> dict | None:
    return state.get(week_start)


def set_fixed_days(week_start: str, day_miles: dict[str, float], long_run_day: str) -> list[str]:
    """Pick SESSIONS_PER_WEEK running days -- excluding rest days (0mi) and the
    long run day -- ranked shortest first, and persist. First call for a given
    week wins: the designation must not drift as the week's day layout gets
    reshuffled under C1, or 'unskippable' loses meaning.
    """
    state = _load_state()
    if week_start in state:
        return list(state[week_start]["status"].keys())
    candidates = [(mi, day) for day, mi in day_miles.items() if day != long_run_day and mi > 0]
    candidates.sort(key=lambda x: x[0])
    chosen = sorted(day for _, day in candidates[:SESSIONS_PER_WEEK])
    state[week_start] = {"status": {d: "pending" for d in chosen}, "moved": {}}
    _save_state(state)
    return chosen


def _ddmm_to_date(s: str, year: int = 2026) -> date:
    day, month = s.split("-")
    return date(year, int(month), int(day))


def pending_confirmation(week_start: str, as_of: str) -> str | None:
    """Returns the fixed day still awaiting a done/missed confirmation whose
    date is strictly before as_of (DD-MM) -- i.e. the day-after check. None
    if nothing's pending (including 'no schedule for this week yet')."""
    week = _week_entry(_load_state(), week_start)
    if not week:
        return None
    cutoff = _ddmm_to_date(as_of)
    pending_days = [d for d, status in week["status"].items() if status == "pending" and _ddmm_to_date(d) < cutoff]
    pending_days.sort(key=_ddmm_to_date)
    return pending_days[0] if pending_days else None


def confirm_day(week_start: str, day: str, done: bool) -> None:
    state = _load_state()
    week = _week_entry(state, week_start)
    if not week or day not in week["status"]:
        raise KeyError(f"{day} is not a fixed strength day for week {week_start}")
    week["status"][day] = "done" if done else "missed"
    _save_state(state)


def reschedule_missed(
    week_start: str, missed_day: str, candidate_day_miles: dict[str, float], long_run_day: str
) -> str | None:
    """Move a missed session to the best remaining day this week: shortest
    running day (mi > 0), not the long run day, not already a fixed day for
    this week. Returns the new day, or None if nothing suitable is left this
    week (missed session just stays missed -- no cross-week makeup, matching
    the plan's own no-makeup spirit even though C4 doesn't require it)."""
    state = _load_state()
    week = _week_entry(state, week_start)
    if not week or missed_day not in week["status"]:
        raise KeyError(f"{missed_day} is not a fixed strength day for week {week_start}")
    already_fixed = set(week["status"].keys())
    candidates = [
        (mi, day)
        for day, mi in candidate_day_miles.items()
        if day != long_run_day and day not in already_fixed and mi > 0
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    new_day = candidates[0][1]
    del week["status"][missed_day]
    week["status"][new_day] = "pending"
    week["moved"][missed_day] = new_day
    _save_state(state)
    return new_day


@dataclass
class ShinCheckLevel:
    level: int
    meaning: str
    action: str


SHIN_CHECK_SCALE = [
    ShinCheckLevel(0, "nothing", "no action"),
    ShinCheckLevel(1, "tender to palpation only, not felt during running", "watch, no change to plan"),
    ShinCheckLevel(2, "aware of it during runs but not limiting", "C2-eligible — consider a cross swap today"),
    ShinCheckLevel(3, "changes how you run", "D1/D2 safety stop — no running plan today, see a professional"),
]


def format_shin_check_prompt() -> str:
    lines = [f"{lvl.level} = {lvl.meaning}" for lvl in SHIN_CHECK_SCALE]
    return "Shin/tibia symptoms today (0-3: " + "; ".join(lines) + ")?"
