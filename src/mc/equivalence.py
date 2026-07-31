from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Sourced from context/equivalence.md (§4 research, step 5). Canonical home
# for these constants — rules.py imports from here rather than duplicating.
EASY_PACE_MIN_PER_MI = 9.75  # step 4's real HR-pace fit (~HR140-145 zone)

ELLIPTICAL_TRANSFER_RANGE = (0.85, 0.95)
ELLIPTICAL_TRANSFER = 0.90  # midpoint, used for point estimates
BIKE_TRANSFER_RANGE = (0.70, 0.85)
BIKE_TRANSFER = 0.775  # midpoint
TREADMILL_TRANSFER = 1.00
TREADMILL_MAX_MINUTES = 45  # my own logistical constraint, not research

NONRUNNING_CAP_PCT = 0.35  # A8

# Fixed vocabulary (§4) — never invent new verdict strings.
VERDICT_GOOD = "✅ good substitute"
VERDICT_AEROBIC_ONLY = "⚠️ aerobic only"
VERDICT_NOT_RECOMMENDED = "❌ not recommended"
VERDICT_NOT_A_SUBSTITUTE = "❌ not a substitute"

# Verdict thresholds on equivalent_pct are my own inference, not sourced --
# the research (context/equivalence.md) gives transfer-rate ranges per
# modality, not verdict cutoffs. 80%/60% is a reasonable, simple split;
# flagging it as a judgment call rather than presenting it as evidence-based.
_GOOD_THRESHOLD = 0.80
_AEROBIC_ONLY_THRESHOLD = 0.60


@dataclass
class SubstitutionOption:
    option: str
    duration: str
    duration_min: float
    equivalent_pct: float | None
    verdict: str
    lost: str


@dataclass
class PrescribedSession:
    session_type: Literal["easy", "pace", "long"]
    distance_mi: float
    pace_min_per_mi: float = EASY_PACE_MIN_PER_MI

    @property
    def duration_min(self) -> float:
        return self.distance_mi * self.pace_min_per_mi


_DISTANCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mi(?!n)", re.IGNORECASE)  # (?!n) excludes "min"


def parse_session(text: str, pace_min_per_mi: float = EASY_PACE_MIN_PER_MI) -> PrescribedSession:
    m = _DISTANCE_RE.search(text)
    distance = float(m.group(1)) if m else 0.0
    lowered = text.lower()
    session_type: Literal["easy", "pace", "long"] = "easy"
    if "long" in lowered:
        session_type = "long"
    elif "pace" in lowered:
        session_type = "pace"
    return PrescribedSession(session_type=session_type, distance_mi=distance, pace_min_per_mi=pace_min_per_mi)


def _verdict(equivalent_pct: float) -> str:
    if equivalent_pct >= _GOOD_THRESHOLD:
        return VERDICT_GOOD
    if equivalent_pct >= _AEROBIC_ONLY_THRESHOLD:
        return VERDICT_AEROBIC_ONLY
    return VERDICT_NOT_RECOMMENDED


def build_substitution_table(session: PrescribedSession) -> list[SubstitutionOption]:
    """Match by time at matched effort, never machine distance (§4 §1).
    For a non-long session, cross-training options are shown at the SAME
    clock duration as the prescribed run — equivalent_pct then equals the
    modality's transfer rate directly, which is the honest number: a
    same-duration elliptical session delivers ~90% of the aerobic dose, not
    100%, because per-minute transfer is <100%. Long runs never get a table
    (context/equivalence.md §5: no substitute exists)."""
    if session.session_type == "long":
        return [
            SubstitutionOption(
                option="—",
                duration="—",
                duration_min=0,
                equivalent_pct=None,
                verdict=VERDICT_NOT_A_SUBSTITUTE,
                lost=(
                    "the entire long-run stimulus — musculoskeletal fatigue resistance, "
                    "fueling practice, duration-dependent adaptation. No substitute exists "
                    "(context/equivalence.md). Never offered, regardless of duration or effort."
                ),
            )
        ]

    prescribed_min = session.duration_min
    options: list[SubstitutionOption] = []

    ellip_min = round(prescribed_min)
    options.append(
        SubstitutionOption(
            option="Elliptical",
            duration=f"{ellip_min} min @ matched easy HR",
            duration_min=ellip_min,
            equivalent_pct=ELLIPTICAL_TRANSFER,
            verdict=_verdict(ELLIPTICAL_TRANSFER),
            lost="impact/tendon/eccentric-loading adaptation (near-zero transfer)",
        )
    )

    bike_min = round(prescribed_min)
    options.append(
        SubstitutionOption(
            option="Bike",
            duration=f"{bike_min} min @ matched easy HR",
            duration_min=bike_min,
            equivalent_pct=BIKE_TRANSFER,
            verdict=_verdict(BIKE_TRANSFER),
            lost="impact/tendon adaptation, and lower musculoskeletal transfer than elliptical",
        )
    )

    combo_ellip_min = round(prescribed_min * 0.55)
    combo_bike_min = round(prescribed_min * 0.45)
    combo_total = combo_ellip_min + combo_bike_min
    combo_pct = (
        combo_ellip_min * ELLIPTICAL_TRANSFER + combo_bike_min * BIKE_TRANSFER
    ) / combo_total if combo_total else 0.0
    options.append(
        SubstitutionOption(
            option=f"Ellip {combo_ellip_min} + bike {combo_bike_min}",
            duration=f"{combo_total} min",
            duration_min=combo_total,
            equivalent_pct=combo_pct,
            verdict=_verdict(combo_pct),
            lost="impact/tendon adaptation (both modalities), somewhat mitigated by the elliptical share",
        )
    )

    treadmill_min = round(prescribed_min)
    if treadmill_min > TREADMILL_MAX_MINUTES:
        options.append(
            SubstitutionOption(
                option="Treadmill",
                duration=f"{session.distance_mi:g} mi ≈ {treadmill_min} min",
                duration_min=treadmill_min,
                equivalent_pct=TREADMILL_TRANSFER,
                verdict=VERDICT_NOT_RECOMMENDED,
                lost=f"nothing physiologically — it's running — but exceeds the {TREADMILL_MAX_MINUTES} min limit",
            )
        )
    else:
        options.append(
            SubstitutionOption(
                option="Treadmill",
                duration=f"{session.distance_mi:g} mi ≈ {treadmill_min} min",
                duration_min=treadmill_min,
                equivalent_pct=TREADMILL_TRANSFER,
                verdict=VERDICT_GOOD,
                lost="nothing — it's running",
            )
        )

    return options


def summary_line(option: SubstitutionOption, substitutions_used_this_week: int) -> str:
    """§4: 'Always state the percentage AND what specifically is lost.'"""
    pct_str = f"{option.equivalent_pct:.0%}" if option.equivalent_pct is not None else "n/a"
    return f"{pct_str} aerobic, lost: {option.lost} — substitutions used this week: {substitutions_used_this_week}"


# --- strength & mobility (§4, researched context/equivalence.md §9) ------------


@dataclass
class StrengthMobilityItem:
    name: str
    protocol: str
    source: str
    minutes: int
    bodyweight_only: bool = True


SHIN_ITEMS = [
    StrengthMobilityItem(
        name="Single-leg calf raises",
        protocol="3x15, 2s pause at top (progress toward 3x20-25 pain-free)",
        source="Runners Connect / Galbraith & Lavallee 2009",
        minutes=4,
    ),
    StrengthMobilityItem(
        name="Tibialis raises (wall-supported)",
        protocol="3x15-20, lean back against wall, lift toes/forefoot, lower under control",
        source="PNEUX tibialis anterior guide",
        minutes=4,
    ),
]

# Progressive-overload tiers for the two fixed shin lifts (added 29-07-2026 at
# my request, after I flagged load-dependent tibial tenderness that's
# never crossed into D1 territory). Static reps stop adapting bone/tendon
# after a few weeks -- tempo/load is the progression variable, not rep count.
# Advances every WEEKS_PER_TIER weeks via mc.strength.tier_for_week.
CALF_RAISE_TIERS = [
    StrengthMobilityItem(
        name="Single-leg calf raises",
        protocol="3x15, 2s pause at top",
        source="Runners Connect / Galbraith & Lavallee 2009",
        minutes=4,
    ),
    StrengthMobilityItem(
        name="Single-leg calf raises, slow eccentric",
        protocol="3x12, 3-4s lowering each rep -- tendon-stiffness stimulus, not rep count",
        source="Runners Connect / Galbraith & Lavallee 2009",
        minutes=4,
    ),
    StrengthMobilityItem(
        name="Single-leg calf raises, weighted",
        protocol="3x10, slow eccentric, add load (dumbbell/backpack) once bodyweight eccentric is easy",
        source="Runners Connect / Galbraith & Lavallee 2009",
        minutes=5,
    ),
]

TIBIALIS_RAISE_TIERS = [
    StrengthMobilityItem(
        name="Tibialis raises (wall-supported, bodyweight)",
        protocol="3x15-20, lean back against wall, lift toes/forefoot, lower under control",
        source="PNEUX tibialis anterior guide",
        minutes=4,
    ),
    StrengthMobilityItem(
        name="Tibialis raises (light band around forefoot)",
        protocol="3x15-20, add light resistance once bodyweight is easy for all sets",
        source="PNEUX tibialis anterior guide",
        minutes=4,
    ),
    StrengthMobilityItem(
        name="Tibialis raises (weighted, plate/dumbbell on foot)",
        protocol="3x12-15, slow eccentric, seated or wall-supported",
        source="PNEUX tibialis anterior guide",
        minutes=5,
    ),
]

HAMSTRING_SAFE_ITEMS = [
    StrengthMobilityItem(
        name="Double-leg glute bridge",
        protocol="3x15, minimal hip flexion",
        source="E3 Rehab proximal hamstring tendinopathy rehab",
        minutes=3,
    ),
    StrengthMobilityItem(
        name="Single-leg glute bridge",
        protocol="3x15/side, minimal hip flexion",
        source="E3 Rehab proximal hamstring tendinopathy rehab",
        minutes=4,
    ),
]

MOBILITY_ITEMS = [
    StrengthMobilityItem(
        name="Calf stretch (gastroc + soleus)",
        protocol="30s x3 each, knee straight then bent",
        source="Runners Connect shin splint guide",
        minutes=3,
    ),
    StrengthMobilityItem(
        name="Ankle circles / dorsiflexion rocks",
        protocol="10 each direction per side",
        source="Standard practitioner practice (convention, not a specific study)",
        minutes=2,
    ),
]

# Exercises deliberately NOT included: RDL/deadlift variations, Roman chair
# hip extensions, long-lever bridges -- E3 Rehab's own staging categorizes
# these as moderate-to-significant hip flexion, which the athlete profile
# flags as the hamstring aggravator. See context/equivalence.md §9 for why
# this is a conservative inference, not a hard rule from the source itself.


def propose_strength_mobility(
    *, target_minutes: int = 15
) -> list[StrengthMobilityItem]:
    """Short bodyweight session for cross/rest days or shin/hamstring
    downgrades. All items here are bodyweight-only by construction, so this
    always satisfies the no-gym-in-Italy requirement without special-casing."""
    picks: list[StrengthMobilityItem] = []
    remaining = target_minutes
    for pool in (SHIN_ITEMS, HAMSTRING_SAFE_ITEMS, MOBILITY_ITEMS):
        for item in pool:
            if item.minutes <= remaining:
                picks.append(item)
                remaining -= item.minutes
    return picks
