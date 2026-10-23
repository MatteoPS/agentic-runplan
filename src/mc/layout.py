"""The week's day-of-week layout, persisted.

`plan.lock.json` freezes weekly aggregates only -- long run distance, weekly
miles, run days, cross minutes. Day-of-week placement is deliberately *not*
frozen (see plan.md: "day-of-week placement is illustrative, not frozen"); it
gets decided each Monday in `/week` under B1-B9. Until now it was decided
conversationally and then discarded, which meant the system could describe
today and nothing else -- "what is Thursday?" had no answer anywhere in the
repo.

This module is the answer. It stores what `/week` already computes.

Relationship to strength.py, which is the subtle part: this layout is
**rewritable** mid-week, because C1 lets easy runs be reordered freely. The
two fixed strength days are **not** -- `strength.set_fixed_days` is
first-write-wins on purpose (see its docstring: "the designation must not
drift as the week's day layout gets reshuffled under C1, or 'unskippable'
loses meaning"). So `revise` never calls into strength. A revision that moves
a run off a fixed strength day is strength's problem to solve via
`reschedule_missed`, not layout's to prevent.

Conflict note: like strength_schedule.json this is a whole-file-rewrite JSON.
Two machines writing it the same day is last-writer-wins. That is tolerable
only under single-writer-per-day discipline -- see the state-sync design in
docs/todo-review.md before this file is ever synced across machines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from mc import config as cfg
from mc import rules as rules_mod

STATE_PATH = cfg.DATA_DIR / "week_layout.json"

# Prescriptions are written to the nearest half mile, and nothing finer is
# ever stored.
#
# A prescription of 5.11 mi is a lie about how running works: an outdoor
# route is eyeballed on the way out to avoid a long walk home and comes back
# a bit over or under, and even a treadmill is set by hand. The hundredths
# were never a measurement -- they were the arithmetic of forcing a weekly
# total to land inside the [floor, ceiling] band, one decimal place at a
# time. w/c 10-08 carried days of 5.11 and 3.87 mi and had been revised 8
# times, which is what that looks like from the outside.
#
# 0.5 mi is ~4-5 min at easy pace, below the resolution of any decision this
# plan makes. Confirmed with me 14-08-2026.
QUANTUM_MI = 0.5


def quantize(miles: float) -> float:
    """Snap a prescribed distance to the nearest QUANTUM_MI."""
    return round(round(miles / QUANTUM_MI) * QUANTUM_MI, 1)

# Session labels. "rest" is a real, deliberate entry rather than an absent day
# -- a planned rest day and an unplanned gap are different things, and A10's
# minimum-running-days check reads better when rest is explicit.
SESSION_TYPES = frozenset({"rest", "easy", "pace", "long", "race", "cross"})

RUNNING_SESSIONS = frozenset({"easy", "pace", "long", "race"})

# "race" exists to hold a measured distance rather than a prescribed one, and
# it was added by the 0.5 mi quantum: a 5K is 3.1 mi because that is what a 5K
# is, and quantizing it to 3.0 discards a fact to satisfy a display
# convention. Without this the Percy Sutton 5K on 08-08 was silently rewritten.
# Distinct from "pace" -- a 5.5 mi pace run is a prescription and *should*
# snap; only the event distance is fixed.
FIXED_DISTANCE_SESSIONS = frozenset({"long", "race"})


class LayoutError(Exception):
    pass


@dataclass(frozen=True)
class DayPlan:
    """Running days carry miles; cross days carry minutes.

    That split isn't an inconsistency, it's the convention this project uses
    everywhere (push.py parses "8 mi easy" for runs and "60 min" for cross;
    §6 A8/A9 weigh cross by minutes). Keeping both fields explicit is what
    lets a layout be checked against A8 (cross ≤ 35% of aerobic load) and A9
    (long-run ratio) -- a layout that stored only miles could not answer
    either question, and would silently fail A9 the moment a week's plan
    counted on its cross-training.
    """

    day: str  # DD-MM
    miles: float
    session: str
    cross_minutes: float = 0.0

    @property
    def is_running(self) -> bool:
        return self.session in RUNNING_SESSIONS


@dataclass(frozen=True)
class WeekLayout:
    week_start: str  # DD-MM Monday, the key used throughout this project
    long_run_day: str
    days: list[DayPlan]
    revised: int = 0  # how many times C1 has reshuffled this week

    @property
    def total_miles(self) -> float:
        return round(sum(d.miles for d in self.days), 1)

    @property
    def total_cross_minutes(self) -> float:
        return round(sum(d.cross_minutes for d in self.days), 1)

    @property
    def run_days(self) -> int:
        return sum(1 for d in self.days if d.is_running and d.miles > 0)

    def day_for(self, ddmm: str) -> DayPlan | None:
        return next((d for d in self.days if d.day == ddmm), None)

    def long_run(self) -> DayPlan | None:
        return self.day_for(self.long_run_day)


# --- persistence (same shape as strength.py) ---------------------------------------


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def _to_layout(week_start: str, entry: dict) -> WeekLayout:
    # Quantized on the way in as well as the way out. `_write` guarantees
    # nothing new lands on disk with hundredths, but this file is tracked
    # state that syncs between devices (see CLAUDE.md's one-writer-per-day
    # lease), so a phone still running an older client can put them back. A
    # read that normalizes means no consumer ever has to care which client
    # wrote the week.
    return WeekLayout(
        week_start=week_start,
        long_run_day=entry["long_run_day"],
        days=_quantize_days([DayPlan(**d) for d in entry["days"]]),
        revised=entry.get("revised", 0),
    )


def get_layout(week_start: str) -> WeekLayout | None:
    entry = _load_state().get(week_start)
    return _to_layout(week_start, entry) if entry else None


def _validate(days: list[DayPlan], long_run_day: str) -> None:
    bad = [d.session for d in days if d.session not in SESSION_TYPES]
    if bad:
        raise LayoutError(f"Unknown session type(s): {sorted(set(bad))}. Allowed: {sorted(SESSION_TYPES)}")
    seen = [d.day for d in days]
    if len(seen) != len(set(seen)):
        raise LayoutError(f"Duplicate day(s) in layout: {sorted({d for d in seen if seen.count(d) > 1})}")
    if long_run_day not in seen:
        raise LayoutError(f"long_run_day {long_run_day} is not one of the layout's days: {seen}")
    marked = [d.day for d in days if d.session == "long"]
    if marked != [long_run_day]:
        raise LayoutError(
            f"Exactly one day must be session=long and it must be long_run_day "
            f"({long_run_day}); got {marked or 'none'}."
        )


def _quantize_days(days: list[DayPlan]) -> list[DayPlan]:
    """Snap prescribed running distances to QUANTUM_MI.

    Applied here rather than in the parser because this is the choke point --
    everything that reaches disk goes through `_write`, whether it came from
    `mc layout --set`, `--revise`, or a caller building DayPlans directly. A
    layout on disk therefore cannot carry hundredths.

    Two exemptions, both because the number is a measurement rather than a
    prescription:

    - **FIXED_DISTANCE_SESSIONS.** The long run's distance is frozen in
      plan.lock.json under A1/A3 -- week 14's is the marathon itself (26.2) --
      so snapping it to fit a display convention is the tail wagging the dog,
      and would put every long run 0.2 mi from its own A1 tolerance for no
      reason. A race's distance is fixed by the race.
    - **Cross days**, whose number is minutes, not miles (see DayPlan).
    """
    return [
        d
        if d.session in FIXED_DISTANCE_SESSIONS or d.session == "cross"
        else replace(d, miles=quantize(d.miles))
        for d in days
    ]


def _write(week_start: str, days: list[DayPlan], long_run_day: str, revised: int) -> WeekLayout:
    _validate(days, long_run_day)
    days = _quantize_days(days)
    state = _load_state()
    state[week_start] = {
        "long_run_day": long_run_day,
        "days": [asdict(d) for d in sorted(days, key=lambda d: _ddmm_to_date(d.day))],
        "revised": revised,
    }
    _save_state(state)
    return _to_layout(week_start, state[week_start])


def set_layout(week_start: str, days: list[DayPlan], long_run_day: str) -> WeekLayout:
    """First write for the week. Idempotent-ish: calling it again on a week
    that already has a layout returns the existing one untouched, so /week can
    call it unconditionally. Use `revise` to actually change a live week."""
    existing = get_layout(week_start)
    if existing:
        return existing
    return _write(week_start, days, long_run_day, revised=0)


def revise(week_start: str, days: list[DayPlan], long_run_day: str) -> WeekLayout:
    """Mid-week reshuffle under C1. Unlike set_layout this overwrites.

    Deliberately does NOT touch strength.set_fixed_days -- see module
    docstring. Callers logging a revision should record a §6 E1 reason code in
    log/sessions/, which is where deviations live; this module stores plan
    shape, not history.
    """
    existing = get_layout(week_start)
    return _write(week_start, days, long_run_day, revised=(existing.revised + 1 if existing else 0))


def day_for(week_start: str, ddmm: str) -> DayPlan | None:
    layout = get_layout(week_start)
    return layout.day_for(ddmm) if layout else None


# --- date helpers ------------------------------------------------------------------
# _ddmm_to_date mirrors strength.py's. Kept local rather than imported across
# modules so neither owns the other's date convention.


def _ddmm_to_date(s: str, year: int = 2026) -> date:
    day, month = s.split("-")
    return date(year, int(month), int(day))


def _to_ddmm(d: date) -> str:
    return d.strftime("%d-%m")


def week_start_for(d: date) -> str:
    """The DD-MM Monday of the week containing d -- the key everything uses."""
    return _to_ddmm(d - timedelta(days=d.weekday()))


# --- parsing the /week spec string --------------------------------------------------


def parse_day_spec(spec: str) -> tuple[list[DayPlan], str | None]:
    """Parse "DD-MM:mi:type,..." as typed by /week.

    Mirrors cli._parse_day_miles' "DD-MM:mi" shape with a third field. The
    session type is optional and defaults to easy for a running day / rest for
    a 0-mile day, so the quick form "28-07:4,29-07:0" still works.

    Returns (days, long_run_day_or_None) -- the long day is inferred when
    exactly one entry is typed "long", otherwise the caller must supply it.
    """
    days: list[DayPlan] = []
    long_day: str | None = None
    for chunk in (c.strip() for c in spec.split(",") if c.strip()):
        parts = chunk.split(":")
        if len(parts) not in (2, 3):
            raise LayoutError(f"Bad day spec {chunk!r} — expected DD-MM:miles or DD-MM:miles:type")
        day, amount_s = parts[0], parts[1]
        try:
            amount = float(amount_s)
        except ValueError as e:
            raise LayoutError(f"Bad amount {amount_s!r} in {chunk!r}") from e
        session = parts[2].lower() if len(parts) == 3 else ("rest" if amount == 0 else "easy")
        if session == "long":
            if long_day is not None:
                raise LayoutError(f"Two days marked long: {long_day} and {day}")
            long_day = day
        # For a cross day the number is minutes, matching how cross-training is
        # prescribed everywhere else in this project. See DayPlan's docstring.
        if session == "cross":
            days.append(DayPlan(day=day, miles=0.0, session=session, cross_minutes=amount))
        else:
            days.append(DayPlan(day=day, miles=amount, session=session))
    if not days:
        raise LayoutError("Empty day spec")
    return days, long_day


def day_miles(layout: WeekLayout) -> dict[str, float]:
    """The dict shape strength.set_fixed_days/reschedule_missed already take —
    so /week can feed both from one source instead of retyping the week."""
    return {d.day: d.miles for d in layout.days}


# --- rule check --------------------------------------------------------------------


def as_proposed_week(layout: WeekLayout, week_num: int, cross_minutes: float | None = None) -> rules_mod.ProposedWeek:
    """Project a layout onto §6's check shape, so `mc layout` can say whether
    the week as laid out would pass *before* it's committed to.

    cross_minutes defaults to the layout's own cross days; pass a value to
    override (e.g. checking a hypothetical without rewriting the layout).
    """
    long_run = layout.long_run()
    return rules_mod.ProposedWeek(
        week=week_num,
        long_run_mi=long_run.miles if long_run else 0.0,
        run_miles=round(sum(d.miles for d in layout.days if d.is_running), 1),
        run_days=layout.run_days,
        cross_minutes=layout.total_cross_minutes if cross_minutes is None else cross_minutes,
    )
