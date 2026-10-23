"""Where activity data comes from, and what shape it arrives in.

Garmin was the only source that mattered until intervals.icu became the
primary one. The reason is not fidelity — Garmin carries more — it is
*credentials*: `mc sync` against Garmin needs an account password and TLS
impersonation (`curl_cffi`) to get past bot detection, while intervals.icu
needs a scoped, independently revocable API key that is designed to be handed
to third-party tools. Only the second of those belongs in an environment with
no secrets store, so a session running anywhere but the laptop reads
intervals.

Rather than teach `check`, `plan`, `render`, `weather` and `metrics` about two
schemas, this module **normalizes at the boundary**: it emits Garmin-shaped
dicts whatever the source, so every existing `activity.get("averageHR")` keeps
working untouched.

## The unit conversions, and why they are stated rather than assumed

intervals.icu reports cadence **per leg** and step length in **millimetres**;
Garmin reports both-legs cadence and centimetres. A mistake here does not
crash — it produces a plausible number, and the decay thresholds (−4 spm,
−5%) are calibrated on Garmin's units, so a silent factor of two would turn
every run into a finding or none into one.

The ×2 was not a new discovery — `TODO.md` recorded it on 04-08-2026 as a trap
any intervals backfill would hit. The ÷10 was not recorded anywhere. Both were
re-confirmed here against **28 runs present in both caches**, rather than taken
from documentation or from the earlier note:

    garmin averageRunningCadence   173.86  ·  intervals average_cadence   86.88  (×2 → 173.77)
                                   167.11  ·                              83.22  (×2 → 166.43)
                                   164.66  ·                              82.36  (×2 → 164.73)

    garmin directStrideLength (cm) 115.80  ·  intervals step_length (mm) 1148.46 (÷10 → 114.85)
                                   103.70  ·                            1035.29 (÷10 → 103.53)
                                   107.90  ·                            1072.05 (÷10 → 107.20)

GAP needs no conversion — both are m/s, and they agree to within ~2% (Garmin's
model against Strava's, which is what `gap_model: STRAVA_RUN` says it uses).
They also agree on *absence*: both report nothing for a treadmill run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mc import config as cfg
from mc import intervals as intervals_api
from mc import sync

GARMIN = "garmin"
INTERVALS = "intervals"

# intervals.icu counts one leg; Garmin counts both.
CADENCE_LEG_FACTOR = 2.0
# intervals.icu step length is millimetres; Garmin's directStrideLength is cm.
STRIDE_MM_PER_CM = 10.0


# --- loading ------------------------------------------------------------------


def _load_latest(root, kind: str) -> list[dict[str, Any]]:
    """Deliberately duplicated from digest._load_latest rather than imported:
    digest imports metrics which will import this module, and the cycle is not
    worth a lazy import for four lines."""
    path = root / kind / "latest.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())["data"]
    except Exception:  # noqa: BLE001
        return []


# --- activity normalization ----------------------------------------------------


def _positive(value: Any) -> float | None:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    return as_float if as_float > 0 else None


def normalize_intervals_activity(activity: dict[str, Any]) -> dict[str, Any]:
    """One intervals.icu activity in Garmin's shape.

    Only the fields something actually reads are mapped. Adding more on
    speculation would mean guessing at semantics that have not been checked
    against a real payload, and a wrong mapping is worse than a missing one.
    """
    start = activity.get("start_date_local")
    # Garmin's startTimeLocal is "YYYY-MM-DD HH:MM:SS"; intervals uses a T.
    start_local = str(start).replace("T", " ") if start else None

    duration = next(
        (activity[k] for k in intervals_api.MOVING_TIME_FIELD_CANDIDATES
         if activity.get(k) is not None),
        None,
    )
    avg_hr = next(
        (activity[k] for k in intervals_api.AVG_HR_FIELD_CANDIDATES
         if activity.get(k) is not None),
        None,
    )

    cadence = _positive(activity.get("average_cadence"))
    return {
        "activityId": activity.get("id"),
        "activityType": {"typeKey": activity.get("type")},
        "startTimeLocal": start_local,
        "startTimeGMT": str(activity.get("start_date") or "").replace("T", " ").replace("Z", ""),
        "distance": activity.get("distance"),
        "duration": duration,
        "averageHR": avg_hr,
        "averageRunningCadenceInStepsPerMinute": (
            cadence * CADENCE_LEG_FACTOR if cadence is not None else None
        ),
        "avgGradeAdjustedSpeed": activity.get("gap"),
        "elevationGain": activity.get("total_elevation_gain"),
        "elevationLoss": activity.get("total_elevation_loss"),
        # No coordinates exist on an intervals activity — all 183 fields were
        # checked. They live only in the `latlng` stream, so weather location
        # is filled in separately; see location.py / the streams cache.
        "startLatitude": None,
        "startLongitude": None,
        "_source": INTERVALS,
    }


def _tag_garmin(activity: dict[str, Any]) -> dict[str, Any]:
    return {**activity, "_source": GARMIN}


def activities(tolerance_minutes: int = sync.MATCH_TOLERANCE_MINUTES) -> list[dict[str, Any]]:
    """Every known activity, Garmin-shaped, newest source preferred per activity.

    Not "Garmin if present, else intervals" — that would hide this morning's
    run behind a Garmin cache last written three days ago, which is exactly the
    situation on a laptop that has been shut. Instead the two are *merged*: a
    Garmin record wins wherever the same session exists in both (it carries
    more fields), and an intervals record is used wherever Garmin has nothing.

    Matching is by canonical bucket and start time within the same tolerance
    `mc sync` already uses for its cross-check, so the two agree about what
    counts as the same session.
    """
    garmin = _load_latest(cfg.RAW_GARMIN_DIR, "activities")
    intervals = _load_latest(cfg.RAW_INTERVALS_DIR, "activities")

    tolerance = timedelta(minutes=tolerance_minutes)
    claimed = [
        (sync.parse_garmin_start(a), sync.canonical_bucket(
            (a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS
        ))
        for a in garmin
    ]
    claimed = [(when, bucket) for when, bucket in claimed if when is not None]

    merged = [_tag_garmin(a) for a in garmin]
    for a in intervals:
        when = sync.parse_intervals_start(a)
        bucket = sync.canonical_bucket(a.get("type"), sync.INTERVALS_BUCKET_KEYWORDS)
        if when is not None and any(
            b == bucket and abs(when - gw) <= tolerance for gw, b in claimed
        ):
            continue
        merged.append(normalize_intervals_activity(a))
    return merged


# --- wellness ------------------------------------------------------------------
#
# The three readings §6 actually spends: C2 lists "HRV below baseline, sleep
# <6h, resting HR +5bpm" and E1 requires READINESS to cite data rather than a
# feeling. Losing them is what would make an intervals-only session unable to
# exercise C2 at all — which is why these are mapped and Body Battery, VO2max
# and training status (none of which any rule reads) are not.
#
# intervals is emitted in Garmin's nested shape so digest's formatters, whose
# field paths were read off real Garmin responses, keep working untouched.
INTERVALS_WELLNESS_SHAPES: dict[str, Any] = {
    "hrv": lambda r: (
        {"hrvSummary": {"lastNightAvg": r["hrv"], "status": None}}
        if r.get("hrv") is not None
        else None
    ),
    "sleep": lambda r: (
        {"dailySleepDTO": {"sleepTimeSeconds": r["sleepSecs"]}}
        if r.get("sleepSecs") is not None
        else None
    ),
    "stats": lambda r: (
        {"restingHeartRate": r["restingHR"]} if r.get("restingHR") is not None else None
    ),
    "stress": lambda r: (
        {"avgStressLevel": r["stress"]} if r.get("stress") is not None else None
    ),
}


# Where the salient number lives inside each Garmin-shaped payload. Used to
# ask "is this reading actually usable?", which is not the same question as
# "does a record exist". Garmin writes a populated `dailySleepDTO` whose
# `sleepTimeSeconds` is null on a night the watch did not track sleep — a
# record that looks like data and carries none.
GARMIN_WELLNESS_PROBES: dict[str, Any] = {
    "hrv": lambda d: (d.get("hrvSummary") or {}).get("lastNightAvg"),
    "sleep": lambda d: (d.get("dailySleepDTO") or {}).get("sleepTimeSeconds"),
    "stats": lambda d: d.get("restingHeartRate"),
    "stress": lambda d: d.get("avgStressLevel"),
}


def garmin_wellness_value(
    metric: str, as_of: date, lookback_days: int = 7, *, require_value: bool = False
) -> tuple[str, Any] | None:
    """Most recent day at or before as_of (within lookback_days) that actually
    has non-empty data for this metric — as_of itself often has no data yet
    (watch not synced), so we walk backward rather than assuming it's
    populated.

    With `require_value`, a day whose payload exists but whose salient number
    is null is skipped rather than returned. Off by default so the historical
    behaviour of this function is unchanged for callers that want the raw
    Garmin record.
    """
    metric_dir = cfg.RAW_GARMIN_DIR / "wellness" / metric
    if not metric_dir.exists():
        return None
    probe = GARMIN_WELLNESS_PROBES.get(metric) if require_value else None
    for offset in range(lookback_days):
        d = (as_of - timedelta(days=offset)).isoformat()
        f = metric_dir / f"{d}.json"
        if not f.exists():
            continue
        try:
            payload = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        data = payload.get("data")
        if data in (None, [], {}):
            continue
        if probe is not None:
            try:
                if probe(data) is None:
                    continue
            except (AttributeError, TypeError):
                continue
        return d, data
    return None


def intervals_wellness_value(
    metric: str, as_of: date, lookback_days: int = 7
) -> tuple[str, Any] | None:
    """The same walk-backwards search over intervals' flat daily records.

    Records are keyed by `id` = ISO date, one per day — the same convention
    `build_wellness_snapshot` already relies on for CTL/ATL/TSB.
    """
    shape = INTERVALS_WELLNESS_SHAPES.get(metric)
    if shape is None:
        return None  # Garmin-only metric; absent is the honest answer
    by_day = {
        str(r.get("id")): r for r in _load_latest(cfg.RAW_INTERVALS_DIR, "wellness")
    }
    for offset in range(lookback_days):
        d = (as_of - timedelta(days=offset)).isoformat()
        record = by_day.get(d)
        if not record:
            continue
        try:
            data = shape(record)
        except (KeyError, TypeError, ValueError):
            continue
        if data:
            return d, data
    return None


def wellness_value(
    metric: str, as_of: date, lookback_days: int = 7
) -> tuple[str, Any, str] | None:
    """One wellness reading, and **which source it came from**.

    **The freshest usable reading wins**, and Garmin breaks a tie because it
    carries more (an HRV status word, a stress average). Freshness decides
    rather than a fixed source order because both caches walk backwards up to
    a week: preferring Garmin outright would answer a question about last
    night with a reading from four days ago whenever the watch missed a night,
    while intervals had the night itself. Where both have the same day they
    agree anyway — intervals is downstream of Garmin — which was checked
    against real data: HRV 44 ms and RHR 42 bpm on both sides, same days.

    The source is returned rather than inferred so the digest can print it.
    §7's rule is that a number never appears without saying where it came
    from, and "HRV 42 ms" means something different if the watch last synced
    three days ago.
    """
    from_garmin = garmin_wellness_value(metric, as_of, lookback_days, require_value=True)
    from_intervals = intervals_wellness_value(metric, as_of, lookback_days)
    if from_garmin is None and from_intervals is None:
        return None
    if from_intervals is None:
        return from_garmin[0], from_garmin[1], GARMIN  # type: ignore[index]
    if from_garmin is None:
        return from_intervals[0], from_intervals[1], INTERVALS
    if from_intervals[0] > from_garmin[0]:
        return from_intervals[0], from_intervals[1], INTERVALS
    return from_garmin[0], from_garmin[1], GARMIN


def garmin_hr_settings(as_of: date) -> tuple[str, Any] | None:
    """The newest HR-settings snapshot taken on or before `as_of`.

    Deliberately **no lookback window**, unlike every wellness metric above: a
    setting is true until it is changed, so on a day nothing was synced the
    right answer to "what is Max HR" is the last snapshot taken, however old.
    Garmin-only — intervals.icu carries no equivalent.

    The snapshot *date* is returned with the payload so the digest can say how
    old the reading is rather than implying it was read this morning.
    """
    hr_dir = cfg.RAW_GARMIN_DIR / "wellness" / "hr_settings"
    if not hr_dir.exists():
        return None
    as_of_iso = as_of.isoformat()
    for f in sorted(hr_dir.glob("20??-??-??.json"), reverse=True):
        if f.stem > as_of_iso:
            continue
        try:
            data = json.loads(f.read_text()).get("data")
        except Exception:  # noqa: BLE001
            continue
        if data in (None, [], {}):
            continue
        return f.stem, data
    return None


# --- streams -------------------------------------------------------------------


@dataclass(frozen=True)
class Streams:
    """Per-sample run data in one canonical shape, in canonical units.

    Whichever source filled it, `cadence` is both-legs steps/min, `stride` is
    metres, and the two speeds are m/s — so `metrics.run_splits` never has to
    know which API it is looking at, and the conversions live in exactly one
    place.

    Lists are parallel and the same length; entries may be None except
    `distance`, which is what the thirds are split on.
    """

    distance: list[float] = field(default_factory=list)
    cadence: list[float | None] = field(default_factory=list)
    stride: list[float | None] = field(default_factory=list)
    gap_speed: list[float | None] = field(default_factory=list)
    speed: list[float | None] = field(default_factory=list)
    source: str = GARMIN

    def __len__(self) -> int:
        return len(self.distance)


def garmin_streams_path(activity_id: str):
    return cfg.RAW_GARMIN_DIR / "activities" / "details" / f"{activity_id}.json"


def intervals_streams_path(activity_id: str):
    return cfg.RAW_INTERVALS_DIR / "streams" / f"{activity_id}.json"


def parse_garmin_streams(payload: dict[str, Any]) -> Streams | None:
    """Garmin's detail payload: a metric-name → column-index map plus rows.

    Looked up by key name because the index order genuinely varies between
    activities (one real payload here has 9 metrics, another 17), and every
    stream but cadence and distance is optional.
    """
    try:
        data = payload["data"]
        descriptors = {m["key"]: m["metricsIndex"] for m in data["metricDescriptors"]}
        rows = data["activityDetailMetrics"]
    except (KeyError, TypeError, ValueError):
        return None

    cadence_idx = descriptors.get("directDoubleCadence")
    distance_idx = descriptors.get("sumDistance")
    if cadence_idx is None or distance_idx is None:
        return None
    stride_idx = descriptors.get("directStrideLength")
    gap_idx = descriptors.get("directGradeAdjustedSpeed")
    speed_idx = descriptors.get("directSpeed")

    def value_at(values: list[Any], index: int | None) -> float | None:
        if index is None or len(values) <= index:
            return None
        raw = values[index]
        return None if raw is None else float(raw)

    out = Streams(source=GARMIN)
    for row in rows:
        values = row.get("metrics") or []
        cadence = value_at(values, cadence_idx)
        distance = value_at(values, distance_idx)
        if cadence is None or distance is None or cadence <= 0:
            continue
        stride_cm = value_at(values, stride_idx)
        out.distance.append(distance)
        out.cadence.append(cadence)
        # Garmin's stride is centimetres; canonical is metres.
        out.stride.append(stride_cm / 100.0 if stride_cm and stride_cm > 0 else None)
        out.gap_speed.append(value_at(values, gap_idx))
        out.speed.append(value_at(values, speed_idx))
    return out


def _gap_by_sample_index(laps: Any) -> dict[int, float]:
    """Expand per-lap GAP into a lookup by stream sample index.

    intervals exposes no per-sample grade-adjusted speed (`types=gap` is a
    422), but each lap carries `gap` alongside `start_index`/`end_index` —
    which index into the stream arrays directly. So a sample's GAP is its
    lap's. The result is a step function rather than Garmin's smooth one, and
    since laps here are per-mile while the thirds are per-third-of-distance,
    the medians land in the same place either way.
    """
    out: dict[int, float] = {}
    if not isinstance(laps, list):
        return out
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        gap = lap.get("gap")
        start, end = lap.get("start_index"), lap.get("end_index")
        if gap is None or start is None or end is None:
            continue
        try:
            for i in range(int(start), int(end)):
                out[i] = float(gap)
        except (TypeError, ValueError):
            continue
    return out


def parse_intervals_streams(payload: Any) -> Streams | None:
    """intervals.icu's `/streams`: a list of `{type, data}` parallel arrays.

    Unlike Garmin's row-per-sample layout this is column-per-metric, so the
    arrays are indexed together rather than walked. `latlng` is the odd one
    out — it splits across `data` (latitudes) and `data2` (longitudes) — but
    nothing here reads it; see `first_fix`.

    Accepts either the bare stream list or the cached envelope, which also
    carries the laps that supply GAP.
    """
    laps: Any = []
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    if isinstance(payload, dict):
        laps = payload.get("laps") or []
        payload = payload.get("streams") or []
    if not isinstance(payload, list):
        return None

    by_type = {s.get("type"): s.get("data") or [] for s in payload if isinstance(s, dict)}
    distance = by_type.get("distance")
    cadence = by_type.get("cadence")
    if not distance or not cadence:
        return None
    stride = by_type.get("step_length") or []
    speed = by_type.get("velocity_smooth") or []
    gap_at = _gap_by_sample_index(laps)

    def at(seq: list[Any], i: int) -> float | None:
        if i >= len(seq) or seq[i] is None:
            return None
        try:
            return float(seq[i])
        except (TypeError, ValueError):
            return None

    out = Streams(source=INTERVALS)
    for i in range(min(len(distance), len(cadence))):
        d, c = at(distance, i), at(cadence, i)
        if d is None or c is None or c <= 0:
            continue
        s = at(stride, i)
        out.distance.append(d)
        # Per-leg → both legs, and millimetres → metres.
        out.cadence.append(c * CADENCE_LEG_FACTOR)
        out.stride.append(s / STRIDE_MM_PER_CM / 100.0 if s and s > 0 else None)
        # Looked up on the ORIGINAL index: samples are dropped below, so any
        # lap lookup done after filtering would silently shift.
        out.gap_speed.append(gap_at.get(i))
        out.speed.append(at(speed, i))
    return out


def first_fix(payload: Any) -> tuple[float, float] | None:
    """Start coordinate from an intervals `latlng` stream.

    Coordinates exist nowhere on the activity object — all 183 fields were
    checked — so this is the only way to answer "where was this run?", which
    `weather.location_from_activities` needs in order to follow the athlete to
    Italy. The stream splits lat and lon across two parallel arrays. An indoor
    run returns an empty list, which is a clean "no GPS" rather than an error.
    """
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    if not isinstance(payload, list):
        return None
    for stream in payload:
        if not isinstance(stream, dict) or stream.get("type") != "latlng":
            continue
        lats, lons = stream.get("data") or [], stream.get("data2") or []
        for lat, lon in zip(lats, lons):
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    return None


def streams(activity_id: str | None) -> Streams | None:
    """Per-sample streams for one activity, from whichever cache has them.

    Garmin first, because it carries per-sample GAP that intervals does not.
    Both are read from disk only — neither branch makes a network call.
    """
    if not activity_id:
        return None
    garmin_path = garmin_streams_path(str(activity_id))
    if garmin_path.exists():
        try:
            parsed = parse_garmin_streams(json.loads(garmin_path.read_text()))
        except (OSError, ValueError):
            parsed = None
        if parsed is not None:
            return parsed
    intervals_path = intervals_streams_path(str(activity_id))
    if intervals_path.exists():
        try:
            return parse_intervals_streams(json.loads(intervals_path.read_text()))
        except (OSError, ValueError):
            return None
    return None
