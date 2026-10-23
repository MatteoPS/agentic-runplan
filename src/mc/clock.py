"""What day it is — which is not the same question as what the machine thinks.

`mc render --all` deleted `out/today.md` on the evening of 24-08-2026. Nothing
was wrong with `tidy`: the file declared `24-08`, the clock said `25-08`, and a
file whose day has passed is deleted. The clock was wrong. This project now
runs from a cloud container whose timezone is UTC, and from 20:00 Eastern
onward UTC has already ticked into tomorrow — so for the four hours that
`/preview` lives in, every `date.today()` in this codebase named the wrong day.

The damage that window does is not limited to one deletion. `mc log` files the
evening's session under tomorrow, `mc propose` writes the prescription onto
tomorrow's row, the training-log backfill marks *today* "Nothing logged"
because it believes today is over, and the one-`/daily`-per-day guard compares
`today.md`'s header against a day that hasn't started. All of it silent, all of
it only in the evening, which is exactly the kind of bug that gets explained
away as a one-off three times before anyone catches it.

**The training day is a civil day where the athlete is**, and that is a fact
about the athlete rather than about the machine, so it is configured rather
than sensed. `MC_TZ` names it; the default is `America/New_York`, which is home
and where the race is. The Italy block (weeks 8-9) is the case that makes this
worth a module: for three weeks the athlete is on `Europe/Rome`, six hours
ahead of New York, so anything before 06:00 there — a dawn long run to beat the
heat, exactly what that block is for — falls on the *previous* New York day.
Pinning the home zone would be the same bug mirrored, so the trip sets
`MC_TZ=Europe/Rome`, and every command that prints a date names the zone it
used.

**Why a module and not just `TZ=America/New_York` in the environment.** The env
var is set too (in the SessionStart hook, for cloud sessions), because bash
`date`, git commit timestamps and `Lease.describe()` should agree with `mc`.
But it can only ever be as reliable as whatever applies it: a trigger-fired
session, a plain shell in the container, or a runner that ignores the hook is
silently back to UTC, and nothing says so. `MC_TZ` is read here, at the point of
use, and printed. Belt, and separately, braces.

Deliberately *not* derived from the GPS fix `mc weather` already resolves. That
would follow travel automatically, but it costs a ~40MB timezone-boundary
dependency and is wrong on precisely the days that matter — a flight day, when
the most recent fix is still the country being left.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Imported for its side effect: config.py calls load_dotenv() at import, which
# is what lets MC_TZ be set in .env on the laptop. (TZ cannot be, without
# time.tzset() -- another reason the day is resolved here rather than by libc.)
from mc import config as cfg  # noqa: F401

# Home, and where the race is. An explicit default beats reading the system
# clock: the machine that is wrong about this is precisely the one with no
# opinion of its own (a container, in UTC), so falling back to it would fail
# open in the only place the bug exists.
DEFAULT_TZ = "America/New_York"

TZ_ENV = "MC_TZ"


@dataclass(frozen=True)
class Zone:
    """The zone in use, and whether it is the one that was asked for."""

    name: str
    tz: tzinfo
    fell_back: bool

    @property
    def label(self) -> str:
        return f"{self.name} (requested, not found — using the system clock)" if self.fell_back else self.name


def requested_tz_name() -> str:
    return (os.environ.get(TZ_ENV) or "").strip() or DEFAULT_TZ


def resolve() -> Zone:
    """The training timezone, falling back loudly rather than crashing.

    A machine with no tz database is a real possibility (a stripped container,
    a Windows checkout without `tzdata`), and refusing to run the 6am ritual
    over it would be worse than the bug this module fixes. Falling back
    *silently* would be worse than either -- hence `fell_back`, which every
    caller that prints a date passes on.
    """
    name = requested_tz_name()
    try:
        return Zone(name=name, tz=ZoneInfo(name), fell_back=False)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return Zone(name=name, tz=system_tz(), fell_back=True)


def training_tz() -> tzinfo:
    return resolve().tz


def system_tz() -> tzinfo:
    """Whatever the machine believes, which is what this module exists to stop
    trusting by default."""
    local = datetime.now().astimezone().tzinfo
    assert local is not None  # astimezone() always attaches one
    return local


def now() -> datetime:
    """Timezone-aware, always. A naive datetime here would be the same class of
    bug one layer down."""
    return datetime.now(training_tz())


def today() -> date:
    return now().date()


def system_today() -> date:
    return date.today()


def system_disagrees() -> bool:
    return system_today() != today()


def describe(as_of: date | None = None) -> str:
    """One line: the day, its weekday, and the zone it came from.

    The zone is named every time rather than only when it is surprising --
    "unlabelled means New York" is a convention a reader has no way to know,
    the same argument §7 makes about naming the source of every reading.
    """
    day = as_of or today()
    return f"{day.strftime('%d-%m')} · {day.strftime('%A')} · {resolve().label}"


def system_note() -> str | None:
    """The warning line, or None when the two clocks agree.

    Only interesting when they differ -- which in the cloud is every evening
    after 20:00 Eastern, and is what a reader needs to see before wondering
    why `date` and `mc` disagree.
    """
    if not system_disagrees():
        return None
    system = datetime.now().astimezone()
    direction = "a day ahead" if system.date() > today() else "a day behind"
    return (
        f"system clock says {system.strftime('%d-%m %H:%M')} "
        f"{system.tzname()} — {direction}. mc is using the training day above."
    )
