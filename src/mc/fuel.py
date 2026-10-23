"""In-run carbohydrate planning for long runs (added 05-08-2026, C4).

The gap this fills came out of the 2025 NYC marathon (02-11-2025, 4:48:58).
Working back from what was actually eaten — 5-6 gels over 4h49 — gives about
**27 g of carbohydrate per hour**, roughly a third of what a marathon of that
duration needs. The failure signature is more equivocal than it first looked:
HR steady and unremarkable, breathing fine, but stride length collapsing 12%
from mile 19 while cadence *rose*. Low fuel is one reading; localised
eccentric quad damage from the course's descents is another, and the quiet HR
points at the second at least as strongly as the first (see
`context/downhill.md`, which exists for that reason). Both are addressed, and
they are addressed separately — this module is not the whole answer to mile
19.

Nothing in this system tracked fuelling at all, which made one of the two most
likely causes of that race's 17-minute positive split a variable nobody was
measuring.

**The cadence is the input; g/hr is the output** (inverted 17-08-2026). This
module used to work the other way round: pick a g/hr target from the ramp,
divide by gel size, round the interval to something followable. That produced
arithmetically correct schedules nobody would run — 5 gels inside a 13-miler,
intervals that moved week to week, and a mental subtraction at mile 8 to work
out whether it had been 25 minutes yet. So the schedule is now **fixed**: a
gel every `GEL_EVERY_MIN`, first one at 40 minutes on a normal breakfast, and
the delivered rate is whatever that comes to. `FUEL_RAMP_G_PER_HR` survives as
the **reference** the fixed cadence is measured against, not as a target the
schedule is solved for. Where the two diverge the plan says so
(`shortfall_vs_reference`) rather than quietly re-tuning the gel count.

**Why 25 g per unit.** A GU gel is 22 g of carbohydrate, a Maurten Gel 100 is
25 g, both around 100 kcal. Close enough that one interval covers both, and
quoting the interval in minutes is what actually gets followed mid-run.

**Gels are the trained default; drink is the top-up.** Confirmed 05-08-2026,
and the reason is specificity rather than preference. On race day 500 ml of
belt capacity cannot fuel four hours, so the intake will be gels plus whatever
the course hands over — which makes a bolus every 20 minutes the thing the
stomach has to tolerate. Training predominantly on sipped carbohydrate would
adapt the gut to a delivery pattern race day won't use. The carry maths below
therefore reports what the bottle *could* cover, but the plan never leans on
it: liquid closes the gap gels leave, not the other way round.

**Carbohydrate and hydration are two jobs, not one.** Confirmed 05-08-2026
that the 12.5mi long run carried a Liquid I.V. stick in 500 ml — which is an
electrolyte product at ~11 g carbohydrate, so it did the sodium job and
contributed about half a gel toward the carbohydrate one. Keeping the two
lines separate is what stops an hour's sodium from being mistaken for an
hour's fuel. Note also that the two have different *timing*: a gel is a bolus
and waits for the first-gel offset, while drink carbohydrate is sipped
continuously from the start.

**Above ~60 g/hr the source matters.** A single sugar saturates one intestinal
transporter (SGLT1) at roughly that rate no matter how much is swallowed;
past it, products need mixed glucose and fructose to recruit a second one.
Maurten, GU and honey-based chews are all already mixed, so this is a
constraint on what to buy, not on what to do.

**Not a §6 rule and not medical advice (D6).** Nothing here gates a session or
feeds `check_week`. It is a prompt attached to the runs long enough to need
one, and `HEAT`/`READINESS`-style reason codes are unaffected.

The settled protocol and the reasoning behind each choice live in
`context/fueling.md`, which is read by `/daily` and `/week`; this module is
its executable half.
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

# **The fixed cadence** (confirmed 17-08-2026). One gel every 20 minutes, every
# long run, race included. Not derived from the week's target any more: a
# schedule that changes week to week is one that gets counted wrong mid-run,
# and 20 minutes is both the interval race day will use and the one that needs
# no arithmetic on the move.
GEL_EVERY_MIN = 20

# When the first gel lands. On a real breakfast the opening 40 minutes run on
# it, and an early gel is one more chance for the stomach to object with the
# whole run still ahead. Without breakfast there is nothing to run on, so the
# clock starts at 20 and the same interval carries on from there — deliberately
# *not* some third offset, because the point of this design is that there is
# only one number to remember.
FIRST_GEL_FED_MIN = 40.0
FIRST_GEL_FASTED_MIN = 20.0

# Three sessions take the fasted offset even on a good breakfast: week 6's 18,
# week 11's 20 (the dress rehearsal) and race day. These are the runs long
# enough that the denser schedule is worth the extra gels, and race day is the
# reason — A4 freezes the taper, so a cadence untested by week 11 cannot be
# introduced on 01-11. Gated on distance as well as week so that a long run
# shortened by a reshuffle drops back to the ordinary offset: the denser start
# was chosen for the 18 and the 20 specifically, not for whatever week 6 ends
# up holding.
DENSE_START_WEEKS = frozenset({6, 11, 14})
DENSE_START_MIN_MI = 18.0

# One packet of carbohydrate drink mix, sipped from the start, on the longer
# runs only. Carried as a whole packet rather than a computed gram figure
# because that is how it is bought and how it goes into the bottle — the old
# code printed a "~23 g from drink mix" shortfall that no packet size actually
# matches.
#
# Product: Maurten Drink Mix 160, confirmed 17-08-2026 -- not the 320, and the
# reason is concentration, not size. The carb bottle is 250 ml (half the belt),
# not the 500 ml Maurten designs around. A 160 packet (40 g/500 ml as sold, 8%)
# in 250 ml lands at 16% -- which is exactly Maurten's own 320 formula (80 g/
# 500 ml), a concentration they already sell and elite marathoners already run
# on. A 320 packet in the same 250 ml would double that to 32%, nothing Maurten
# validates -- the class of hypertonic mix that pulls water into the gut rather
# than delivering it, i.e. the GI-distress mechanism, not a minor tweak.
LIQUID_PACKET_CARB_G = 40
LIQUID_PACKET_MIN_MI = 14.0

# Italy (weeks 8-9) runs on gels alone — a 6-pack bought locally covers both
# long runs, and drink mix is one more thing to source abroad for two sessions
# that are opportunistic by design. Same instinct as B7 and as the flat stretch
# in the ramp below: travel is the wrong place to add a variable.
NO_LIQUID_WEEKS = frozenset({8, 9})

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

# A divergence worth printing. Below this the fixed cadence and the reference
# ramp are close enough that reporting the gap would be noise; at or above it
# the schedule is genuinely delivering less than the plan designed for, and
# E3's "never soften the framing" applies to fuelling as much as to mileage.
MATERIAL_SHORTFALL_G_PER_HR = 10

# Grams/hour by plan week — the **reference** ramp, not a target the schedule
# solves for (see the module docstring). Measured baseline was 43 g/hr on the
# 12.5mi of 05-08-2026 (2 GU + 1 pack of chews, ~83 g over 1h57), itself
# already well up from the race's 27. The ramp holds flat through the Italy
# block (weeks 8-9): that block is opportunistic by design and travel is the
# wrong place to introduce a new GI stressor, the same reasoning that puts B7's
# easy days after each flight. Week 11 is the 20-miler and the one full dress
# rehearsal available -- A4 freezes the taper, so nothing new can be tried
# after it.
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
    reference_g_per_hr: int
    gel_every_min: int
    first_gel_at_min: float
    n_gels: int
    liquid_packets: int
    fasted: bool
    is_dress_rehearsal: bool

    @property
    def grams_from_gels(self) -> int:
        return round(self.n_gels * GRAMS_PER_GEL)

    @property
    def grams_from_liquid(self) -> int:
        return self.liquid_packets * LIQUID_PACKET_CARB_G

    @property
    def total_grams(self) -> int:
        """What the schedule actually delivers — an outcome, not a target."""
        return self.grams_from_gels + self.grams_from_liquid

    @property
    def delivered_g_per_hr(self) -> int:
        return round(self.total_grams / (self.duration_min / 60))

    @property
    def shortfall_vs_reference(self) -> int:
        """How far under the designed ramp the fixed cadence lands, in g/hr.

        Zero when it meets or beats it, which it does on most weeks. Reported
        rather than corrected: the cadence is the thing that has to be
        sustainable, and re-tuning the gel count to hit a rounder number would
        undo the decision this module now encodes.
        """
        return max(self.reference_g_per_hr - self.delivered_g_per_hr, 0)

    @property
    def shortfall_is_material(self) -> bool:
        return self.shortfall_vs_reference >= MATERIAL_SHORTFALL_G_PER_HR

    @property
    def gel_times_min(self) -> list[int]:
        """Every minute mark a gel is due, so the schedule can be read off."""
        return [
            int(self.first_gel_at_min + i * self.gel_every_min) for i in range(self.n_gels)
        ]

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
    def carb_g_per_fill(self) -> int:
        """Carbohydrate one fill of the carb bottle holds — half the belt at mix
        concentration, since the other half is water."""
        return round(CARB_MIX_G_PER_500ML * (BELT_CAPACITY_ML / 2) / 500)

    @property
    def carbs_from_bottles(self) -> int:
        """Carbohydrate the belt can actually deliver across the run.

        Counts **one** of the two bottles as carb mix, because the other holds
        water and electrolyte — assuming both would contradict the split this
        module recommends, and would mean drinking a 16% solution with no water
        alongside it for three hours. Re-dosed from a sachet at every refill,
        so the ceiling is per-fill capacity times fills, not one bottleful.
        """
        return (self.refills + 1) * self.carb_g_per_fill

    @property
    def carb_sachets(self) -> int:
        """Sachets of drink mix to pack — which is `liquid_packets`, i.e. one on
        a run at or over 14 mi and none otherwise.

        This deliberately does **not** re-dose at every fountain stop. An
        earlier version returned `refills + 1` on the reasoning that the carb
        bottle gets topped up each time, which is coherent but describes a
        different plan from the one that was actually chosen: one packet per
        long run, gels carrying the rest. Packing three sachets for a 20-miler
        because the belt gets refilled three times would quietly reintroduce
        the drink-led fuelling the 17-08-2026 decision moved away from. Refills
        are water and an electrolyte tab; the carb mix goes in once, at the
        start.
        """
        return self.liquid_packets

    @property
    def electrolyte_tabs(self) -> int:
        """Tabs for the water bottle, one per fill.

        Unlike the carb sachets this *is* per-fill: it is the hydration line,
        which the fixed-cadence decision did not touch, and a tab is re-dosed
        every time the water bottle is refilled.
        """
        return self.refills + 1

    @property
    def liquid_only_is_enough(self) -> bool:
        """Whether drink alone could reach the delivered total. When False the
        gap is gels, and saying so now beats discovering it at mile 14."""
        return self.carbs_from_bottles >= self.total_grams

    @property
    def gel_gap_g(self) -> int:
        return max(self.total_grams - self.carbs_from_bottles, 0)

    @property
    def summary(self) -> str:
        liquid = (
            f" plus {self.liquid_packets} packet of drink mix"
            if self.liquid_packets
            else ", gels only"
        )
        return (
            f"{self.n_gels} gels every {self.gel_every_min} min from "
            f"{self.first_gel_at_min:.0f} min{liquid} — {self.total_grams} g over "
            f"~{self.duration_min / 60:.1f} h, about {self.delivered_g_per_hr} g/hr."
        )


def target_for_week(week_num: int) -> int:
    """The reference g/hr for this week — what the ramp designed for.

    Kept as the yardstick the fixed cadence is reported against. It no longer
    determines the schedule; see the module docstring.
    """
    if week_num in FUEL_RAMP_G_PER_HR:
        return FUEL_RAMP_G_PER_HR[week_num]
    return RACE_TARGET_G_PER_HR


def needs_fuelling(distance_mi: float, pace_min_per_mi: float = EASY_PACE_MIN_PER_MI) -> bool:
    return distance_mi * pace_min_per_mi >= MIN_FUEL_DURATION_MIN


def first_gel_at(distance_mi: float, week_num: int, fasted: bool = False) -> float:
    """When the first gel lands: 40 min fed, 20 min fasted or on the big three."""
    if fasted:
        return FIRST_GEL_FASTED_MIN
    if week_num in DENSE_START_WEEKS and distance_mi >= DENSE_START_MIN_MI:
        return FIRST_GEL_FASTED_MIN
    return FIRST_GEL_FED_MIN


def liquid_packets_for(distance_mi: float, week_num: int) -> int:
    """One packet on runs >= 14 mi, none in Italy where a 6-pack of gels covers it."""
    if week_num in NO_LIQUID_WEEKS:
        return 0
    return 1 if distance_mi >= LIQUID_PACKET_MIN_MI else 0


def build_plan(
    distance_mi: float,
    week_num: int,
    pace_min_per_mi: float = EASY_PACE_MIN_PER_MI,
    fasted: bool = False,
) -> FuelPlan | None:
    """The fuelling schedule for one session, or None if it's too short to need one."""
    duration_min = distance_mi * pace_min_per_mi
    if duration_min < MIN_FUEL_DURATION_MIN:
        return None

    start = first_gel_at(distance_mi, week_num, fasted=fasted)

    # Count what actually fits after the opening window rather than dividing the
    # whole run: the first gel is deliberately late, so the naive count is high.
    fuelling_window = max(duration_min - start, 0)
    n_gels = int(fuelling_window // GEL_EVERY_MIN) + 1

    return FuelPlan(
        distance_mi=distance_mi,
        duration_min=duration_min,
        reference_g_per_hr=target_for_week(week_num),
        gel_every_min=GEL_EVERY_MIN,
        first_gel_at_min=start,
        n_gels=n_gels,
        liquid_packets=liquid_packets_for(distance_mi, week_num),
        fasted=fasted,
        is_dress_rehearsal=week_num == 11,
    )


def plan_lines(plan: FuelPlan | None) -> list[str]:
    """Markdown bullets for `out/today.md`. Empty when there's nothing to say."""
    if plan is None:
        return []

    if plan.fasted:
        breakfast = "no real breakfast, so the clock starts at the gun"
    elif plan.first_gel_at_min == FIRST_GEL_FASTED_MIN:
        breakfast = (
            "breakfast 2-3 h beforehand, and the early start is deliberate — this "
            "is one of the three sessions that rehearse race day's denser schedule"
        )
    else:
        # Explains the offset only. The meal-timing *instruction* lives in
        # prep_lines, which is the reading that can still be acted on.
        breakfast = "breakfast carries the opening stretch"
    lines = [
        f"**Carbohydrate — {plan.n_gels} gels, {plan.total_grams} g over "
        f"~{plan.duration_min / 60:.1f} h (~{plan.delivered_g_per_hr} g/hr).**",
        f"- One ~100 kcal gel (GU 22 g / Maurten 25 g) **every "
        f"{plan.gel_every_min} min, first at {plan.first_gel_at_min:.0f} min** — "
        f"{breakfast}. {plan.n_gels} in total ({plan.grams_from_gels} g).",
        f"- Due at: {', '.join(f'{t} min' for t in plan.gel_times_min)}.",
    ]
    if plan.liquid_packets:
        lines.append(
            f"- **{plan.liquid_packets} packet of carbohydrate drink mix** "
            f"(~{plan.grams_from_liquid} g — Maurten Drink Mix, SIS Beta Fuel, "
            f"Precision Fuel, Tailwind, Skratch) in the carb bottle, **sipped "
            f"continuously from the start**, unlike the gels. Runs at or over "
            f"{LIQUID_PACKET_MIN_MI:g} mi only."
        )
    elif plan.distance_mi >= LIQUID_PACKET_MIN_MI:
        lines.append(
            "- **No drink mix this week** — Italy runs on gels alone, from a "
            "6-pack bought locally. One less thing to source abroad for two "
            "sessions that are opportunistic by design."
        )
    else:
        lines.append(
            f"- **No drink mix** — under {LIQUID_PACKET_MIN_MI:g} mi the gels "
            f"carry it alone. Water and an electrolyte tab still ride along; "
            f"that is hydration, not fuel."
        )
    if plan.shortfall_is_material:
        lines.append(
            f"- Worth stating plainly: this delivers ~{plan.delivered_g_per_hr} g/hr "
            f"against the ramp's {plan.reference_g_per_hr} g/hr for this week — "
            f"{plan.shortfall_vs_reference} g/hr under. The fixed cadence is the "
            f"decision and it stands; the gap is reported, not corrected by "
            f"squeezing in another gel."
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
        "- One bottle carbohydrate mix, one bottle water with an electrolyte "
        "tab. Re-dose the carb bottle from a sachet at each refill — powder "
        "weighs nothing, which is the whole reason this works on a belt.",
        f"- **Gels carry the session, drink tops it up** — race day is "
        f"gel-dominant, so training a gut on sipped carbohydrate trains the "
        f"wrong thing. The bottle could deliver ~{plan.carbs_from_bottles} g "
        f"here; use it for the balance, not the bulk.",
        "- Log what you actually took and how the stomach handled it — that's "
        "the point of doing it now.",
    ]
    if plan.delivered_g_per_hr > 60:
        lines.append(
            "- Above 60 g/hr needs mixed glucose + fructose to clear a second "
            "intestinal transporter. Maurten, GU and honey-based chews all "
            "qualify; a single-sugar product will not, however much you take."
        )
    if plan.is_dress_rehearsal:
        lines.append(
            "- **This is the dress rehearsal.** A4 freezes the taper, so this is "
            "the last long run that can test race-day fuelling before race day — "
            "and it runs the same 20-min-from-20-min schedule race day will."
        )
    return lines


def prep_lines(plan: FuelPlan | None) -> list[str]:
    """What has to exist *before* the run, as opposed to what happens during it.

    Split out from `plan_lines` (added 17-08-2026) because the two are read at
    different moments and only one of them can still be acted on. The in-run
    schedule is a 6am reminder; the count of gels is a question that has to be
    answered the night before, when there is still time to notice there are two
    in the drawer and the run needs six. `/preview` prints this alone — that is
    the command whose whole job is "what do I need to have done by morning" —
    and `/daily` prints it above the schedule.

    Counts, never inventory: this system does not know what is in the cupboard,
    so it says what the run needs and leaves the comparison to me.
    """
    if plan is None:
        return []

    sachet_part = (
        f"{plan.carb_sachets} sachet of carb mix, " if plan.carb_sachets else "no carb mix, "
    )
    lines = [
        f"**Have ready — {plan.n_gels} gel{'s' if plan.n_gels != 1 else ''}, "
        f"{sachet_part}{plan.electrolyte_tabs} electrolyte "
        f"tab{'s' if plan.electrolyte_tabs != 1 else ''}.**",
        f"- {plan.n_gels} gels is {plan.grams_from_gels} g of the "
        f"{plan.total_grams} g this run delivers. Count them out rather than "
        f"trusting the drawer — short by two is a decision made at mile 14, not "
        f"at the start.",
    ]
    if plan.carb_sachets:
        lines.append(
            f"- Bottles: one sachet (~{plan.grams_from_liquid} g) in 250 ml, 250 ml "
            f"water + a tab. The mix goes in **once, at the start** — the "
            f"{plan.refills} fountain stop(s) are water and a fresh tab, not more "
            f"carb. {plan.electrolyte_tabs - 1} spare tab(s) to carry; they weigh "
            f"nothing, which is the whole reason this works on a belt."
        )
    else:
        lines.append(
            f"- Bottles: both water, {plan.electrolyte_tabs} tab(s) across the "
            f"{plan.refills} fountain stop(s). No carb mix on this one — under "
            f"{LIQUID_PACKET_MIN_MI:g} mi, or Italy, where the gels cover it alone."
        )
    breakfast_note = (
        # Already on the early offset, so skipping breakfast changes nothing
        # about the schedule -- saying "one more gel" here would be wrong.
        "the first gel is at 20 min either way on this one, so breakfast changes "
        "how the opening feels rather than what to pack"
        if plan.first_gel_at_min == FIRST_GEL_FASTED_MIN
        else f"it is also what sets the first gel at {plan.first_gel_at_min:.0f} "
        f"min — no real breakfast means `--fasted`, and one more gel"
    )
    lines.append(
        f"- Pack the belt the night before. Eat 2-3 h beforehand, not 20 min — "
        f"that is what decides the alarm, and {breakfast_note}."
    )
    if plan.delivered_g_per_hr > 60:
        lines.append(
            f"- Buying, not doing: at ~{plan.delivered_g_per_hr} g/hr the product "
            f"has to be mixed glucose + fructose (Maurten, GU, honey-based chews). "
            f"A single-sugar gel will not clear, however many you carry."
        )
    if plan.n_gels > 6:
        lines.append(
            f"- {plan.n_gels} gels is past what a belt carries comfortably — a "
            f"refillable flask is the same product in less bulk."
        )
    return lines
