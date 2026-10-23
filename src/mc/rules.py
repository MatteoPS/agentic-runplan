from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mc import clock
from mc import config as cfg
from mc.equivalence import EASY_PACE_MIN_PER_MI, ELLIPTICAL_TRANSFER
from mc.plan import PlanBlock, PlanLock, PlanWeek

# Fixed dates from the frozen plan (§1, §5 Step 4) — not derived from
# plan.lock.json since the lock file only carries weekly aggregates, not
# specific travel dates.
#
# These anchor B7's easy-only windows, so each is the day the athlete is
# ON THE GROUND, not the day the plane leaves. The distinction only bites
# eastbound: the NYC->MXP leg departs 10-09 and lands 11-09, so B7's window
# is 11-09/12-09/13-09. It was 10-09 here until 07-09-2026, which put the
# window a day early and left Sun 13-09 — the third day off a transatlantic
# flight — unprotected. §6's own text named the departure date as an arrival
# too; both were corrected on explicit approval 07-09-2026, so this constant,
# `instructionforclaudecode.md` §6 B7 and `CLAUDE.md`'s verbatim copy all now
# read 11-09. `context/italy-trip.md` carries the real itinerary.
#
# No practical effect on the plan as routed (week 7's long run is Wed 09-09
# and the travel block carries no quality sessions), but a long run proposed
# for 13-09 used to pass and now correctly does not.
#
# The westbound return lands the same calendar day it departs, so US_RETURN is
# both, and is unchanged. B6 is unaffected either way — it reads the flight
# dates the caller passes in, not these.
ITALY_ARRIVAL = date(2026, 9, 11)
US_RETURN = date(2026, 9, 30)

# A3 protects "the 20-miler" and "the 18" absolutely — derived from the
# week's own data (is_twenty, or a long run >=18mi) rather than hardcoded
# week numbers, so this generalizes across any plan, not just the specific
# frozen one (whose milestones happen to be weeks 6 and 11).
_PROTECTED_LONG_RUN_THRESHOLD_MI = 18.0


def _is_protected(week: PlanWeek) -> bool:
    return week.is_twenty or week.long_run_mi >= _PROTECTED_LONG_RUN_THRESHOLD_MI


REASON_CODES = frozenset(
    {
        "TRAVEL",
        "RACE",
        "ILLNESS",
        "INJURY",
        "SHIN",
        "HAMSTRING",
        "HEAT",
        "WEATHER",
        "LIFE",
        "READINESS",
        "OVERRIDE",
    }
)


# --- shared models -----------------------------------------------------------


class Violation(BaseModel):
    rule_id: str
    category: Literal["A", "B", "C", "D", "E"]
    message: str


class RuleResult(BaseModel):
    allowed: bool
    violations: list[Violation]

    @classmethod
    def from_violations(cls, violations: list[Violation]) -> "RuleResult":
        return cls(allowed=len(violations) == 0, violations=violations)


def _v(rule_id: str, message: str) -> Violation:
    return Violation(rule_id=rule_id, category=rule_id[0], message=message)  # type: ignore[arg-type]


# --- A: immutable (hard reject) ------------------------------------------------


class ProposedWeek(BaseModel):
    week: int
    long_run_mi: float
    run_miles: float
    run_days: int
    cross_minutes: float = 0.0


# --- partial-week rule filtering -----------------------------------------------
# Used wherever a *partial* week has to be judged and no full-week proposal is
# available: `mc push` (one session projected onto actuals-to-date) and
# `mc check`'s degraded tier (no persisted layout to project the rest of the
# week from). Where a layout *does* exist, prefer planning.project_week and
# check the blended week in full — these sets suppress real findings as well
# as false ones, so they are the fallback, never the default.

# A2 (compliance floor), A8/A9 (aerobic-load ratios), A10 (min running days)
# are cumulative, end-of-week metrics — computed against a partial week they
# will ALWAYS look "behind" (day 2 of 7 can never hit a weekly floor by
# definition). What survives is the rules a single session can violate on its
# own at any point in the week: long-run shrink (A1), the protected long run
# (A3), the taper freeze (A4), stepback top-up (A5), the 105% ceiling (A6),
# race date (A7).
PARTIAL_WEEK_BLOCKING_RULE_IDS = frozenset({"A1", "A3", "A4", "A5", "A6", "A7"})

# A1/A3 are specifically about the week's long-run EVENT. ProposedWeek's
# long_run_mi field is "the longest run so far this week" — a fine proxy once
# the week is over, but a false positive before the long run has actually
# happened (a Tuesday easy run in a week whose long run is Sunday will always
# look "short" of the long-run target, which has nothing to do with Tuesday).
# Only enforce these two once the long run is the thing being judged.
LONG_RUN_EVENT_RULE_IDS = frozenset({"A1", "A3"})

# Every A-rule check_week can return, so a degraded check can name exactly
# what it stopped judging rather than leaving the caller to infer it.
ALL_A_RULE_IDS = frozenset({f"A{n}" for n in range(1, 11)})


def _cross_mi_equiv(cross_minutes: float) -> float:
    return cross_minutes / EASY_PACE_MIN_PER_MI * ELLIPTICAL_TRANSFER


def _total_aerobic_mi(proposed: ProposedWeek) -> float:
    return proposed.run_miles + _cross_mi_equiv(proposed.cross_minutes)


_LONG_RUN_TOLERANCE_MI = 0.2

# The week-sum rules (A2, A4, A5, A6, A9) are judged to the nearest half
# mile. Below that a "violation" is arithmetic, not a finding.
#
# A distance is not a precise quantity. An outdoor route is eyeballed to
# avoid a long walk home and often comes out a bit over or under; a
# prescription is now written to the nearest 0.5 mi (layout.QUANTUM_MI) for
# the same reason. Judging the sum of five such numbers against a floor with
# only a float epsilon meant a week 0.05 mi short was a violation -- and
# warnings you dismiss daily are warnings you stop reading, which is the
# failure this whole file exists to avoid.
#
# This is not a relaxation so much as a consistency fix: the codebase had
# already decided the question twice in the other direction, at
# _LONG_RUN_TOLERANCE_MI (0.2 mi on A1/A3, the *strictest* rules here) and at
# drift.DEVIATION_TOLERANCE_MI (a full mile per day, "rounding and GPS
# noise"). A2/A6/A9 were simply the ones nobody had got to.
#
# It cannot hide a missed session: the shortest run anywhere in the plan is
# 3 mi, six times this. A skipped Tuesday still drags the week under the
# floor and A2 still fires -- see planning.project_week.
#
# Applies in the taper too, where compliance_floor is 1.0 and the floor
# therefore *is* the plan (wk12: 28.00 mi exactly). A 28 mi taper week now
# passes at 27.5. That is deliberate: A4 is the rule protecting the taper's
# shape, and it is a ceiling, not a floor. Both confirmed with me
# 14-08-2026.
#
# Deliberately NOT applied to A1/A3. Those judge a single event against a
# locked distance rather than a sum of five, and already carry their own
# tighter tolerance above. By the "half a mile in one run cannot matter"
# principle they would arguably go to 0.5 as well, but A3 is the rule
# protecting the 18 and the 20 and that was not the change asked for.
_WEEK_TOLERANCE_MI = 0.5


def check_week(proposed: ProposedWeek, plan: PlanLock) -> RuleResult:
    week = plan.week_by_number(proposed.week)
    block = plan.block_for(week)
    violations: list[Violation] = []

    # A1 — long run must not shrink, except travel_italy (opportunistic).
    if not block.long_run_opportunistic:
        if proposed.long_run_mi < week.long_run_mi - _LONG_RUN_TOLERANCE_MI:
            violations.append(
                _v(
                    "A1",
                    f"Week {week.week}: long run {proposed.long_run_mi}mi is below "
                    f"the locked {week.long_run_mi}mi and this block isn't opportunistic.",
                )
            )

    # A2 — weekly total >= block's compliance floor.
    floor_miles = block.compliance_floor * week.run_miles
    if proposed.run_miles < floor_miles - _WEEK_TOLERANCE_MI:
        violations.append(
            _v(
                "A2",
                f"Week {week.week}: {proposed.run_miles:.1f}mi is below the "
                f"{block.compliance_floor:.0%} compliance floor ({floor_miles:.1f}mi) "
                f"for block '{week.block}'.",
            )
        )

    # A3 — protected milestone long runs (18mi+, or flagged is_twenty) happen
    # at full distance.
    if _is_protected(week):
        if abs(proposed.long_run_mi - week.long_run_mi) > _LONG_RUN_TOLERANCE_MI:
            violations.append(
                _v(
                    "A3",
                    f"Week {week.week}'s {week.long_run_mi}mi long run is protected — "
                    f"never shortened, split, or moved outside its week.",
                )
            )

    # A4 — taper is frozen: exact match required, no additions.
    if block.frozen:
        if proposed.run_miles > week.run_miles + _WEEK_TOLERANCE_MI:
            violations.append(
                _v(
                    "A4",
                    f"Week {week.week} is in the frozen taper block — no additions, "
                    f"no making up missed volume. Planned {week.run_miles:g}mi, "
                    f"proposed {proposed.run_miles:.1f}mi.",
                )
            )

    # A5 — stepback weeks never topped up.
    if week.is_stepback and proposed.run_miles > week.run_miles + _WEEK_TOLERANCE_MI:
        violations.append(
            _v(
                "A5",
                f"Week {week.week} is a stepback — stays at the planned lower "
                f"{week.run_miles}mi, never topped up.",
            )
        )

    # A6 — no increases beyond 105% of plan.
    ceiling = 1.05 * week.run_miles
    if proposed.run_miles > ceiling + _WEEK_TOLERANCE_MI:
        violations.append(
            _v(
                "A6",
                f"Week {week.week}: {proposed.run_miles:.1f}mi exceeds 105% of plan "
                f"({ceiling:.1f}mi). Feeling great isn't a reason to increase — "
                f"stick to the plan.",
            )
        )

    # A8 — non-running aerobic load <= 35% of total, outside travel.
    if not block.no_gym:
        total = _total_aerobic_mi(proposed)
        if total > 0:
            nonrun_pct = _cross_mi_equiv(proposed.cross_minutes) / total
            if nonrun_pct > 0.35 + 1e-9:
                violations.append(
                    _v(
                        "A8",
                        f"Week {week.week}: non-running load is {nonrun_pct:.0%} of "
                        f"total aerobic load, above the 35% cap.",
                    )
                )

    # A9 — long run <= long_run_ratio_max of total aerobic load.
    # Judged in MILES, not in ratio space: the tolerance is a statement about
    # how precisely a distance can be run, so it has to be applied to a
    # distance. `allowance_mi` is the longest run this week's total permits;
    # the finding is still reported as a percentage because that is how the
    # cap is written.
    total = _total_aerobic_mi(proposed)
    if total > 0:
        allowance_mi = week.long_run_ratio_max * total
        if proposed.long_run_mi > allowance_mi + _WEEK_TOLERANCE_MI:
            ratio = proposed.long_run_mi / total
            violations.append(
                _v(
                    "A9",
                    f"Week {week.week}: long run is {ratio:.0%} of total aerobic load, "
                    f"above the {week.long_run_ratio_max:.0%} cap for this week. "
                    f"Reduce the long run or restore midweek miles — do not just "
                    f"add cross-training to paper over it.",
                )
            )

    # A10 — minimum 3 running days/week, outside travel and taper.
    if not block.no_gym and not block.frozen:
        if proposed.run_days < 3:
            violations.append(
                _v(
                    "A10",
                    f"Week {week.week}: {proposed.run_days} running days is below "
                    f"the minimum of 3 (outside travel/taper).",
                )
            )

    return RuleResult.from_violations(violations)


class WeekBand(BaseModel):
    """The legal range for a week's running miles: A2's floor to A6's ceiling.

    Exists to be *printed*. The hundredths this project used to prescribe were
    the symptom of laying a week out flush against one edge of this band --
    w/c 10-08 was built to hit its 20.9 mi floor almost exactly, so every
    subsequent nudge had to be shaved off a hundredth at a time, eight
    revisions deep. A week laid out mid-band absorbs an eyeballed route
    without anyone having to do arithmetic.

    Reports the strict band, not the tolerance-widened one: _WEEK_TOLERANCE_MI
    is there to stop noise, not to be spent deliberately.
    """

    week: int
    floor_mi: float
    ceiling_mi: float
    plan_mi: float
    ceiling_rule: str  # which rule actually binds the top: A4, A5 or A6

    @property
    def width_mi(self) -> float:
        return round(self.ceiling_mi - self.floor_mi, 1)

    @property
    def midpoint_mi(self) -> float:
        return round((self.floor_mi + self.ceiling_mi) / 2, 1)

    def headroom(self, proposed_mi: float) -> tuple[float, float]:
        """(room below the proposal, room above it) before a rule fires."""
        return (
            round(proposed_mi - self.floor_mi, 1),
            round(self.ceiling_mi - proposed_mi, 1),
        )

    @property
    def is_degenerate(self) -> bool:
        """Floor and ceiling are closer together than the tolerance itself.

        True for the whole taper: compliance_floor is 1.0 there, so A2's floor
        IS the plan value, and A4 caps at that same value. The strict band is
        a single point — wk12 is 28.0-28.0 — which no outdoor week can hit.
        """
        return self.width_mi < _WEEK_TOLERANCE_MI

    @property
    def note(self) -> str:
        if not self.is_degenerate:
            return ""
        return (
            f"A2's floor and {self.ceiling_rule}'s ceiling coincide at "
            f"{self.plan_mi:g} mi — the ±{_WEEK_TOLERANCE_MI:g} mi tolerance is the only "
            f"thing making this week runnable, so treat {self.plan_mi:g} as the target, "
            f"not a threshold to clear."
        )

    def describe(self, proposed_mi: float) -> str:
        below, above = self.headroom(proposed_mi)
        return (
            f"{proposed_mi:.1f} mi · band {self.floor_mi:.1f}-{self.ceiling_mi:.1f} mi "
            f"(A2 floor / {self.ceiling_rule} ceiling) · slack -{below:.1f} / +{above:.1f}"
        )


def week_band(week: PlanWeek, plan: PlanLock) -> WeekBand:
    """The week's legal range, with the *binding* ceiling.

    A6's 105% is not always the top. A frozen taper week (A4) and a stepback
    week (A5) are both capped at the plan value itself, which is tighter --
    and that is not a detail: week 3 is a stepback with a plan of 22 mi, so
    its real band is 20.9-22.0, not the 20.9-23.1 A6 alone would suggest. Its
    layout was set to exactly 22.0, flush against a ceiling nothing was
    printing.
    """
    block = plan.block_for(week)
    ceiling_mi = 1.05 * week.run_miles
    ceiling_rule = "A6"
    if block.frozen:
        ceiling_mi, ceiling_rule = week.run_miles, "A4"
    elif week.is_stepback:
        ceiling_mi, ceiling_rule = week.run_miles, "A5"
    return WeekBand(
        week=week.week,
        floor_mi=round(block.compliance_floor * week.run_miles, 1),
        ceiling_mi=round(ceiling_mi, 1),
        plan_mi=week.run_miles,
        ceiling_rule=ceiling_rule,
    )


def check_race_date(candidate: date, plan: PlanLock) -> RuleResult:
    if candidate != plan.race_date:
        return RuleResult.from_violations(
            [_v("A7", f"Race date is fixed at {plan.race_date} — cannot change to {candidate}.")]
        )
    return RuleResult.from_violations([])


# --- B: long-run shuffling ------------------------------------------------------


class ProposedSchedule(BaseModel):
    week: int
    long_run_date: date
    quality_session_dates: list[date] = []
    running_days: list[date] = []
    prev_long_run_date: date | None = None
    next_long_run_date: date | None = None
    flight_dates: list[tuple[date, float]] = []  # (date, duration_hours)
    pairing_broken_reason: str | None = None


def _in_own_week(d: date, week: PlanWeek) -> bool:
    return week.wc <= d <= week.wc + timedelta(days=6)


def check_schedule(
    proposed: ProposedSchedule,
    plan: PlanLock,
    *,
    crossed_adjacent_week_count_in_block: int = 0,
    five_day_streaks_in_block: int = 0,
) -> RuleResult:
    week = plan.week_by_number(proposed.week)
    violations: list[Violation] = []

    # B1 — soft preference only, not a hard block.
    crosses = not _in_own_week(proposed.long_run_date, week)

    # B2 — >=48h between long run and any quality session, both directions.
    for qd in proposed.quality_session_dates:
        if abs((proposed.long_run_date - qd).days) < 2:
            violations.append(
                _v(
                    "B2",
                    f"Week {week.week}: long run on {proposed.long_run_date} is within "
                    f"48h of a quality session on {qd}.",
                )
            )

    # B3 — consecutive long runs must be 5-10 calendar days apart.
    for other, label in (
        (proposed.prev_long_run_date, "previous"),
        (proposed.next_long_run_date, "next"),
    ):
        if other is not None:
            delta = abs((proposed.long_run_date - other).days)
            if not (5 <= delta <= 10):
                violations.append(
                    _v(
                        "B3",
                        f"Week {week.week}: long run on {proposed.long_run_date} is "
                        f"{delta} day(s) from the {label} week's long run ({other}) — "
                        f"must be 5-10 days apart. This shuffle is rejected outright; "
                        f"solve it another way.",
                    )
                )

    # B4 — crossing into an adjacent week: at most once per 4-week block,
    # and only if B3 (checked above) holds.
    if crosses:
        if crossed_adjacent_week_count_in_block >= 1:
            violations.append(
                _v(
                    "B4",
                    f"Week {week.week}: long run already crossed into an adjacent "
                    f"week once in this 4-week block — cannot do it again.",
                )
            )

    # B6 — no long run within 24h of a flight over 4h, either direction.
    for flight_date, hours in proposed.flight_dates:
        if hours > 4 and abs((proposed.long_run_date - flight_date).days) < 1:
            violations.append(
                _v(
                    "B6",
                    f"Week {week.week}: long run on {proposed.long_run_date} is within "
                    f"24h of a {hours:.0f}h flight on {flight_date}.",
                )
            )

    # B7 — first 3 days after Italy arrival / US return: easy only, no
    # quality, no long run. Not an override — pre-declared in the plan.
    for anchor, label in ((ITALY_ARRIVAL, "arrival in Italy"), (US_RETURN, "return to the US")):
        window = {anchor + timedelta(days=i) for i in range(3)}
        if proposed.long_run_date in window:
            violations.append(
                _v(
                    "B7",
                    f"Week {week.week}: long run on {proposed.long_run_date} falls in "
                    f"the first 3 easy-only days after {label} ({anchor}-{anchor + timedelta(days=2)}).",
                )
            )
        for qd in proposed.quality_session_dates:
            if qd in window:
                violations.append(
                    _v(
                        "B7",
                        f"Week {week.week}: quality session on {qd} falls in the first "
                        f"3 easy-only days after {label}.",
                    )
                )

    # B8 — max 5 consecutive running days, at most once per 4-week block, never 6.
    streak = _longest_streak(proposed.running_days)
    if streak > 5:
        violations.append(
            _v("B8", f"Week {week.week}: {streak} consecutive running days — never more than 5.")
        )
    elif streak == 5 and five_day_streaks_in_block >= 1:
        violations.append(
            _v(
                "B8",
                f"Week {week.week}: a 5-day running streak already happened once in "
                f"this 4-week block — cannot do it again.",
            )
        )

    # B9 — Saturday-pace / Sunday-long pairing preserved, or a stated reason.
    saturday_before = proposed.long_run_date - timedelta(days=1)
    pairing_preserved = saturday_before in proposed.quality_session_dates
    if not pairing_preserved and not proposed.pairing_broken_reason:
        violations.append(
            _v(
                "B9",
                f"Week {week.week}: Saturday-pace/Sunday-long pairing broken with no "
                f"stated reason — must say why if breaking it.",
            )
        )

    return RuleResult.from_violations(violations)


def _longest_streak(days: list[date]) -> int:
    if not days:
        return 0
    ordered = sorted(set(days))
    best = cur = 1
    for prev, nxt in zip(ordered, ordered[1:]):
        if (nxt - prev).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


class LongRunResolution(BaseModel):
    week: int
    resolution: Literal["move", "split", "swap", "reduce"]
    split_ratio: tuple[float, float] | None = None
    split_gap_hours: float | None = None
    reduce_pct: float = 0.0
    reason_code: str | None = None
    swap_week: int | None = None
    swap_week_long_run_mi: float | None = None


def check_long_run_resolution(
    resolution: LongRunResolution, plan: PlanLock, *, splits_used_so_far: int = 0
) -> RuleResult:
    """B5's strict priority order (move -> split -> swap -> reduce) is a
    process constraint on the caller (only escalate if the cheaper option is
    genuinely infeasible) — this validates whichever specific resolution was
    chosen against its own constraints, not that earlier options were tried."""
    week = plan.week_by_number(resolution.week)
    violations: list[Violation] = []
    protected = _is_protected(week)

    if resolution.resolution == "split":
        if protected:
            violations.append(
                _v("B5", f"Week {week.week}: splitting is forbidden for the 18mi/20mi weeks.")
            )
        if splits_used_so_far >= 2:
            violations.append(_v("B5", "Splitting has already been used twice in this plan — max twice, whole plan."))
        if resolution.split_gap_hours is None or resolution.split_gap_hours > 6:
            violations.append(_v("B5", "Split must be same-day, <=6h apart."))
        if resolution.split_ratio is None or sorted(resolution.split_ratio) != sorted((0.6, 0.4)):
            violations.append(_v("B5", "Split must be 60/40."))

    elif resolution.resolution == "swap":
        if resolution.swap_week is None:
            violations.append(_v("B5", "Swap requires a target week."))
        else:
            other = plan.adjacent_week(week.week, resolution.swap_week - week.week)
            if other is None or abs(resolution.swap_week - week.week) != 1:
                violations.append(_v("B5", "Swap must be with an adjacent week."))
            if resolution.swap_week_long_run_mi is not None and resolution.swap_week_long_run_mi > week.long_run_mi:
                violations.append(
                    _v(
                        "B5",
                        "Swap must be with a SHORTER long run — never carry the "
                        "longer one forward into a peak week.",
                    )
                )

    elif resolution.resolution == "reduce":
        if protected:
            violations.append(
                _v("B5", f"Week {week.week}: reducing is forbidden for the 18mi/20mi weeks.")
            )
        if resolution.reduce_pct > 25:
            violations.append(_v("B5", "Reduction may not exceed 25%."))
        if not resolution.reason_code or resolution.reason_code not in REASON_CODES:
            violations.append(_v("B5", "Reduction requires a valid reason code."))

    return RuleResult.from_violations(violations)


# --- C: free to adjust, no approval needed --------------------------------------
# No dedicated check functions — these are permissions, not constraints, so
# there's nothing to reject. Documented here for traceability against §6:
#   C1 reorder easy runs within the week
#   C2 swap an easy run for its cross-equivalent (heat/shin/readiness) — A8
#      still binds, already enforced unconditionally by check_week whenever
#      the resulting week is checked, regardless of why cross_minutes changed
#   C3 adjust easy pace freely
#   C4 add/remove strength and mobility
#   C5 drop a single easy run for travel — A2 still binds, same reasoning as C2
#   C6 choose session time of day freely


# --- D: safety stops -----------------------------------------------------------


class SymptomReport(BaseModel):
    shin_pain: Literal["none", "dull", "sharp", "localized_bone", "worsens_during_run"] = "none"
    shin_pain_free_on_elliptical: bool = True
    gait_altering_pain: bool = False
    posterior_thigh_or_sitbone_pain: bool = False
    recent_self_reports: list[int] = []  # most recent last, 1-10 scale
    fever_or_illness: bool = False


class SafetyResult(BaseModel):
    allow_running: bool
    allow_elliptical: bool
    no_speed: bool = False
    no_hills: bool = False
    no_long_stride: bool = False
    see_professional: bool = False
    propose_recovery_week: bool = False
    messages: list[str] = []


def check_safety(report: SymptomReport) -> SafetyResult:
    result = SafetyResult(allow_running=True, allow_elliptical=True)

    if report.shin_pain in ("sharp", "localized_bone", "worsens_during_run"):
        result.allow_running = False
        result.allow_elliptical = report.shin_pain_free_on_elliptical
        result.see_professional = True
        result.messages.append(
            "D1: shin pain is sharp/bone-localized/worsening — no running today. "
            "This needs a professional; not optimising around it."
        )

    if report.gait_altering_pain:
        result.allow_running = False
        result.messages.append("D2: pain changes your gait — no running plan today.")

    if report.posterior_thigh_or_sitbone_pain:
        result.no_speed = True
        result.no_hills = True
        result.no_long_stride = True
        result.messages.append(
            "D3: posterior thigh/sit-bone pain — possible hamstring tendinopathy signal "
            "given history. No speed, no hills, no long stride."
        )

    if len(report.recent_self_reports) >= 3 and all(s <= 3 for s in report.recent_self_reports[-3:]):
        result.propose_recovery_week = True
        result.messages.append(
            "D4: three consecutive days self-report <=3/10 — propose a recovery "
            "week, flag possible overreaching."
        )

    if report.fever_or_illness:
        result.allow_running = False
        result.messages.append("D5: fever/illness — no running.")

    if result.see_professional or not result.allow_running:
        result.messages.append("D6: not a doctor or physio.")

    return result


# --- E: anti-drift -----------------------------------------------------------


class Override(BaseModel):
    reason_code: str
    detail: str
    logged_at: datetime


_OVERRIDE_RE = re.compile(r"^OVERRIDE:\s*(.+)$")


def parse_override(text: str) -> Override | None:
    """Only ever recognizes a literal typed 'OVERRIDE: <reason>' — never
    assumed from any other phrasing (§6 E4). Deliberately case-sensitive:
    'never assume one' means a lowercase near-miss doesn't count either."""
    m = _OVERRIDE_RE.match(text.strip())
    if not m:
        return None
    detail = m.group(1).strip()
    if not detail:
        return None
    code = next((c for c in REASON_CODES if detail.upper().startswith(c)), "OVERRIDE")
    # Naive on purpose: count_overrides_in_window compares these against
    # naive bounds. What matters is that the wall clock is the athlete's
    # rather than the container's -- an override typed at 21:00 in New York
    # belongs to that day, not to the UTC one that has already started.
    return Override(reason_code=code, detail=detail, logged_at=clock.now().replace(tzinfo=None))


def validate_reason_code(code: str, *, readiness_data_cited: str | None = None) -> RuleResult:
    violations = []
    if code not in REASON_CODES:
        violations.append(_v("E1", f"{code!r} is not in the closed reason-code set."))
    elif code == "READINESS" and not readiness_data_cited:
        violations.append(_v("E1", "READINESS reason code requires cited data."))
    return RuleResult.from_violations(violations)


def append_override(override: Override, path: Path = cfg.OVERRIDES_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"\n- {override.logged_at.isoformat(timespec='seconds')} · {override.reason_code} · {override.detail}\n"
    with path.open("a") as f:
        f.write(line)


def count_overrides_in_window(overrides: list[Override], window_start: datetime, window_end: datetime) -> int:
    return sum(1 for o in overrides if window_start <= o.logged_at <= window_end)


def check_override_drift(overrides_in_block: int) -> RuleResult:
    """E5 — more than 2 overrides in a 4-week block means the plan isn't
    matching real life; propose a structural revision, not more overrides."""
    if overrides_in_block > 2:
        return RuleResult.from_violations(
            [
                _v(
                    "E5",
                    f"{overrides_in_block} overrides in this 4-week block — the plan "
                    f"isn't matching real life. Propose a structural revision for "
                    f"approval, not another override.",
                )
            ]
        )
    return RuleResult.from_violations([])


def check_rolling_compliance(rolling_actual_pct: float, block: PlanBlock) -> RuleResult:
    """E2 — if rolling 3-week actual < the block's compliance floor,
    out/today.md must open with a warning stating the shortfall."""
    if rolling_actual_pct < block.compliance_floor:
        shortfall_pct = block.compliance_floor - rolling_actual_pct
        return RuleResult.from_violations(
            [
                _v(
                    "E2",
                    f"Rolling 3-week compliance {rolling_actual_pct:.0%} is below the "
                    f"{block.compliance_floor:.0%} floor — shortfall of {shortfall_pct:.0%}. "
                    f"This must open today's digest, not be buried.",
                )
            ]
        )
    return RuleResult.from_violations([])
