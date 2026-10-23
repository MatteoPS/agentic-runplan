"""The training day is the athlete's day, not the container's.

The bug these guard against ran for four hours every evening and left no trace
except a deleted file: UTC ticks into tomorrow at 20:00 Eastern, so `mc tidy`
deleted a live `out/today.md`, `mc log` filed the evening under tomorrow, and
the backfill marked the current day "Nothing logged" because it believed the
day was over.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mc import clock


@pytest.fixture(autouse=True)
def clear_tz(monkeypatch):
    monkeypatch.delenv(clock.TZ_ENV, raising=False)


def test_default_zone_is_home():
    assert clock.requested_tz_name() == clock.DEFAULT_TZ == "America/New_York"


def test_mc_tz_overrides(monkeypatch):
    monkeypatch.setenv(clock.TZ_ENV, "Europe/Rome")
    assert clock.resolve().name == "Europe/Rome"
    assert not clock.resolve().fell_back


def test_the_evening_the_container_is_already_tomorrow(monkeypatch):
    """21:00 in New York on the 24th is 01:00 UTC on the 25th. The training day
    is the 24th, and this is the entire bug in one assertion."""
    utc_evening = datetime(2026, 8, 25, 1, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(clock, "now", lambda: utc_evening.astimezone(clock.training_tz()))
    assert clock.today() == date(2026, 8, 24)
    assert utc_evening.date() == date(2026, 8, 25)


def test_italy_is_the_mirror_image(monkeypatch):
    """Rome runs 6h ahead of New York, so anything before 06:00 there falls on
    the previous New York day — an early long run to beat the heat is exactly
    the Italy case. Pinning home would be the same bug pointed the other way
    for three weeks."""
    monkeypatch.setenv(clock.TZ_ENV, "Europe/Rome")
    rome_dawn = datetime(2026, 9, 15, 5, 30, tzinfo=ZoneInfo("Europe/Rome"))
    assert rome_dawn.astimezone(ZoneInfo("America/New_York")).date() == date(2026, 9, 14)
    assert rome_dawn.astimezone(clock.training_tz()).date() == date(2026, 9, 15)


def test_now_is_always_aware():
    assert clock.now().tzinfo is not None


def test_an_unloadable_zone_falls_back_but_says_so(monkeypatch):
    """A stripped container without tzdata must not take the 6am ritual down.
    It must also not pretend the fallback is what was asked for."""
    monkeypatch.setenv(clock.TZ_ENV, "Mars/Olympus_Mons")
    zone = clock.resolve()
    assert zone.fell_back
    assert "not found" in zone.label
    assert "not found" in clock.describe()
    assert isinstance(clock.today(), date)


def test_describe_always_names_the_zone():
    """Unlabelled would have to mean New York, which is a convention a reader
    has no way to know (§7)."""
    assert clock.DEFAULT_TZ in clock.describe()


def test_system_note_is_silent_when_the_clocks_agree(monkeypatch):
    monkeypatch.setattr(clock, "today", clock.system_today)
    assert clock.system_note() is None


def test_system_note_names_the_direction_when_they_disagree(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: clock.system_today().replace(day=1) if clock.system_today().day != 1 else date(2000, 1, 2))
    note = clock.system_note()
    assert note is not None
    assert "day ahead" in note or "day behind" in note
