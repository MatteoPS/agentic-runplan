from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from mc import config as cfg

# --- exceptions -------------------------------------------------------------


class GarminSyncError(Exception):
    """Base for all garmin.py errors. Never swallow into empty data — raise."""


class GarminAuthError(GarminSyncError):
    pass


class GarminRateLimitError(GarminSyncError):
    pass


class GarminConnectionFailedError(GarminSyncError):
    pass


class GarminNotFoundError(GarminSyncError):
    pass


# --- call-volume strategy (see plan §"Call-volume strategy") ----------------

DEFAULT_SINCE_DAYS = 60
MAX_SINCE_DAYS = 150

# Empirically confirmed 28-07-2026 by binary search against the live API (31
# days = 400 "requested date range is too big", 30 days = OK). Undocumented in
# garminconnect and in Garmin's own docs — this is a real API-side limit, not
# a client-library setting. Not in the original spec's assumptions.
BODY_BATTERY_MAX_DAYS = 30

# Deferred optimization (my explicit call, 28-07-2026): all 8 of these are
# fetched daily for now. If Garmin rate-limiting becomes a real problem, only
# TRAINING_READINESS, HRV, SLEEP and STATS are load-bearing for anything the
# rule engine reads (spec §6 C2: HRV baseline, sleep, RHR, self-report) or for
# the daily digest — TRAINING_STATUS, STRESS and MAX_METRICS (VO2max) change
# slowly enough to refresh weekly instead without losing anything the system
# acts on. There's also a free dedup available alongside that: STATS already
# embeds `restingHeartRate`, so the separate RHR_DAY call is redundant and could
# be dropped outright. None of this is built now — revisit only if it proves
# necessary.
WELLNESS_LOOKBACK_DAYS = 7
WELLNESS_METRICS = (
    "training_readiness",
    "training_status",
    "hrv",
    "sleep",
    "rhr",
    "stress",
    "max_metrics",
    "stats",
)

_WELLNESS_JITTER_MIN_S = 0.3
_WELLNESS_JITTER_MAX_S = 0.8


# --- auth / token cache -------------------------------------------------------


_MFA_UNAVAILABLE_MSG = (
    "Garmin wants an MFA code, but there's no terminal to type it into.\n"
    "Run `uv run mc sync` once in an interactive terminal on this machine to "
    "establish a cached token; non-interactive runs work from then on, until "
    "the token expires or another machine's refresh invalidates it."
)


def is_interactive() -> bool:
    """Whether there is a human at a terminal who could answer an MFA prompt.

    Detected rather than declared, because the callers that most need the
    non-interactive path -- a cron job, a cloud session running /daily from
    the phone -- are exactly the ones that won't think to pass a flag. Getting
    this wrong is not a small failure: `input()` on a closed stdin raises
    EOFError from deep inside the login call, which surfaces as an unhandled
    traceback rather than the perfectly good GarminAuthError that already
    exists for this case.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        # ValueError: stdin detached/closed. Either way, nobody's there.
        return False


def _prompt_mfa_interactive() -> str:
    try:
        return input("Garmin MFA code: ").strip()
    except (EOFError, KeyboardInterrupt) as e:
        # Belt and braces: isatty() can be True and still fail to read (stdin
        # closed mid-run, a wrapper that fakes a tty, Ctrl-D at the prompt).
        # Convert to the same clear error rather than a traceback.
        raise GarminAuthError(_MFA_UNAVAILABLE_MSG) from e


def _prompt_mfa_unavailable() -> str:
    raise GarminAuthError(_MFA_UNAVAILABLE_MSG)


def get_client(interactive: bool | None = None) -> Garmin:
    """interactive=None (the default) auto-detects a terminal. Pass an
    explicit bool only to override that."""
    if interactive is None:
        interactive = is_interactive()
    cfg.GARMIN_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    client = Garmin(
        email=cfg.settings.garmin_email,
        password=cfg.settings.garmin_password,
        prompt_mfa=_prompt_mfa_interactive if interactive else _prompt_mfa_unavailable,
        verify_login=True,
    )
    have_creds = bool(cfg.settings.garmin_email and cfg.settings.garmin_password)
    try:
        client.login(tokenstore=str(cfg.GARMIN_TOKENS_DIR))
    except GarminConnectAuthenticationError as e:
        hint = (
            ""
            if have_creds
            else (
                " No cached token was valid and GARMIN_EMAIL/GARMIN_PASSWORD "
                "are not set in .env — set them or run an interactive login first."
            )
        )
        raise GarminAuthError(f"Garmin login failed.{hint} ({e})") from e
    except GarminConnectTooManyRequestsError as e:
        raise GarminRateLimitError(f"Garmin rate-limited the login: {e}") from e
    except GarminConnectConnectionError as e:
        raise GarminConnectionFailedError(
            f"Could not reach Garmin (network error, 4xx, or possibly a "
            f"Cloudflare block surfacing as a plain connection error): {e}"
        ) from e
    return client


def _call(description: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except GarminConnectAuthenticationError as e:
        raise GarminAuthError(f"{description}: 401 — {e}") from e
    except GarminConnectTooManyRequestsError as e:
        raise GarminRateLimitError(f"{description}: 429 — {e}") from e
    except GarminConnectNotFoundError as e:
        # Must precede ConnectConnectionError — NotFoundError subclasses it.
        raise GarminNotFoundError(f"{description}: 404 — {e}") from e
    except GarminConnectConnectionError as e:
        raise GarminConnectionFailedError(
            f"{description}: connection/API error — {e}"
        ) from e


# --- raw-dump helpers ---------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def _envelope(data: Any, *, source: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "data": data,
    }


# --- data pull functions -------------------------------------------------------


def pull_activities(
    client: Garmin, since_days: int, *, force: bool = False
) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=since_days)
    activities = _call(
        f"get_activities_by_date({start},{end})",
        client.get_activities_by_date,
        start.isoformat(),
        end.isoformat(),
    )

    activities_dir = cfg.RAW_GARMIN_DIR / "activities"
    details_dir = activities_dir / "details"
    _write_json(
        activities_dir / f"activities_{start.isoformat()}_{end.isoformat()}.json",
        _envelope(activities, source="get_activities_by_date"),
    )
    _write_json(activities_dir / "latest.json", _envelope(activities, source="get_activities_by_date"))

    enriched: list[dict[str, Any]] = []
    for activity in activities:
        activity_id = str(activity.get("activityId"))
        details_path = details_dir / f"{activity_id}.json"
        splits_path = details_dir / f"{activity_id}_splits.json"

        if force or not details_path.exists():
            details = _call(
                f"get_activity_details({activity_id})",
                client.get_activity_details,
                activity_id,
            )
            _write_json(details_path, _envelope(details, source="get_activity_details"))
        if force or not splits_path.exists():
            splits = _call(
                f"get_activity_splits({activity_id})",
                client.get_activity_splits,
                activity_id,
            )
            _write_json(splits_path, _envelope(splits, source="get_activity_splits"))

        enriched.append(activity)
    return enriched


def pull_daily_wellness(
    client: Garmin, lookback_days: int = WELLNESS_LOOKBACK_DAYS, *, force: bool = False
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    wellness_dir = cfg.RAW_GARMIN_DIR / "wellness"
    results: dict[str, dict[str, Any]] = {m: {} for m in WELLNESS_METRICS}
    gaps: list[tuple[str, str]] = []

    calls: dict[str, Callable[[str], Any]] = {
        "training_readiness": client.get_training_readiness,
        "training_status": client.get_training_status,
        "hrv": client.get_hrv_data,
        "sleep": client.get_sleep_data,
        "rhr": client.get_rhr_day,
        "stress": client.get_stress_data,
        "max_metrics": client.get_max_metrics,
        "stats": client.get_stats,
    }

    for offset in range(lookback_days):
        cdate = (date.today() - timedelta(days=offset)).isoformat()
        for metric, fn in calls.items():
            metric_path = wellness_dir / metric / f"{cdate}.json"
            if not force and metric_path.exists():
                results[metric][cdate] = json.loads(metric_path.read_text())["data"]
                continue
            try:
                data = _call(f"{fn.__name__}({cdate})", fn, cdate)
            except GarminNotFoundError:
                gaps.append((cdate, metric))
                continue
            if data in (None, [], {}):
                gaps.append((cdate, metric))
            results[metric][cdate] = data
            _write_json(metric_path, _envelope(data, source=fn.__name__))
            time.sleep(_jitter())

    return results, gaps


def _jitter() -> float:
    import random

    return random.uniform(_WELLNESS_JITTER_MIN_S, _WELLNESS_JITTER_MAX_S)


def pull_body_battery(client: Garmin, since_days: int) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=since_days)
    data = _call(
        f"get_body_battery({start},{end})",
        client.get_body_battery,
        start.isoformat(),
        end.isoformat(),
    )
    _write_json(
        cfg.RAW_GARMIN_DIR / "body_battery" / "latest.json",
        _envelope(data, source="get_body_battery"),
    )
    return data


def pull_race_predictions(client: Garmin) -> dict[str, Any]:
    data = _call("get_race_predictions()", client.get_race_predictions)
    _write_json(
        cfg.RAW_GARMIN_DIR / "race_predictions" / "latest.json",
        _envelope(data, source="get_race_predictions"),
    )
    return data


def pull_lactate_threshold(client: Garmin) -> dict[str, Any]:
    data = _call(
        "get_lactate_threshold(latest=True)", client.get_lactate_threshold, latest=True
    )
    _write_json(
        cfg.RAW_GARMIN_DIR / "lactate_threshold" / "latest.json",
        _envelope(data, source="get_lactate_threshold"),
    )
    return data


def estimate_call_count(
    since_days: int, wellness_lookback_days: int = WELLNESS_LOOKBACK_DAYS
) -> dict[str, int]:
    """Rough pre-flight estimate of Garmin API calls this sync will make,
    based on what's already cached on disk. Printed before the Garmin portion
    of a sync runs. Engineering judgment, not a documented Garmin threshold —
    the "new activities" count is a heuristic (assumes ~5 sessions/week
    density for days not yet covered by cache), since the real count is only
    known after the list call itself.
    """
    details_dir = cfg.RAW_GARMIN_DIR / "activities" / "details"
    cached_activity_ids: set[str] = set()
    if details_dir.exists():
        cached_activity_ids = {
            p.stem for p in details_dir.glob("*.json") if not p.stem.endswith("_splits")
        }

    approx_activity_density_per_day = 5 / 7
    approx_total_activities = round(since_days * approx_activity_density_per_day)
    approx_new_activities = max(0, approx_total_activities - len(cached_activity_ids))

    hrv_dir = cfg.RAW_GARMIN_DIR / "wellness" / "hrv"
    cached_wellness_days = len(list(hrv_dir.glob("*.json"))) if hrv_dir.exists() else 0

    activities_list_call = 1
    detail_calls = approx_new_activities * 2
    wellness_calls = max(0, wellness_lookback_days - cached_wellness_days) * len(
        WELLNESS_METRICS
    )
    fixed_calls = 3  # body_battery + race_predictions + lactate_threshold
    return {
        "activities_list": activities_list_call,
        "activity_details_est": detail_calls,
        "wellness_est": wellness_calls,
        "fixed": fixed_calls,
        "total_est": activities_list_call + detail_calls + wellness_calls + fixed_calls,
    }


@dataclass
class GarminPullResult:
    activities: list[dict[str, Any]]
    wellness: dict[str, dict[str, Any]]
    body_battery: list[dict[str, Any]] | None
    race_predictions: dict[str, Any] | None
    lactate_threshold: dict[str, Any] | None
    wellness_gaps: list[tuple[str, str]] = field(default_factory=list)
    supplementary_failures: dict[str, str] = field(default_factory=dict)


def sync_garmin(
    since_days: int,
    *,
    wellness_lookback_days: int = WELLNESS_LOOKBACK_DAYS,
    force: bool = False,
    interactive: bool | None = None,
) -> GarminPullResult:
    client = get_client(interactive=interactive)

    # Critical path — needed by the rule engine (§6) and current-fitness
    # computation. A failure here aborts the whole sync and propagates loudly.
    activities = pull_activities(client, since_days, force=force)
    wellness, gaps = pull_daily_wellness(client, wellness_lookback_days, force=force)

    # Supplementary — not referenced by any §6 rule. A failure here (e.g.
    # Garmin's undocumented ~30-day range limit on body battery, discovered
    # 28-07-2026 when a 60-day request 400'd) must not discard the critical
    # data already fetched above. Caught per-call, recorded, sync continues.
    supplementary_failures: dict[str, str] = {}

    body_battery: list[dict[str, Any]] | None = None
    try:
        body_battery = pull_body_battery(client, min(since_days, BODY_BATTERY_MAX_DAYS))
    except GarminSyncError as e:
        supplementary_failures["body_battery"] = str(e)

    race_predictions: dict[str, Any] | None = None
    try:
        race_predictions = pull_race_predictions(client)
    except GarminSyncError as e:
        supplementary_failures["race_predictions"] = str(e)

    lactate_threshold: dict[str, Any] | None = None
    try:
        lactate_threshold = pull_lactate_threshold(client)
    except GarminSyncError as e:
        supplementary_failures["lactate_threshold"] = str(e)

    return GarminPullResult(
        activities=activities,
        wellness=wellness,
        body_battery=body_battery,
        race_predictions=race_predictions,
        lactate_threshold=lactate_threshold,
        wellness_gaps=gaps,
        supplementary_failures=supplementary_failures,
    )
