from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from garminconnect.workout import (
    BaseWorkout,
    ConditionType,
    CyclingWorkout,
    ExecutableStep,
    FitnessEquipmentWorkout,
    RunningWorkout,
    StepType,
    TargetType,
    WorkoutSegment,
)

from mc import config as cfg
from mc import equivalence as eq
from mc import garmin as garmin_mod
from mc import rules as rules_mod
from mc.plan import PlanLock, PlanWeek

MILE_M = 1609.344

WARMUP_SECONDS = 300
COOLDOWN_SECONDS = 300
MIN_MAIN_SECONDS = 60

DEFAULT_HR_LOW = 135
DEFAULT_HR_HIGH = 150

Modality = Literal["run", "elliptical", "bike"]


class PushError(Exception):
    pass


class SessionParseError(Exception):
    pass


# --- target construction ---------------------------------------------------------
# Pace-zone (workoutTargetTypeId=6, "pace.zone") targetValueOne/targetValueTwo
# in METERS PER SECOND — [CONFIRMED] against a real, tested, actively-used
# implementation (github.com/alfranz/garmin-workouts,
# garminworkouts/models/pace.py Pace.to_garmin() / running_workout.py), not
# just garminconnect's own source (which only demonstrates NO_TARGET steps).
#
# HR-zone (workoutTargetTypeId=4, "heart.rate.zone") targetValueOne/
# targetValueTwo in BPM — [INFERENCE]: same field structure as the confirmed
# pace case, sourced from aggregated web research, not independently verified
# against a second primary implementation the way pace was. This is exactly
# why --dry-run (prints the JSON payload, no network) is the path used to
# actually verify this before any real push happens.


def _hr_zone_target(hr_low: int, hr_high: int) -> dict[str, Any]:
    return {
        "targetType": {
            "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
            "workoutTargetTypeKey": "heart.rate.zone",
        },
        "targetValueOne": hr_low,
        "targetValueTwo": hr_high,
    }


def pace_to_mps(pace_min_per_mi: float) -> float:
    return MILE_M / (pace_min_per_mi * 60)


def _fmt_pace(pace_min_per_mi: float) -> str:
    m = int(pace_min_per_mi)
    s = round((pace_min_per_mi - m) * 60)
    return f"{m}:{s:02d}"


def _step(step_order: int, step_type_id: int, step_type_key: str, duration_seconds: float, target: dict[str, Any] | None) -> ExecutableStep:
    data: dict[str, Any] = dict(
        stepOrder=step_order,
        stepType={"stepTypeId": step_type_id, "stepTypeKey": step_type_key, "displayOrder": step_type_id},
        endCondition={
            "conditionTypeId": ConditionType.TIME,
            "conditionTypeKey": "time",
            "displayOrder": 2,
            "displayable": True,
        },
        endConditionValue=duration_seconds,
    )
    if target:
        data["targetType"] = target["targetType"]
        data["targetValueOne"] = target["targetValueOne"]
        data["targetValueTwo"] = target["targetValueTwo"]
    else:
        data["targetType"] = {
            "workoutTargetTypeId": TargetType.NO_TARGET,
            "workoutTargetTypeKey": "no.target",
        }
    return ExecutableStep(**data)


# --- session spec + workout construction ------------------------------------------

# Garmin workout class + sportTypeId/Key per modality. Elliptical has no
# dedicated typed Workout subclass with its own sportTypeId in garminconnect
# — FitnessEquipmentWorkout (sportTypeId=6, "cardio_training") is Garmin's
# general indoor-cardio-machine category and is what elliptical falls under.
_WORKOUT_KINDS: dict[Modality, tuple[type[BaseWorkout], int, str]] = {
    "run": (RunningWorkout, 1, "running"),
    "bike": (CyclingWorkout, 2, "cycling"),
    "elliptical": (FitnessEquipmentWorkout, 6, "cardio_training"),
}

# Only run/bike have a dedicated typed upload_*_workout method on Garmin.
# Elliptical (FitnessEquipmentWorkout) has none — falls back to the generic
# upload_workout(json), which is the same underlying endpoint minus the
# isinstance() convenience check.
_UPLOAD_METHOD_NAME: dict[Modality, str] = {
    "run": "upload_running_workout",
    "bike": "upload_cycling_workout",
}


@dataclass
class SessionSpec:
    session_type: Literal["easy", "pace", "long"]
    modality: Modality = "run"
    distance_mi: float = 0.0
    duration_min: float | None = None  # explicit override — required in practice for elliptical/bike
    hr_low: int = DEFAULT_HR_LOW
    hr_high: int = DEFAULT_HR_HIGH
    pace_min_per_mi: float | None = None  # informational only, run modality only — never a hard target on the long run


def _build_steps(
    duration_s: float,
    warmup_target: dict[str, Any] | None,
    main_target: dict[str, Any] | None,
    cooldown_target: dict[str, Any] | None,
) -> list[ExecutableStep]:
    """A warmup/cooldown split only tells the watch something when its target
    actually differs from the main set's. Today every session is a single
    constant HR band, so the three phases were identical -- three alerts, one
    instruction, and a mid-run "cooldown" banner for a run that was all one
    effort. Collapse to one step whenever the targets match.

    The split path below is deliberately kept rather than deleted: it returns
    the day warmup gets a real target of its own (an easier HR band, or a
    slower pace zone on pace days). This is not an oversight -- it is the
    condition under which the split is meaningful.
    """
    if warmup_target == main_target == cooldown_target:
        return [_step(1, StepType.INTERVAL, "interval", duration_s, main_target)]

    main_s = max(MIN_MAIN_SECONDS, duration_s - WARMUP_SECONDS - COOLDOWN_SECONDS)
    return [
        _step(1, StepType.WARMUP, "warmup", WARMUP_SECONDS, warmup_target),
        _step(2, StepType.INTERVAL, "interval", main_s, main_target),
        _step(3, StepType.COOLDOWN, "cooldown", COOLDOWN_SECONDS, cooldown_target),
    ]


def build_workout(week: PlanWeek, session_date: date, session: SessionSpec, easy_pace_min_per_mi: float) -> BaseWorkout:
    if session.duration_min is not None:
        duration_min = session.duration_min
    else:
        duration_min = session.distance_mi * (session.pace_min_per_mi or easy_pace_min_per_mi)
    duration_s = duration_min * 60

    # Same target for all three phases -- including pace sessions, which today
    # carry no distinct warmup target either. See _build_steps.
    target = _hr_zone_target(session.hr_low, session.hr_high)
    steps = _build_steps(duration_s, target, target, target)

    description = f"HR {session.hr_low}-{session.hr_high}"
    if session.pace_min_per_mi:
        pace_str = f"{_fmt_pace(session.pace_min_per_mi)}/mi"
        description += (
            f" · pace ceiling ~{pace_str} (not a hard target — do not run faster than this on the long run)"
            if session.session_type == "long"
            else f" · ~{pace_str}"
        )

    workout_cls, sport_id, sport_key = _WORKOUT_KINDS[session.modality]
    name_suffix = session.modality if session.modality != "run" else session.session_type
    return workout_cls(
        workoutName=f"MC W{week.week} {session_date.strftime('%d-%m')} {name_suffix}",
        estimatedDurationInSecs=round(duration_s),
        description=description,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType={"sportTypeId": sport_id, "sportTypeKey": sport_key},
                workoutSteps=steps,
            )
        ],
    )


# --- rule check before pushing (§9: "Refuse to push any workout that violates §6") --

# A2 (compliance floor), A8/A9 (aerobic-load ratios), A10 (min running days)
# are cumulative, end-of-week metrics — computed against a partial week they
# will ALWAYS look "behind" (day 2 of 7 can never hit a weekly floor by
# definition), which would block every push early in every week regardless
# of whether today's specific session is actually fine. Hard-blocking a push
# is reserved for rules a single session can violate on its own, at any
# point in the week: the protected long run (A3), the taper freeze (A4),
# stepback top-up (A5), the 105% ceiling (A6), long-run shrink (A1), race
# date (A7). Cumulative status is `mc check`/`mc status`'s job, tracked
# across the week's real execution — not re-litigated at every single push.
_BLOCKING_RULE_IDS = frozenset({"A1", "A3", "A4", "A5", "A6", "A7"})

# A1/A3 are specifically about the week's long-run EVENT. ProposedWeek's
# long_run_mi field is "the longest run so far this week" — a fine proxy
# once the week is over, but a false positive before the long run has
# actually happened (e.g. pushing Tuesday's easy run in a week whose long
# run is scheduled for Sunday will always look "short" of the long-run
# target, which has nothing to do with Tuesday). Only enforce these two when
# the push IS the long run itself.
_LONG_RUN_ONLY_RULE_IDS = frozenset({"A1", "A3"})


def check_before_push(
    session: SessionSpec, week: PlanWeek, actuals: rules_mod.ProposedWeek, plan: PlanLock
) -> rules_mod.RuleResult:
    """Projects this session onto the week's actual-to-date totals and runs
    the same A-rule check `mc check` uses, then keeps only the violations
    that should actually block THIS push (see _BLOCKING_RULE_IDS and
    _LONG_RUN_ONLY_RULE_IDS above). Run sessions count toward run_miles/
    run_days/long_run_mi; elliptical/bike count toward cross_minutes instead
    — pushing a cross-training session must never be misread as running
    volume."""
    if session.modality == "run":
        projected = rules_mod.ProposedWeek(
            week=week.week,
            long_run_mi=max(actuals.long_run_mi, session.distance_mi),
            run_miles=actuals.run_miles + session.distance_mi,
            run_days=actuals.run_days + 1,
            cross_minutes=actuals.cross_minutes,
        )
    else:
        projected = rules_mod.ProposedWeek(
            week=week.week,
            long_run_mi=actuals.long_run_mi,
            run_miles=actuals.run_miles,
            run_days=actuals.run_days,
            cross_minutes=actuals.cross_minutes + (session.duration_min or 0),
        )
    full_result = rules_mod.check_week(projected, plan)
    blocking_ids = _BLOCKING_RULE_IDS if session.session_type == "long" else _BLOCKING_RULE_IDS - _LONG_RUN_ONLY_RULE_IDS
    blocking = [v for v in full_result.violations if v.rule_id in blocking_ids]
    return rules_mod.RuleResult.from_violations(blocking)


# --- data/pushed.json persistence --------------------------------------------------


def _load_pushed() -> dict[str, Any]:
    if not cfg.PUSHED_PATH.exists():
        return {}
    return json.loads(cfg.PUSHED_PATH.read_text())


def _save_pushed(data: dict[str, Any]) -> None:
    cfg.PUSHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.PUSHED_PATH.write_text(json.dumps(data, indent=2))


# --- push / unpush ------------------------------------------------------------------


@dataclass
class PushResult:
    date: str
    workout_id: str | None
    scheduled_workout_id: str | None
    action: Literal["dry_run", "created", "updated"]
    payload: dict[str, Any]
    name: str


def push_workout(
    session_date: date,
    week: PlanWeek,
    session: SessionSpec,
    easy_pace_min_per_mi: float,
    *,
    dry_run: bool = True,
    yes: bool = False,
    interactive: bool = True,
) -> PushResult:
    workout = build_workout(week, session_date, session, easy_pace_min_per_mi)
    payload = workout.to_dict()

    if dry_run:
        return PushResult(
            date=session_date.isoformat(), workout_id=None, scheduled_workout_id=None,
            action="dry_run", payload=payload, name=workout.workoutName,
        )

    if not yes:
        raise PushError(
            "Pushing requires explicit --yes. This writes to your real Garmin "
            "account — use --dry-run first to review the payload."
        )

    client = garmin_mod.get_client(interactive=interactive)
    pushed = _load_pushed()
    key = session_date.isoformat()
    existing = pushed.get(key)

    if existing and existing.get("workout_id"):
        client.update_workout(existing["workout_id"], payload)
        workout_id = existing["workout_id"]
        scheduled_id = existing.get("scheduled_workout_id")
        action: Literal["created", "updated"] = "updated"
    else:
        upload_method_name = _UPLOAD_METHOD_NAME.get(session.modality)
        resp = getattr(client, upload_method_name)(workout) if upload_method_name else client.upload_workout(payload)
        workout_id = str(resp.get("workoutId") or resp.get("workout_id") or "")
        if not workout_id:
            raise PushError(f"Upload succeeded but no workout id found in response: {resp}")
        schedule_resp = client.schedule_workout(workout_id, session_date.isoformat())
        scheduled_id = str(
            schedule_resp.get("workoutScheduleId") or schedule_resp.get("id") or ""
        ) or None
        action = "created"

    pushed[key] = {
        "workout_id": workout_id,
        "scheduled_workout_id": scheduled_id,
        "name": workout.workoutName,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_pushed(pushed)
    return PushResult(
        date=key, workout_id=workout_id, scheduled_workout_id=scheduled_id,
        action=action, payload=payload, name=workout.workoutName,
    )


def unpush_workout(session_date: date, *, interactive: bool = True) -> bool:
    pushed = _load_pushed()
    key = session_date.isoformat()
    entry = pushed.get(key)
    if not entry:
        return False

    client = garmin_mod.get_client(interactive=interactive)
    if entry.get("scheduled_workout_id"):
        client.unschedule_workout(entry["scheduled_workout_id"])
    if entry.get("workout_id"):
        client.delete_workout(entry["workout_id"])

    del pushed[key]
    _save_pushed(pushed)
    return True


# --- deriving a session from out/today.md ------------------------------------------
# plan.lock.json only carries weekly aggregates, not day-of-week prescriptions
# (see plan.md: "day-of-week placement is illustrative, not frozen"). The
# canonical source for "what's actually prescribed on this specific date" is
# out/today.md's "## Today — <session>" line (or, via --option, a row from
# its substitution table), written fresh each day by /daily. mc push
# therefore only knows what to push once /daily has already written that
# day's prescription — it doesn't invent one.
#
# Run sessions are described in miles ("8 mi easy"); cross-training sessions
# in minutes ("60 min @ HR..."). equivalence.parse_session only handles the
# mile case (it's built for "what would this run cost as a substitute"), so
# today.md parsing here detects modality/duration itself rather than
# delegating blindly to it.

_HEADER_DATE_RE = re.compile(r"^#\s*(\d{2}-\d{2})", re.MULTILINE)
_TODAY_LINE_RE = re.compile(r"^##\s*Today\s*—\s*(.+)$", re.MULTILINE)
_HR_RANGE_RE = re.compile(r"HR\s*(\d+)\s*[–-]\s*(\d+)")
_DURATION_MIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*min\b", re.IGNORECASE)
_DISTANCE_MI_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mi(?!n)", re.IGNORECASE)
_MODALITY_KEYWORDS: dict[str, Modality] = {"elliptical": "elliptical", "bike": "bike", "cycling": "bike"}


def _detect_modality(text: str) -> Modality:
    lowered = text.lower()
    for kw, modality in _MODALITY_KEYWORDS.items():
        if kw in lowered:
            return modality
    return "run"


def _detect_session_type(text: str) -> Literal["easy", "pace", "long"]:
    lowered = text.lower()
    if "long" in lowered:
        return "long"
    if "pace" in lowered:
        return "pace"
    return "easy"


def _build_session_spec_from_text(text: str, easy_pace_min_per_mi: float) -> SessionSpec:
    modality = _detect_modality(text)
    session_type = _detect_session_type(text)

    distance_mi = 0.0
    duration_min: float | None = None
    if modality == "run":
        m = _DISTANCE_MI_RE.search(text)
        distance_mi = float(m.group(1)) if m else 0.0
        if distance_mi <= 0:
            raise SessionParseError(f"Could not find a distance in: {text!r}")
    else:
        m = _DURATION_MIN_RE.search(text)
        duration_min = float(m.group(1)) if m else 0.0
        if duration_min <= 0:
            raise SessionParseError(f"Could not find a duration in: {text!r}")

    hr_match = _HR_RANGE_RE.search(text)
    hr_low, hr_high = (int(hr_match.group(1)), int(hr_match.group(2))) if hr_match else (DEFAULT_HR_LOW, DEFAULT_HR_HIGH)

    # No goal marathon pace is established yet (pending the 08-08 5K
    # benchmark) — for a long run, fall back to easy pace as a conservative
    # ceiling proxy (Higdon's own principle: long runs should be *slower*
    # than marathon pace, so easy pace is a safe, if rough, stand-in) rather
    # than pretending a precise ceiling was parsed from the text.
    pace_ceiling = easy_pace_min_per_mi if (modality == "run" and session_type == "long") else None

    return SessionSpec(
        session_type=session_type,
        modality=modality,
        distance_mi=distance_mi,
        duration_min=duration_min,
        hr_low=hr_low,
        hr_high=hr_high,
        pace_min_per_mi=pace_ceiling,
    )


# /preview and /plan mark projected days PROVISIONAL. Those are computed
# under assumed conditions -- normal sleep, no new injury, full compliance --
# none of which have happened yet. Pushing one to the watch would turn an
# assumption into a committed session that tomorrow's digest then measures
# real life against, which is exactly the silent hardening the projection
# design exists to prevent. Refuse rather than trust the caller to notice.
#
# Scoping matters here: /daily appends a "## Next 2 days (provisional)"
# lookahead to out/today.md, and that section is entirely legitimate -- it
# just isn't pushable. So the lookahead section is cut before scanning, and
# only what remains (the day's actual prescription) is checked. A file that
# is provisional *as a whole* -- out/tomorrow.md, which says so above its
# lookahead heading -- still trips the guard.
_PROVISIONAL_RE = re.compile(r"\bprovisional\b", re.IGNORECASE)
_LOOKAHEAD_HEADING_RE = re.compile(r"^##\s+.*\bprovisional\b.*$", re.IGNORECASE | re.MULTILINE)


def _prescription_region(md_text: str) -> str:
    """Everything before the provisional-lookahead section."""
    match = _LOOKAHEAD_HEADING_RE.search(md_text)
    return md_text[: match.start()] if match else md_text


def _check_not_provisional(md_text: str) -> None:
    if _PROVISIONAL_RE.search(_prescription_region(md_text)):
        raise SessionParseError(
            "This session is marked provisional — it's a projection under assumed "
            "conditions, not today's prescription. Run /daily for the real day first."
        )


def _check_today_md_date(md_text: str, expected_date: date) -> None:
    _check_not_provisional(md_text)
    header_match = _HEADER_DATE_RE.search(md_text)
    if not header_match:
        raise SessionParseError("out/today.md has no '# DD-MM · ...' header — can't confirm which day this is for.")
    header_ddmm = header_match.group(1)
    if header_ddmm != expected_date.strftime("%d-%m"):
        raise SessionParseError(
            f"out/today.md is dated {header_ddmm}, not {expected_date.strftime('%d-%m')} — "
            f"regenerate it for the requested date via /daily before pushing."
        )


def parse_session_from_today_md(
    md_text: str, expected_date: date, easy_pace_min_per_mi: float = eq.EASY_PACE_MIN_PER_MI
) -> SessionSpec:
    _check_today_md_date(md_text, expected_date)
    today_match = _TODAY_LINE_RE.search(md_text)
    if not today_match:
        raise SessionParseError("out/today.md has no '## Today — <session>' line.")
    return _build_session_spec_from_text(today_match.group(1), easy_pace_min_per_mi)


def parse_option_from_today_md(
    md_text: str, expected_date: date, option: str, easy_pace_min_per_mi: float = eq.EASY_PACE_MIN_PER_MI
) -> SessionSpec:
    """Selects a specific row from today.md's substitution table by option
    name (e.g. 'bike', 'elliptical') instead of the primary Today
    prescription — lets me push whichever of the day's suggested
    alternatives I actually want on my watch."""
    _check_today_md_date(md_text, expected_date)
    option_lower = option.lower()
    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower() == "option":
            continue
        if option_lower in cells[0].lower():
            return _build_session_spec_from_text(f"{cells[0]} {cells[1]}", easy_pace_min_per_mi)
    raise SessionParseError(f"No option matching {option!r} found in out/today.md's substitution table.")
