"""In-run carbohydrate planning for long runs (added 05-08-2026, C4).

The gap this fills came out of the 2025 NYC marathon (02-11-2025, 4:48:58).
Working back from what was actually eaten — 5-6 gels over 4h49 — gives about
**27 g of carbohydrate per hour**, roughly a third of what a marathon of that
duration needs. The failure signature matches: HR steady and unremarkable,
breathing fine, but stride length collapsing 12% from mile 19 while cadence
*rose*. That is an empty tank, not an aerobic ceiling.

Nothing in this system tracked fuelling at all, which made the single most
likely cause of that race's 17-minute positive split the one variable nobody
was measuring.

**Why a ramp rather than a target.** Carbohydrate absorption is trainable and
the gut is the thing being trained: going from 43 g/hr (measured 05-08-2026)
straight to race rate reliably buys GI distress instead of adaptation. So the
target climbs across the plan, and every long run is a rehearsal of the next
step rather than of race day.

**Why 25 g per unit.** A GU gel is 22 g of carbohydrate, a Maurten Gel 100 is
25 g, both around 100 kcal. Close enough that one interval covers both, and
quoting the interval in minutes is what actually gets followed mid-run.

**Carbohydrate and hydration are two jobs, not one.** Confirmed 05-08-2026
that the 12.5mi long run carried a Liquid I.V. stick in 500 ml — which is an
electrolyte product at ~11 g carbohydrate, so it did the sodium job and
contributed about half a gel toward the carbohydrate one. Keeping the two
lines separate is what stops an hour's sodium from being mistaken for an
hour's fuel. Note also that the two have different *timing*: a gel is a bolus
and waits for `FIRST_GEL_AT_MIN`, while drink carbohydrate is sipped
continuously from the start.

**Above ~60 g/hr the source matters.** A single sugar saturates one intestinal
transporter (SGLT1) at roughly that rate no matter how much is swallowed;
past it, products need mixed glucose and fructose to recruit a second one.
Maurten, GU and honey-based chews are all already mixed, so this is a
constraint on what to buy, not on what to do.

**Not a §6 rule and not medical advice (D6).** Nothing here gates a session or
feeds `check_week`. It is a prompt attached to the runs long enough to need
one, and `HEAT`/`READINESS`-style reason codes are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

from mc.equivalence import EASY_PACE_MIN_PER_MI

# Below this a run finishes before in-run fuelling changes anything, and a
# prompt that fires on every easy day is one that stops being read. 75 minutes
# is about 8 miles at this athlete's easy pace.
MIN_FUEL_DURATION_MIN = 75.0

# Carbohydrate per gel, in grams. Maurten Gel 100 is 25 g; GU is 22 g.
GRAMS_PER_GEL = 25.0

# An electrolyte tab is **not** a fuel product, and conflating the two is the
# easy mistake here: a Liquid I.V. stick is ~11 g carbohydrate and ~500 mg
# sodium, so it covers most of an hour's sodium and about half a gel's carbs.
# Carried as a constant so the digest can say what a stick is actually worth
# rather than leaving it to be assumed either way.
ELECTROLYTE_TAB_CARB_G = 11
ELECTROLYTE_TAB_SODIUM_MG = 500

# Fluid and sodium are a separate job from carbohydrate and are ranges, not
# targets: both depend on sweat rate, which this system does not measure. Wide
# on purpose, and stated as something to test rather than to hit.
FLUID_ML_PER_HR = (400, 800)
SODIUM_MG_PER_HR = (300, 600)

# What the athlete will actually carry: 2 x 250 ml bottles on a belt, confirmed
# 05-08-2026, with an explicit preference for not carrying more. Planning
# against real capacity rather than an ideal one is the difference between a
# plan that gets followed and one that gets abandoned at mile 6 -- Central Park
# fountains make refilling the right answer here rather than a bigger vest.
BELT_CAPACITY_ML = 500

# Grams of carbohydrate a 500 ml bottle holds at the concentration the
# high-carb mixes are designed for (Maurten Drink Mix 320, SiS Beta Fuel and
# Precision Fuel PF90 are all 80-90 g per 500 ml). Ordinary mixes are half
# this; a plain electrolyte tab is ~11 g and is not a fuel product at all.
CARB_MIX_G_PER_500ML = 80

# Don't start the clock at the gun -- the first 30-40 minutes run on what was
# eaten beforehand, and an early gel is one more chance for the stomach to
# object with the whole run still ahead.
FIRST_GEL_AT_MIN = 35.0

# Grams/hour by plan week. Measured baseline was 43 g/hr on the 12.5mi of
# 05-08-2026 (2 GU + 1 pack of chews, ~83 g over 1h57), itself already well up
# from the race's 27. The ramp holds flat through the Italy block (weeks 8-9):
# that block is opportunistic by design and travel is the wrong place to
# introduce a new GI stressor, the same reasoning that puts B7's easy days
# after each flight. Week 11 is the 20-miler and the one full dress rehearsal
# available -- A4 freezes the taper, so nothing new can be tried after it.
FUEL_RAMP_G_PER_HR = {
    1: 50,
    2: 50,
    3: 55,
    4: 60,
    5: 60,
    6: 65,
    7: 65,
    8: 65,
    9: 65,
    10: 70,
    11: 80,
    12: 80,
    13: 80,
    14: 80,
}
RACE_TARGET_G_PER_HR = 80


@dataclass(frozen=True)
class FuelPlan:
    distance_mi: float
    duration_min: float
    target_g_per_hr: int
    total_grams: int
    gel_every_min: int
    n_gels: int
    is_dress_rehearsal: bool

    @property
    def grams_from_gels(self) -> int:
        return round(self.n_gels * GRAMS_PER_GEL)

    @property
    def grams_from_drink(self) -> int:
        """The shortfall gels don't cover, which is where drink mix comes in.

        Rounding the interval to something followable (nearest 5 min) always
        leaves a gap at the higher targets, and pretending otherwise would put
        a number in the digest that the schedule beneath it doesn't deliver.
        """
        return max(self.total_grams - self.grams_from_gels, 0)

    @property
    def refills(self) -> int:
        """Fountain stops implied by belt capacity at the mid fluid rate.

        Counts the *stops*, not the bottles: the belt leaves home full, so a run
        needing 1500 ml needs two refills, not three.
        """
        mid_ml_per_hr = sum(FLUID_ML_PER_HR) / 2
        needed_ml = mid_ml_per_hr * self.duration_min / 60
        return max(int(-(-needed_ml // BELT_CAPACITY_ML)) - 1, 0)

    @property
    def carbs_from_bottles(self) -> int:
        """Carbohydrate the belt can actually deliver across the run.

        Counts **one** of the two bottles as carb mix, because the other holds
        water and electrolyte — assuming both would contradict the split this
        module recommends, and would mean drinking a 16% solution with no water
        alongside it for three hours. Re-dosed from a sachet at every refill,
        so the ceiling is per-fill capacity times fills, not one bottleful.
        """
        per_fill = CARB_MIX_G_PER_500ML * (BELT_CAPACITY_ML / 2) / 500
        return round((self.refills + 1) * per_fill)

    @property
    def liquid_only_is_enough(self) -> bool:
        """Whether drink alone reaches the target. When False the gap is gels,
        and saying so now beats discovering it at mile 14."""
        return self.carbs_from_bottles >= self.total_grams

    @property
    def gel_gap_g(self) -> int:
        return max(self.total_grams - self.carbs_from_bottles, 0)

    @property
    def summary(self) -> str:
        return (
            f"{self.total_grams} g carbohydrate over ~{self.duration_min / 60:.1f} h "
            f"({self.target_g_per_hr} g/hr) — a gel every {self.gel_every_min} min "
            f"from {FIRST_GEL_AT_MIN:.0f} min, about {self.n_gels} in total."
        )


def target_for_week(week_num: int) -> int:
    """Grams/hour this week's long run should rehearse."""
    if week_num in FUEL_RAMP_G_PER_HR:
        return FUEL_RAMP_G_PER_HR[week_num]
    return RACE_TARGET_G_PER_HR


def needs_fuelling(distance_mi: float, pace_min_per_mi: float = EASY_PACE_MIN_PER_MI) -> bool:
    return distance_mi * pace_min_per_mi >= MIN_FUEL_DURATION_MIN


def build_plan(
    distance_mi: float,
    week_num: int,
    pace_min_per_mi: float = EASY_PACE_MIN_PER_MI,
) -> FuelPlan | None:
    """The fuelling rehearsal for one session, or None if it's too short to need one."""
    duration_min = distance_mi * pace_min_per_mi
    if duration_min < MIN_FUEL_DURATION_MIN:
        return None

    target = target_for_week(week_num)
    hours = duration_min / 60
    total_grams = round(target * hours)
    gels_per_hour = target / GRAMS_PER_GEL
    gel_every_min = round(60 / gels_per_hour / 5) * 5  # to the nearest 5 min, to be followable

    # Count what actually fits after the opening window rather than dividing the
    # whole run: the first gel is deliberately late, so the naive count is high.
    fuelling_window = max(duration_min - FIRST_GEL_AT_MIN, 0)
    n_gels = int(fuelling_window // gel_every_min) + 1

    return FuelPlan(
        distance_mi=distance_mi,
        duration_min=duration_min,
        target_g_per_hr=target,
        total_grams=total_grams,
        gel_every_min=gel_every_min,
        n_gels=n_gels,
        is_dress_rehearsal=week_num == 11,
    )


def plan_lines(plan: FuelPlan | None) -> list[str]:
    """Markdown bullets for `out/today.md`. Empty when there's nothing to say."""
    if plan is None:
        return []

    lines = [
        f"**Carbohydrate — {plan.target_g_per_hr} g/hr, {plan.total_grams} g over "
        f"~{plan.duration_min / 60:.1f} h.**",
        f"- One ~100 kcal gel (GU 22 g / Maurten 25 g) **every "
        f"{plan.gel_every_min} min, first at {FIRST_GEL_AT_MIN:.0f} min** — a gel "
        f"is a bolus, so the opening half hour runs on breakfast. About "
        f"{plan.n_gels} in total ({plan.grams_from_gels} g).",
    ]
    if plan.grams_from_drink:
        lines.append(
            f"- The remaining **~{plan.grams_from_drink} g from carbohydrate drink "
            f"mix** (Maurten Drink Mix, SIS Beta Fuel, Precision Fuel, Tailwind, "
            f"Skratch) — **sipped continuously from the start**, unlike the gels. "
            f"Gels on a followable interval don't reach the target alone, and "
            f"carrying more of them isn't the answer."
        )
    else:
        lines.append(
            "- Carbohydrate drink mix counts toward the same number, sipped from "
            "the start, and is easier on the stomach than another gel."
        )
    lines += [
        "**Fluid & sodium — a separate job from the number above.**",
        f"- {FLUID_ML_PER_HR[0]}-{FLUID_ML_PER_HR[1]} ml/hr and "
        f"{SODIUM_MG_PER_HR[0]}-{SODIUM_MG_PER_HR[1]} mg sodium/hr — wide ranges, "
        f"because sweat rate isn't measured here. Toward the top in heat and at a "
        f"high dew point.",
        f"- **An electrolyte tab is hydration, not fuel.** A Liquid I.V. stick is "
        f"~{ELECTROLYTE_TAB_CARB_G} g carbohydrate and ~{ELECTROLYTE_TAB_SODIUM_MG} "
        f"mg sodium: most of an hour's sodium, and about half a gel. It counts "
        f"toward the sodium line, not the carbohydrate one.",
        f"**Carry — {BELT_CAPACITY_ML} ml on the belt, ~{plan.refills} fountain "
        f"refill(s).**",
        f"- One bottle carbohydrate mix, one bottle water with an electrolyte "
        f"tab. Re-dose the carb bottle from a sachet at each refill — powder "
        f"weighs nothing, which is the whole reason this works on a belt.",
    ]
    if not plan.liquid_only_is_enough:
        lines.append(
            f"- **Liquid alone won't reach {plan.total_grams} g here.** Re-dosed "
            f"at every refill the carb bottle delivers about "
            f"{plan.carbs_from_bottles} g, leaving **~{plan.gel_gap_g} g "
            f"(~{round(plan.gel_gap_g / GRAMS_PER_GEL)} gels)** to carry. The "
            f"run is simply longer than 250 ml at a time can fuel."
        )
    else:
        lines.append(
            f"- At this distance the carb bottle can cover all "
            f"{plan.total_grams} g on its own (~{plan.carbs_from_bottles} g "
            f"available) if you'd rather skip gels — provided every refill gets "
            f"re-dosed. Gels stay the simpler option; this is the choice, not a "
            f"recommendation."
        )
    lines += [
        "- Eat 2-3 h beforehand, not 20 min. Log what you actually took and how "
        "the stomach handled it — that's the point of doing it now.",
    ]
    if plan.target_g_per_hr > 60:
        lines.append(
            "- Above 60 g/hr needs mixed glucose + fructose to clear a second "
            "intestinal transporter. Maurten, GU and honey-based chews all "
            "qualify; a single-sugar product will not, however much you take."
        )
    if plan.is_dress_rehearsal:
        lines.append(
            "- **This is the dress rehearsal.** A4 freezes the taper, so this is "
            "the last long run that can test race-day fuelling before race day."
        )
    return lines
