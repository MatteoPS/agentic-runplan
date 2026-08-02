"""Is the plan still matching real life? -- answered in sentences, not rule IDs.

§6 E5 says that more than 2 overrides in a 4-week block means the plan isn't
matching my life and a *structural* revision is due. The problem with that as
written is that it only fires once the tripwire is hit. By then the drift has
already happened; the interesting information was in the weeks before, in the
shape of what kept going wrong. Three SHIN deviations and a 15% mileage
shortfall is a plan that needs changing, whether or not anyone typed the word
OVERRIDE.

So this module reports counts and dates over a trailing window, in plain
language. Two constraints on it:

- **It never diagnoses.** §6 D6: not a doctor, not a physio. "SHIN appears on
  3 days" is a fact worth surfacing. "You have shin splints" is not this
  module's to say, and neither is "you should cut the long run" -- that's a
  §6 proposal, made by the agent with the plan in hand.
- **It never overclaims precision.** The sources differ wildly in how
  structured they are: training-log.md is a real table, log/sessions/ is
  free prose. A number parsed out of free-text
  prose is reported as a *mention count*, and says so. An authoritative-
  looking 0 from a file that has no entries and no writer would be worse than
  saying "not tracked yet".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from mc import config as cfg
from mc import traininglog as tlog_mod

# §6 E1's closed set. Matched as whole words, case-sensitive: these are typed
# in prose as uppercase tokens, and lowercasing the match would turn every
# mention of the word "life" or "travel" into a reason code.
REASON_CODES = (
    "TRAVEL", "RACE", "ILLNESS", "INJURY", "SHIN", "HAMSTRING",
    "HEAT", "WEATHER", "LIFE", "READINESS", "OVERRIDE",
)
_CODE_RE = re.compile(r"\b(" + "|".join(REASON_CODES) + r")\b")

# "10.5mi", "3 mi", "4.0mi" -- the shape both columns of training-log.md use.
_MILES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mi\b", re.IGNORECASE)

# An override entry, as written by `mc override`. The date and code are
# structured precisely so this file stops being unparseable prose.
_OVERRIDE_ENTRY_RE = re.compile(r"^##\s*(\d{2}-\d{2})\s*·\s*([A-Z]+)\s*$", re.MULTILINE)

OVERRIDE_LIMIT_PER_BLOCK = 2  # §6 E5
BLOCK_WEEKS = 4

# Below this, a proposed-vs-actual gap is rounding and GPS noise, not a
# deviation worth reporting. A mile is roughly a 10-minute error at easy pace.
DEVIATION_TOLERANCE_MI = 1.0

NOTHING_LOGGED = "Nothing logged"


@dataclass(frozen=True)
class Deviation:
    day: str  # DD-MM
    proposed_mi: float
    actual_mi: float
    codes: tuple[str, ...]

    @property
    def missed_entirely(self) -> bool:
        return self.actual_mi == 0 and self.proposed_mi > 0

    @property
    def shortfall_mi(self) -> float:
        return round(self.proposed_mi - self.actual_mi, 1)


@dataclass(frozen=True)
class DriftReport:
    since: date
    until: date
    weeks: int
    days_logged: int
    deviations: list[Deviation]
    code_mentions: dict[str, list[str]]  # CODE -> [DD-MM, ...]
    proposed_mi: float
    actual_mi: float
    overrides: list[tuple[str, str]] | None  # (DD-MM, CODE); None = not trackable
    override_log_exists: bool = True

    @property
    def compliance_pct(self) -> int | None:
        if self.proposed_mi <= 0:
            return None
        return round(self.actual_mi / self.proposed_mi * 100)

    @property
    def over_override_limit(self) -> bool:
        return self.overrides is not None and len(self.overrides) > OVERRIDE_LIMIT_PER_BLOCK


# --- parsing ------------------------------------------------------------------------


def _all_miles(text: str) -> list[float]:
    if not text or text.strip() == NOTHING_LOGGED:
        return []
    return [float(m.group(1)) for m in _MILES_RE.finditer(text)]


def proposed_miles_in(text: str) -> float:
    """Miles for the *day* from a Proposed cell -- the first figure only.

    The two columns need different rules, which is worth spelling out because
    summing both looks obviously right and is wrong. /daily writes the day's
    session first but often continues into context for the rest of the week:

        "Long run, already done this morning — 10.5mi (locked 11.0);
         Sat 01-08 3mi easy + fixed strength 2/2, Sun 02-08 2mi easy"

    Summing that yields 15.5mi for a single day and invents a 5mi shortfall
    out of nothing. The day's own distance is always the first one stated.
    """
    miles = _all_miles(text)
    return round(miles[0], 1) if miles else 0.0


def actual_miles_in(text: str) -> float:
    """Miles from an Actual cell -- summed.

    Opposite rule, because this column is machine-written by
    traininglog.describe_actual_session and genuinely lists every activity
    recorded that day: "run 4.0mi 38min; run 2.1mi 20min" is one day's two
    runs, and both count.
    """
    return round(sum(_all_miles(text)), 1)


def codes_in(text: str) -> tuple[str, ...]:
    """Reason codes mentioned in free text, de-duplicated, in first-seen order."""
    seen: list[str] = []
    for m in _CODE_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return tuple(seen)


def _session_text_for(day: date, sessions_dir: Path) -> str:
    """log/sessions/ is one free-text file per day, named YYYY-MM-DD.md."""
    path = sessions_dir / f"{day.isoformat()}.md"
    return path.read_text() if path.exists() else ""


def parse_overrides(path: Path) -> tuple[list[tuple[str, str]] | None, bool]:
    """Returns (entries, file_exists).

    entries is None when the file exists but has no parseable entries -- which
    today means "nothing has ever been written here", not "zero overrides
    occurred". Reporting a confident 0 from an unwritten file would be the
    exact overclaim this module is meant to avoid. Once `mc override` has
    written even one entry, the count becomes real.
    """
    if not path.exists():
        return None, False
    entries = [(m.group(1), m.group(2)) for m in _OVERRIDE_ENTRY_RE.finditer(path.read_text())]
    return (entries or None), True


# --- the report ---------------------------------------------------------------------


def build_report(
    *,
    weeks: int = BLOCK_WEEKS,
    as_of: date | None = None,
    log_path: Path | None = None,
    sessions_dir: Path | None = None,
    overrides_path: Path | None = None,
) -> DriftReport:
    as_of = as_of or date.today()
    log_path = log_path or cfg.TRAINING_LOG_PATH
    sessions_dir = sessions_dir or cfg.LOG_SESSIONS_DIR
    overrides_path = overrides_path or cfg.OVERRIDES_LOG_PATH

    since = as_of - timedelta(weeks=weeks)
    rows = [r for r in tlog_mod.load_log(log_path) if since <= r.date <= as_of]

    deviations: list[Deviation] = []
    code_mentions: dict[str, list[str]] = {}
    proposed_total = actual_total = 0.0

    for row in rows:
        # A row still pending has no actual yet -- it isn't a deviation, it's
        # a day that hasn't been measured. Counting it as a shortfall would
        # make every report look bad on the day it runs.
        if row.actual == tlog_mod.PENDING:
            continue

        ddmm = row.date.strftime("%d-%m")
        proposed_mi = proposed_miles_in(row.proposed)
        actual_mi = actual_miles_in(row.actual)
        proposed_total += proposed_mi
        actual_total += actual_mi

        text = f"{row.proposed}\n{row.actual}\n{_session_text_for(row.date, sessions_dir)}"
        codes = codes_in(text)
        for code in codes:
            code_mentions.setdefault(code, []).append(ddmm)

        if abs(proposed_mi - actual_mi) > DEVIATION_TOLERANCE_MI:
            deviations.append(
                Deviation(day=ddmm, proposed_mi=proposed_mi, actual_mi=actual_mi, codes=codes)
            )

    overrides, exists = parse_overrides(overrides_path)
    return DriftReport(
        since=since,
        until=as_of,
        weeks=weeks,
        days_logged=len([r for r in rows if r.actual != tlog_mod.PENDING]),
        deviations=deviations,
        code_mentions=code_mentions,
        proposed_mi=round(proposed_total, 1),
        actual_mi=round(actual_total, 1),
        overrides=overrides,
        override_log_exists=exists,
    )


# --- writing an override ------------------------------------------------------------


class OverrideError(Exception):
    pass


def append_override(code: str, reason: str, *, day: date | None = None, path: Path | None = None) -> str:
    """Append one §6 E4 override entry in the structured form this module parses.

    Deliberately does NOT decide whether an override is warranted -- E4 is
    explicit that only a literal typed `OVERRIDE: <reason>` from the user
    creates one, never an inference from a close paraphrase. This function is
    the writer for that moment, not the judge of it.
    """
    code = code.upper()
    if code not in REASON_CODES:
        raise OverrideError(f"{code} is not in the closed set: {', '.join(REASON_CODES)}")
    if not reason.strip():
        raise OverrideError("An override needs a reason — 'I feel tired' is not one, and neither is blank.")

    path = path or cfg.OVERRIDES_LOG_PATH
    day = day or date.today()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n## {day.strftime('%d-%m')} · {code}\n\n{reason.strip()}\n"
    with path.open("a") as f:
        f.write(entry)
    return entry


# --- plain language -----------------------------------------------------------------


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def format_report(report: DriftReport) -> list[str]:
    """Sentences, in the order that matters if you only read the first one.

    §6 E3: never soften the framing. If the shortfall is real it goes first,
    stated in miles.
    """
    lines: list[str] = []
    window = f"Last {report.weeks} weeks ({report.since.strftime('%d-%m')} to {report.until.strftime('%d-%m')})"

    if report.days_logged == 0:
        return [f"{window}: nothing logged yet — no drift to report."]

    pct = report.compliance_pct
    if pct is not None and pct < 100:
        lines.append(
            f"{window}: you ran {report.actual_mi:g} of {report.proposed_mi:g} planned miles "
            f"({pct}%) — {report.proposed_mi - report.actual_mi:.1f}mi short."
        )
    elif pct is not None:
        lines.append(
            f"{window}: you ran {report.actual_mi:g} of {report.proposed_mi:g} planned miles ({pct}%)."
        )
    else:
        lines.append(f"{window}: {_plural(report.days_logged, 'day')} logged.")

    if report.deviations:
        missed = [d for d in report.deviations if d.missed_entirely]
        detail = ", ".join(f"{d.day} ({d.shortfall_mi:+g}mi)" for d in report.deviations[:6])
        more = "" if len(report.deviations) <= 6 else f", +{len(report.deviations) - 6} more"
        lines.append(
            f"{_plural(len(report.deviations), 'day')} of {report.days_logged} differed from plan by "
            f"more than {DEVIATION_TOLERANCE_MI:g}mi: {detail}{more}."
        )
        if missed:
            lines.append(f"Of those, {_plural(len(missed), 'day was', 'days were')} not run at all: "
                         f"{', '.join(d.day for d in missed)}.")
    else:
        lines.append(f"No day differed from plan by more than {DEVIATION_TOLERANCE_MI:g}mi.")

    if report.code_mentions:
        ranked = sorted(report.code_mentions.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        parts = [f"{code} on {', '.join(days)}" for code, days in ranked]
        lines.append("Reasons mentioned: " + "; ".join(parts) + ".")
        lines.append(
            "[These are counted by scanning the log's free text for the closed-set codes, "
            "so they're mentions, not a structured tally.]"
        )

    if report.overrides is None:
        lines.append(
            "Overrides: not tracked yet — context/overrides.md has no entries, so this is "
            "'nothing recorded', not a confident zero. `mc override` writes them."
            if report.override_log_exists
            else "Overrides: context/overrides.md is missing entirely."
        )
    else:
        n = len(report.overrides)
        lines.append(
            f"Overrides: {n} of the {OVERRIDE_LIMIT_PER_BLOCK} that trigger a structural review "
            f"({', '.join(f'{d} {c}' for d, c in report.overrides)})."
        )
        if report.over_override_limit:
            lines.append(
                f"That is over the limit. §6 E5: the plan is not matching real life — the answer "
                f"is a structural revision for approval, not another override."
            )

    return lines
