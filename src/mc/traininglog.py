from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from mc import config as cfg
from mc import digest as digest_mod
from mc import sync

PENDING = "*(pending)*"
_YEAR = 2026  # matches _parse_ddmm elsewhere in the codebase — no year-boundary in this project's timeframe

_TITLE = "# Training log\n"
_HEADER = "| Date | Proposed | Actual |\n"
_SEP = "|---|---|---|\n"
_ROW_RE = re.compile(r"^\|\s*(\d{2}-\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


@dataclass
class LogRow:
    date: date
    proposed: str
    actual: str


def _parse_ddmm(s: str) -> date:
    day, month = s.split("-")
    return date(_YEAR, int(month), int(day))


def load_log(path=cfg.TRAINING_LOG_PATH) -> list[LogRow]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        m = _ROW_RE.match(line.strip())
        if not m or m.group(1) == "Date":
            continue
        rows.append(LogRow(date=_parse_ddmm(m.group(1)), proposed=m.group(2), actual=m.group(3)))
    return rows


def save_log(rows: list[LogRow], path=cfg.TRAINING_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: r.date)
    lines = [_TITLE, "\n", _HEADER, _SEP]
    for r in ordered:
        lines.append(f"| {r.date.strftime('%d-%m')} | {r.proposed} | {r.actual} |\n")
    path.write_text("".join(lines))


def record_proposed(d: date, proposed: str, *, path=cfg.TRAINING_LOG_PATH) -> None:
    """Called when /daily writes today's plan. Appends a new row, or updates
    the Proposed cell in place if today's row already exists (e.g. /daily
    re-run same day) — never duplicates a date."""
    rows = load_log(path)
    existing = next((r for r in rows if r.date == d), None)
    if existing:
        existing.proposed = proposed
    else:
        rows.append(LogRow(date=d, proposed=proposed, actual=PENDING))
    save_log(rows, path)


def describe_actual_session(activities: list[dict[str, Any]], d: date) -> str:
    """Objective, factual summary of what really happened on date d, from
    synced Garmin data — deliberately not editorialized as 'matches' or
    'differs', just states the facts so the Proposed/Actual columns can be
    compared by eye."""
    matches = []
    for a in activities:
        dt = digest_mod._garmin_local_start(a)
        if dt is None or dt.date() != d:
            continue
        bucket = sync.canonical_bucket((a.get("activityType") or {}).get("typeKey"), sync.GARMIN_BUCKET_KEYWORDS)
        dist_m = a.get("distance")
        dur_s = a.get("duration")
        hr = a.get("averageHR")
        parts = [bucket]
        if bucket == "run" and dist_m:
            parts.append(f"{dist_m / sync.MILE_M:.1f}mi")
        if dur_s:
            parts.append(f"{dur_s / 60:.0f}min")
        if hr:
            parts.append(f"HR{hr:.0f}")
        matches.append(" ".join(parts))
    if not matches:
        return "Nothing logged"
    return "; ".join(matches)


def fill_pending_actuals(
    activities: list[dict[str, Any]], *, up_to: date | None = None, path=cfg.TRAINING_LOG_PATH
) -> int:
    """For every row still marked pending and dated on/before up_to (default
    yesterday — today's own session is presumably not done yet when /daily
    runs in the morning), fill the Actual column from synced data. Returns
    the number of rows updated."""
    up_to = up_to or (date.today() - timedelta(days=1))
    rows = load_log(path)
    updated = 0
    for r in rows:
        if r.actual == PENDING and r.date <= up_to:
            r.actual = describe_actual_session(activities, r.date)
            updated += 1
    if updated:
        save_log(rows, path)
    return updated
