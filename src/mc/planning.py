"""Multi-day lookahead: the deterministic skeleton behind /plan and /preview.

This module emits **facts only** -- dates, planned miles, session types, which
days are fixed strength days, what the week's rule status is. The judgement
(should today's easy run become an elliptical because your shins are at 2 and
it's 31C?) stays in the slash command, where the day's real answers live. That
split is deliberate: the parts that must be reproducible are code, and the
parts that require reading a person are not.

The one idea this module exists to enforce is `Basis`.

Day 1 is ACTUAL: it can be computed against real sleep, HRV, RHR and
yesterday's real session. Days 2+ are PROJECTED: they assume normal sleep,
full compliance with the days before them, and no new injury. Those
assumptions are frequently wrong -- that is not a flaw, it is what makes a
3-day view cheap. The failure mode to prevent is a projection quietly
hardening into a commitment: getting pushed to the watch, or logged as a
proposal that tomorrow's digest then compares actuals against. So every
projected day carries its basis explicitly, and the consumers
(`mc push`, `mc propose`) refuse projected input rather than trusting the
caller to remember.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from mc import digest as digest_mod
from mc import layout as layout_mod
from mc import rules as rules_mod
from mc import strength as strength_mod
from mc.plan import PlanLock, PlanWeek

# Printed verbatim by /plan and /preview. Stated every time, never implied --
# a projection whose assumptions are invisible reads as a forecast.
PROJECTION_ASSUMPTIONS = (
    "normal sleep",
    "full compliance with the days before it",
    "no new injury or shin escalation",
    "readiness unchanged from today",
)


class Basis(str, Enum):
    ACTUAL = "actual"
    PROJECTED = "projected"


@dataclass(frozen=True)
class PlannedDay:
    date: date
    ddmm: str
    week_num: int
    week_start: str
    miles: float
    session: str
    basis: Basis
    is_long_run: bool = False
    is_fixed_strength: bool = False
    layout_known: bool = True  # False => derived from weekly aggregates, not a real layout

    @property
    def is_provisional(self) -> bool:
        return self.basis is Basis.PROJECTED


@dataclass(frozen=True)
class Lookahead:
    days: list[PlannedDay]
    week_check: rules_mod.RuleResult | None
    missing_layout_weeks: list[str]

    @property
    def provisional_days(self) -> list[PlannedDay]:
        return [d for d in self.days if d.is_provisional]


def _week_for_date(plan: PlanLock, d: date) -> PlanWeek | None:
    """PlanLock.week_for_date raises past the end of the plan; a lookahead
    that runs off the final taper week should simply stop, not explode."""
    try:
        return plan.week_for_date(d)
    except KeyError:
        return None


def _fallback_day(week: PlanWeek, d: date, week_start: str, basis: Basis) -> PlannedDay:
    """No persisted layout for this week yet (e.g. /week hasn't run).

    Rather than invent a day-of-week placement -- which would be a guess
    presented as a plan, and could contradict whatever /week later decides --
    emit the day with the week's average running mileage and an explicit
    layout_known=False so the caller must say "layout not set for this week".
    """
    per_running_day = round(week.run_miles / week.run_days, 1) if week.run_days else 0.0
    return PlannedDay(
        date=d,
        ddmm=d.strftime("%d-%m"),
        week_num=week.week,
        week_start=week_start,
        miles=per_running_day,
        session="easy",
        basis=basis,
        is_long_run=False,
        is_fixed_strength=False,
        layout_known=False,
    )


def lookahead(plan: PlanLock, start: date, days: int = 3) -> Lookahead:
    """`days` calendar days from `start` inclusive. Day 1 is ACTUAL, the rest
    PROJECTED."""
    if days < 1:
        raise ValueError("days must be >= 1")

    planned: list[PlannedDay] = []
    missing: list[str] = []

    for offset in range(days):
        d = start + timedelta(days=offset)
        basis = Basis.ACTUAL if offset == 0 else Basis.PROJECTED
        week = _week_for_date(plan, d)
        if week is None:
            continue  # past the end of the plan — say nothing rather than extrapolate
        week_start = layout_mod.week_start_for(d)
        wl = layout_mod.get_layout(week_start)
        if wl is None:
            if week_start not in missing:
                missing.append(week_start)
            planned.append(_fallback_day(week, d, week_start, basis))
            continue

        ddmm = d.strftime("%d-%m")
        day_plan = wl.day_for(ddmm)
        if day_plan is None:
            planned.append(_fallback_day(week, d, week_start, basis))
            continue

        fixed = set(strength_mod.get_fixed_days(week_start) or [])
        planned.append(
            PlannedDay(
                date=d,
                ddmm=ddmm,
                week_num=week.week,
                week_start=week_start,
                miles=day_plan.miles,
                session=day_plan.session,
                basis=basis,
                is_long_run=(ddmm == wl.long_run_day),
                is_fixed_strength=(ddmm in fixed),
                layout_known=True,
            )
        )

    # Rule status of the *starting* week as laid out. A lookahead spanning two
    # weeks checks only the first: the second week's layout is a separate
    # /week decision, and pre-judging it here would imply more certainty than
    # a projection has.
    check = None
    start_week = _week_for_date(plan, start)
    start_layout = layout_mod.get_layout(layout_mod.week_start_for(start))
    if start_week and start_layout:
        check = rules_mod.check_week(layout_mod.as_proposed_week(start_layout, start_week.week), plan)

    return Lookahead(days=planned, week_check=check, missing_layout_weeks=missing)


def format_assumptions() -> str:
    return "Assumes: " + ", ".join(PROJECTION_ASSUMPTIONS) + "."


# --- the blended week ---------------------------------------------------------------
# §6's A-rules are whole-week metrics: A2's floor is a fraction of the week's
# planned miles, A10 wants 3 running days, A1/A3 want the long run to have
# happened. Checking actuals-so-far against them is a category error -- on a
# build week (floor 0.95) A2 *cannot* pass before roughly Saturday, so every
# mid-week `mc check` reported violations that were arithmetic rather than
# findings. Warnings you dismiss daily are warnings you stop reading.
#
# So we check the week that is actually being proposed: days already elapsed at
# what happened, days still ahead at what the persisted layout says. That is a
# real proposal -- "if I finish the week as laid out, does it pass?" -- and it
# stays honest, because a skipped Tuesday drags the projection under the floor
# and A2 fires for real. The remedy for a real finding is `mc layout --revise`
# (C1, no approval needed), not an override.


@dataclass(frozen=True)
class WeekProjection:
    """Actuals for elapsed days + layout for the days still ahead."""

    proposed: rules_mod.ProposedWeek
    banked_miles: float  # elapsed days, actual
    remaining_miles: float  # days ahead, per layout
    elapsed_days: list[str]  # DD-MM
    remaining_days: list[str]  # DD-MM

    @property
    def long_run_done(self) -> bool:
        return self.proposed.long_run_mi > 0 and not self.remaining_days


def project_week(
    week: PlanWeek,
    layout: layout_mod.WeekLayout,
    day_actuals: dict[str, digest_mod.DayActuals],
    as_of: date,
) -> WeekProjection:
    """Blend a week's actuals with its remaining layout into one ProposedWeek.

    Per day: anything before `as_of` counts what actually happened (0.0 when
    nothing was logged -- a miss is real and should show). `as_of` and later
    count the layout, *unless* that day already has a logged activity, in
    which case actuals win. That last clause matters twice: /preview runs in
    the evening after the session, and a day run longer than planned should
    count what was run rather than what was intended.
    """
    banked = remaining = 0.0
    cross = 0.0
    elapsed: list[str] = []
    ahead: list[str] = []
    run_days = 0
    longest_actual = 0.0
    planned_long_ahead = 0.0

    for day in layout.days:
        actual = day_actuals.get(day.day)
        is_past = _ddmm_before(day.day, as_of)
        use_actual = actual is not None or is_past

        if use_actual:
            miles = actual.run_miles if actual else 0.0
            banked += miles
            elapsed.append(day.day)
            cross += actual.cross_minutes if actual else 0.0
            if actual:
                longest_actual = max(longest_actual, actual.longest_run_mi)
                if actual.ran:
                    run_days += 1
        else:
            remaining += day.miles
            ahead.append(day.day)
            cross += day.cross_minutes
            if day.is_running and day.miles > 0:
                run_days += 1
            if day.day == layout.long_run_day:
                planned_long_ahead = day.miles

    # A1/A3 ask whether the week's long run happens at its planned distance.
    # Once its day is behind us and it did not, the shortfall is the finding --
    # so the layout's figure only counts while that day is still ahead.
    long_run_mi = max(longest_actual, planned_long_ahead)

    return WeekProjection(
        proposed=rules_mod.ProposedWeek(
            week=week.week,
            long_run_mi=round(long_run_mi, 2),
            run_miles=round(banked + remaining, 2),
            run_days=run_days,
            cross_minutes=round(cross, 2),
        ),
        banked_miles=round(banked, 2),
        remaining_miles=round(remaining, 2),
        elapsed_days=elapsed,
        remaining_days=ahead,
    )


def _ddmm_before(ddmm: str, as_of: date) -> bool:
    day, month = ddmm.split("-")
    return date(as_of.year, int(month), int(day)) < as_of
