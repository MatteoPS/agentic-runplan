"""Ambient weather — past and forecast — from Open-Meteo.

Why this exists: two decisions in this system have been running on guesswork.

- §6 **C2** permits swapping an easy run for its cross-equivalent when
  "forecast heat is high". Nothing here could say what the forecast was, so
  that trigger has only ever fired on self-report — while the neighbouring
  triggers (HRV, sleep, RHR) demand cited numbers.
- **`/preview`'s** entire reason for existing is the question "early alarm and
  run outside, or indoors any time?" — asked the night before, answered
  without a temperature.

Open-Meteo was chosen for three properties, in this order: **no API key** (no
new credential to keep out of two repos), **one call** covers both recent past
and forecast via `past_days`, and it is a different provider from Garmin, so
none of this competes for Garmin's rate budget. One HTTP call per `mc sync`.

**This module emits facts, never the call.** It returns temperatures, dew
points and ranked windows; whether that means "set an alarm" or "take the
elliptical" is a judgement made in `/daily` and `/preview`, the same split
`planning.py` draws for projections. Nothing in `rules.py` imports this —
§6 C2 is a permission, not a constraint, and heat data is input to a decision
a human makes, not a rule that fires on its own.

## What leaves the machine

One coordinate pair, rounded to 2 decimal places, to `api.open-meteo.com`.
Nothing else — no identity, no activity data, no history. The rounding is not
a token gesture: Open-Meteo snaps every request to its own model grid anyway
(a 40.7986/-73.9660 request comes back resolved to 40.78858/-73.9661), so
finer coordinates buy literally nothing while describing a doorstep instead of
a neighbourhood. 2dp is ~1.1 km, comfortably inside one grid cell.

Location comes from `MC_WEATHER_LAT`/`MC_WEATHER_LON` when set, otherwise from
the most recent GPS-bearing activity in the Garmin cache — which means it
follows the athlete to Italy in weeks 8-9 without being told. Whichever was
used is printed every time, never assumed. With neither, weather is simply
off: no location, no call, no error.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from mc import config as cfg

BASE_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation_probability",
    "precipitation",
    "wind_speed_10m",
)

# See the module docstring: finer than this is discarded by Open-Meteo's own
# grid, so sending it would leak precision for no forecast benefit.
COORD_PRECISION = 2

DEFAULT_PAST_DAYS = 1
DEFAULT_FORECAST_DAYS = 3

# A GPS fix older than this is a poor guess at "where am I now" — after two
# weeks of treadmill or elliptical, fall back to the configured location and
# say so rather than quietly forecasting for a city already left behind.
LOCATION_MAX_AGE_DAYS = 14

# Forecasts age faster than training data. `/daily` and `/preview` both run
# `mc sync` first so this is normally minutes old; the threshold exists to
# catch the run that used `--source garmin` or worked from a cold cache.
STALE_HOURS = 12

_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5
_TIMEOUT_S = 20.0


class WeatherError(Exception):
    """Base for weather failures. Never swallowed into a plausible-looking
    forecast — a missing number must read as missing (§7)."""


class WeatherConnectionError(WeatherError):
    pass


class WeatherServerError(WeatherError):
    pass


# --- units ---------------------------------------------------------------------
#
# Fahrenheit is the canonical internal unit: every threshold below is stated in
# °F once, and Celsius is a display-time conversion. The alternative — fetching
# in whichever unit is configured — would make every comparison in this file
# depend on an env var, which is exactly the kind of quiet unit bug this
# project's "miles, always, never km" rule exists to prevent.


def temp_unit() -> str:
    """`fahrenheit` (default) or `celsius`, from MC_TEMP_UNIT.

    Defaults to Fahrenheit to match the plan's imperial convention and the
    race's location. Worth flipping for the Italy block, where every local
    forecast being compared against is in Celsius.
    """
    raw = (os.environ.get("MC_TEMP_UNIT") or "fahrenheit").strip().lower()
    return "celsius" if raw in ("c", "celsius") else "fahrenheit"


def fmt_temp(value_f: float | None, unit: str | None = None) -> str:
    if value_f is None:
        return "—"
    unit = unit or temp_unit()
    if unit == "celsius":
        return f"{(value_f - 32) * 5 / 9:.0f}°C"
    return f"{value_f:.0f}°F"


# --- heat classification --------------------------------------------------------


class HeatLevel(str, Enum):
    """Deliberately *not* the §4 verdict vocabulary.

    §4's four verdicts describe how well a cross-training session substitutes
    for a run and must never be invented anew. This is a different axis
    entirely — how hard the air will make a session — and mixing the two
    vocabularies would let "⚠️ aerobic only" start meaning "it's warm out".
    Plain words, no emoji, no overlap.
    """

    NONE = "none"
    NOTICEABLE = "noticeable"
    HARD = "hard"
    EXTREME = "extreme"


_HEAT_RANK = {
    HeatLevel.NONE: 0,
    HeatLevel.NOTICEABLE: 1,
    HeatLevel.HARD: 2,
    HeatLevel.EXTREME: 3,
}

# Dew point drives this more than raw temperature: it's what decides whether
# sweat can evaporate, and 85°F at a 50°F dew point is a different run from
# 85°F at 72°F. The bands below follow the dew-point tables in common
# runner-facing coaching guidance (comfortable below ~60, most runners
# struggling by ~65, oppressive from ~70) rather than any single study.
#
# Like equivalence.py's verdict cutoffs, these are a judgment call stated
# plainly as one. Their only power is choosing which of four words gets
# printed next to a number that is always printed alongside — no §6 rule
# reads them, and nothing is decided by them.
DEW_POINT_F = {HeatLevel.NOTICEABLE: 60.0, HeatLevel.HARD: 65.0, HeatLevel.EXTREME: 72.0}
FEELS_LIKE_F = {HeatLevel.NOTICEABLE: 72.0, HeatLevel.HARD: 82.0, HeatLevel.EXTREME: 92.0}


def _level_from(value: float | None, thresholds: dict[HeatLevel, float]) -> HeatLevel:
    if value is None:
        return HeatLevel.NONE
    for level in (HeatLevel.EXTREME, HeatLevel.HARD, HeatLevel.NOTICEABLE):
        if value >= thresholds[level]:
            return level
    return HeatLevel.NONE


def heat_level(feels_like_f: float | None, dew_point_f: float | None) -> HeatLevel:
    """The worse of the two readings — a cool-feeling morning at a 70°F dew
    point is still a hard run, and a dry 95°F afternoon is still 95°F."""
    return max(
        _level_from(feels_like_f, FEELS_LIKE_F),
        _level_from(dew_point_f, DEW_POINT_F),
        key=lambda level: _HEAT_RANK[level],
    )


# --- location -------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    source: str  # printed every time — never let the origin be assumed


def _env_location() -> Location | None:
    lat_raw = (os.environ.get("MC_WEATHER_LAT") or "").strip()
    lon_raw = (os.environ.get("MC_WEATHER_LON") or "").strip()
    if not lat_raw or not lon_raw:
        return None
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except ValueError:
        return None
    return Location(
        lat=round(lat, COORD_PRECISION),
        lon=round(lon, COORD_PRECISION),
        source="MC_WEATHER_LAT/LON",
    )


def location_from_activities(
    garmin_activities: list[dict[str, Any]],
    as_of: date | None = None,
    max_age_days: int = LOCATION_MAX_AGE_DAYS,
) -> Location | None:
    """Most recent activity that carried a GPS fix, rounded before it's used
    anywhere. Indoor sessions have no coordinates and are skipped."""
    # Imported here, not at module scope: sync.py needs WeatherSyncReport at
    # class-definition time for its pydantic field, so the cycle can only be
    # broken on this side.
    from mc import sync

    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=max_age_days)
    best: tuple[datetime, float, float] | None = None
    for a in garmin_activities:
        lat, lon = a.get("startLatitude"), a.get("startLongitude")
        if lat is None or lon is None:
            continue
        dt = sync.parse_garmin_local_start(a)
        if dt is None or not (cutoff <= dt.date() <= as_of):
            continue
        if best is None or dt > best[0]:
            best = (dt, float(lat), float(lon))
    if best is None:
        return None
    dt, lat, lon = best
    return Location(
        lat=round(lat, COORD_PRECISION),
        lon=round(lon, COORD_PRECISION),
        source=f"last GPS activity {dt.strftime('%d-%m')}",
    )


def resolve_location(
    garmin_activities: list[dict[str, Any]] | None = None, as_of: date | None = None
) -> Location | None:
    """Explicit config wins over inference — that ordering is the least
    surprising one, and it's the only way to say "forecast for the city, not
    for wherever I happened to start running".

    The cost is that a set MC_WEATHER_LAT/LON will keep reporting home weather
    after a flight. That's why `mc weather` prints the source on every run
    instead of only when it's interesting: unsetting it is the fix, and you
    can only know to do that if you can see it.
    """
    env = _env_location()
    if env is not None:
        return env
    if garmin_activities is None:
        from mc import digest as digest_mod

        garmin_activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
    return location_from_activities(garmin_activities, as_of=as_of)


# --- hourly records ---------------------------------------------------------------


@dataclass(frozen=True)
class HourlyWeather:
    when: datetime  # naive local time, matching Garmin's startTimeLocal
    temp_f: float | None
    feels_like_f: float | None
    humidity_pct: float | None
    dew_point_f: float | None
    precip_prob: float | None
    precip_in: float | None
    wind_mph: float | None

    @property
    def heat(self) -> HeatLevel:
        return heat_level(self.feels_like_f, self.dew_point_f)


def hours_from_payload(payload: dict[str, Any]) -> list[HourlyWeather]:
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []

    def col(name: str) -> list[Any]:
        values = hourly.get(name) or []
        return list(values) + [None] * (len(times) - len(values))

    temps, feels = col("temperature_2m"), col("apparent_temperature")
    humidity, dew = col("relative_humidity_2m"), col("dew_point_2m")
    prob, precip = col("precipitation_probability"), col("precipitation")
    wind = col("wind_speed_10m")

    out: list[HourlyWeather] = []
    for i, raw_time in enumerate(times):
        try:
            when = datetime.fromisoformat(raw_time)
        except (TypeError, ValueError):
            continue
        out.append(
            HourlyWeather(
                when=when,
                temp_f=temps[i],
                feels_like_f=feels[i],
                humidity_pct=humidity[i],
                dew_point_f=dew[i],
                precip_prob=prob[i],
                precip_in=precip[i],
                wind_mph=wind[i],
            )
        )
    return out


# --- training windows --------------------------------------------------------------

# Named by when this athlete actually trains, not by clock convention: the
# digest's time-of-day table shows two real clusters — an early-morning one and
# an evening one — and those are the two slots any "when should I go" answer
# is choosing between. The middle bands exist so a bad answer can be shown to
# be bad rather than silently omitted.
WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("early", 5, 8),
    ("morning", 8, 11),
    ("midday", 11, 16),
    ("evening", 17, 21),
)


@dataclass(frozen=True)
class Window:
    name: str
    day: date
    start_hour: int
    end_hour: int
    feels_like_f: float | None  # worst hour in the window, not the average
    dew_point_f: float | None
    precip_prob: float | None
    wind_mph: float | None

    @property
    def heat(self) -> HeatLevel:
        return heat_level(self.feels_like_f, self.dew_point_f)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.start_hour:02d}:00–{self.end_hour:02d}:00)"


def _worst(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def windows_for_day(hours: list[HourlyWeather], day: date) -> list[Window]:
    """Each window summarised by its *worst* hour.

    A window is a commitment to be outside for its whole span, so the average
    is the wrong statistic — an 06:00 that's pleasant and an 07:45 that isn't
    average out to a recommendation that doesn't survive contact with the run.
    """
    out: list[Window] = []
    for name, start, end in WINDOWS:
        in_window = [
            h for h in hours if h.when.date() == day and start <= h.when.hour <= end
        ]
        if not in_window:
            continue
        out.append(
            Window(
                name=name,
                day=day,
                start_hour=start,
                end_hour=end,
                feels_like_f=_worst([h.feels_like_f for h in in_window]),
                dew_point_f=_worst([h.dew_point_f for h in in_window]),
                precip_prob=_worst([h.precip_prob for h in in_window]),
                wind_mph=_worst([h.wind_mph for h in in_window]),
            )
        )
    return out


def best_window(windows: list[Window]) -> Window | None:
    """Coolest window, ties broken toward the earlier slot.

    Ranked on heat level first and feels-like second, so a window that is
    merely 'noticeable' always beats one that is 'hard', even when a stray
    degree says otherwise.
    """
    if not windows:
        return None
    return min(
        windows,
        key=lambda w: (
            _HEAT_RANK[w.heat],
            w.feels_like_f if w.feels_like_f is not None else 999.0,
            w.start_hour,
        ),
    )


# --- fetch & cache -------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def fetch(
    location: Location,
    *,
    past_days: int = DEFAULT_PAST_DAYS,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
) -> dict[str, Any]:
    """One GET. Caches the envelope to data/raw/weather/ like every other
    source, so everything downstream reads the cache and never the network."""
    params = {
        "latitude": f"{location.lat:.{COORD_PRECISION}f}",
        "longitude": f"{location.lon:.{COORD_PRECISION}f}",
        "hourly": ",".join(HOURLY_FIELDS),
        "temperature_unit": "fahrenheit",  # canonical internally; see fmt_temp
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "auto",
        "past_days": str(past_days),
        "forecast_days": str(forecast_days),
    }

    attempt = 0
    while True:
        try:
            resp = httpx.get(BASE_URL, params=params, timeout=_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < _MAX_RETRIES:
                attempt += 1
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise WeatherConnectionError(f"Open-Meteo: network error — {e}") from e

        if resp.status_code >= 500:
            if attempt < _MAX_RETRIES:
                attempt += 1
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise WeatherServerError(f"Open-Meteo: {resp.status_code} — {resp.text[:200]}")
        if resp.status_code >= 400:
            raise WeatherError(f"Open-Meteo: {resp.status_code} — {resp.text[:200]}")
        break

    data = resp.json()
    envelope = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "open-meteo /v1/forecast",
        "location": {"lat": location.lat, "lon": location.lon, "source": location.source},
        "data": data,
    }
    out_dir = cfg.RAW_WEATHER_DIR
    _write_json(out_dir / f"{date.today().isoformat()}.json", envelope)
    _write_json(out_dir / "latest.json", envelope)
    return envelope


def load_cached() -> dict[str, Any] | None:
    path = cfg.RAW_WEATHER_DIR / "latest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 — a corrupt cache is "no weather", not a crash
        return None


def cache_age_hours(envelope: dict[str, Any] | None) -> float | None:
    if not envelope or not envelope.get("fetched_at"):
        return None
    try:
        fetched = datetime.fromisoformat(str(envelope["fetched_at"]))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600


# --- sync integration ------------------------------------------------------------------


class WeatherSyncReport(BaseModel):
    """Deliberately kept out of SyncReport.sources.

    `SyncReport.all_ok` decides `mc sync`'s exit code, and the daily ritual
    treats a non-zero exit as "the data didn't arrive". Weather is not
    rule-critical: no §6 rule reads it, and a failed forecast must not make a
    successful Garmin pull look like a failed sync. It reports separately, and
    loudly, and changes nothing else.
    """

    attempted: bool = False
    ok: bool = False
    error: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    location_source: str | None = None
    hours_cached: int = 0


def enabled() -> bool:
    """`MC_WEATHER=off` disables the only outbound call this feature makes."""
    return (os.environ.get("MC_WEATHER") or "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "no",
    )


def sync_weather(garmin_activities: list[dict[str, Any]]) -> WeatherSyncReport:
    """Called once per `mc sync`. Never raises — a weather failure is reported,
    not propagated, for the reason spelled out on WeatherSyncReport."""
    if not enabled():
        return WeatherSyncReport(attempted=False, error="disabled (MC_WEATHER=off)")

    location = resolve_location(garmin_activities)
    if location is None:
        return WeatherSyncReport(
            attempted=False,
            error=(
                "no location — no GPS activity in the last "
                f"{LOCATION_MAX_AGE_DAYS} days and MC_WEATHER_LAT/LON unset"
            ),
        )

    try:
        envelope = fetch(location)
    except WeatherError as e:
        return WeatherSyncReport(
            attempted=True,
            ok=False,
            error=str(e),
            location_lat=location.lat,
            location_lon=location.lon,
            location_source=location.source,
        )

    return WeatherSyncReport(
        attempted=True,
        ok=True,
        location_lat=location.lat,
        location_lon=location.lon,
        location_source=location.source,
        hours_cached=len(hours_from_payload(envelope.get("data") or {})),
    )


# --- markdown rendering (consumed by digest.py) -------------------------------------


def _window_line(w: Window) -> str:
    rain = (
        f", {w.precip_prob:.0f}% precip"
        if w.precip_prob is not None and w.precip_prob >= 20
        else ""
    )
    return (
        f"{w.label}: {fmt_temp(w.feels_like_f)} feels-like, "
        f"dew point {fmt_temp(w.dew_point_f)} — {w.heat.value}{rain}"
    )


def digest_lines(as_of: date, envelope: dict[str, Any] | None = None) -> list[str]:
    """Today's and tomorrow's windows, worst-hour basis, with the location and
    cache age stated rather than implied."""
    envelope = envelope if envelope is not None else load_cached()
    if envelope is None:
        return [
            "- No weather cached — run `mc sync` (or `mc weather --refresh`). "
            "Set MC_WEATHER_LAT/LON if there's been no GPS run recently."
        ]

    age = cache_age_hours(envelope)
    loc = envelope.get("location") or {}
    stale = age is not None and age > STALE_HOURS
    header = (
        f"- Location: {loc.get('lat')}, {loc.get('lon')} "
        f"(from {loc.get('source', 'unknown')}) · fetched "
        + (f"{age:.0f}h ago" if age is not None else "at an unknown time")
    )
    lines = [f"- **{header[2:]} — STALE**" if stale else header]

    hours = hours_from_payload(envelope.get("data") or {})
    if not hours:
        return lines + ["- Cached payload has no hourly data."]

    for label, day in (("Today", as_of), ("Tomorrow", as_of + timedelta(days=1))):
        windows = windows_for_day(hours, day)
        if not windows:
            lines.append(f"- {label} ({day.strftime('%d-%m')}): no forecast hours cached.")
            continue
        best = best_window(windows)
        lines.append(f"- {label} ({day.strftime('%d-%m')}):")
        for w in windows:
            marker = " ← coolest" if best is not None and w.name == best.name else ""
            lines.append(f"  - {_window_line(w)}{marker}")

    lines.append(
        "- Heat levels are none/noticeable/hard/extreme — a separate vocabulary "
        "from §4's substitution verdicts, and not a §6 trigger on their own: "
        "C2 is a permission you exercise, citing these numbers."
    )
    return lines
