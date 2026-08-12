from datetime import date, datetime, timedelta, timezone

import pytest

from mc import weather


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("MC_WEATHER", "MC_WEATHER_LAT", "MC_WEATHER_LON", "MC_TEMP_UNIT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(weather.cfg, "RAW_WEATHER_DIR", tmp_path / "weather")


def payload(times, **series):
    hourly = {"time": times}
    hourly.update(series)
    return {"hourly": hourly}


def hours_for(day: str, temps: dict[int, tuple[float, float]]):
    """{hour: (feels_like, dew_point)} -> an Open-Meteo-shaped payload."""
    times = [f"{day}T{h:02d}:00" for h in sorted(temps)]
    return payload(
        times,
        temperature_2m=[temps[h][0] for h in sorted(temps)],
        apparent_temperature=[temps[h][0] for h in sorted(temps)],
        dew_point_2m=[temps[h][1] for h in sorted(temps)],
        relative_humidity_2m=[50] * len(temps),
        precipitation_probability=[0] * len(temps),
        precipitation=[0.0] * len(temps),
        wind_speed_10m=[5.0] * len(temps),
    )


# --- heat classification ---------------------------------------------------------


def test_cool_and_dry_is_no_heat():
    assert weather.heat_level(60.0, 45.0) is weather.HeatLevel.NONE


def test_worse_of_the_two_readings_wins():
    """A dry 95F afternoon is still extreme; a mild-feeling morning at a 73F
    dew point is too. Either alone is enough."""
    assert weather.heat_level(95.0, 45.0) is weather.HeatLevel.EXTREME
    assert weather.heat_level(68.0, 73.0) is weather.HeatLevel.EXTREME


def test_dew_point_bands():
    assert weather.heat_level(50.0, 61.0) is weather.HeatLevel.NOTICEABLE
    assert weather.heat_level(50.0, 66.0) is weather.HeatLevel.HARD
    assert weather.heat_level(50.0, 72.0) is weather.HeatLevel.EXTREME


def test_missing_readings_never_invent_heat():
    assert weather.heat_level(None, None) is weather.HeatLevel.NONE


def test_heat_vocabulary_stays_disjoint_from_section_4_verdicts():
    """§4's verdicts must never leak into this axis — "⚠️ aerobic only" cannot
    be allowed to start meaning "it's warm out"."""
    from mc import equivalence as eq

    section_4 = {
        eq.VERDICT_GOOD, eq.VERDICT_AEROBIC_ONLY,
        eq.VERDICT_NOT_RECOMMENDED, eq.VERDICT_NOT_A_SUBSTITUTE,
    }
    assert {level.value for level in weather.HeatLevel}.isdisjoint(section_4)


# --- units -----------------------------------------------------------------------


def test_fahrenheit_is_the_default():
    assert weather.temp_unit() == "fahrenheit"
    assert weather.fmt_temp(84.0) == "84°F"


def test_celsius_is_a_display_conversion(monkeypatch):
    monkeypatch.setenv("MC_TEMP_UNIT", "celsius")
    assert weather.fmt_temp(212.0) == "100°C"


def test_thresholds_are_unaffected_by_display_unit(monkeypatch):
    """Fahrenheit is canonical internally on purpose — the classification must
    not shift when someone flips the display for the Italy block."""
    before = weather.heat_level(85.0, 66.0)
    monkeypatch.setenv("MC_TEMP_UNIT", "celsius")
    assert weather.heat_level(85.0, 66.0) is before


def test_missing_temperature_renders_as_em_dash():
    assert weather.fmt_temp(None) == "—"


# --- location resolution ------------------------------------------------------------


def gps_activity(start, lat=40.7994235, lon=-73.9580446):
    return {"startTimeLocal": start, "startLatitude": lat, "startLongitude": lon}


def test_coordinates_are_rounded_before_leaving_the_machine():
    loc = weather.location_from_activities(
        [gps_activity("2026-08-03 20:13:06")], as_of=date(2026, 8, 4)
    )
    assert loc.lat == 40.8
    assert loc.lon == -73.96


def test_env_location_wins_over_inference(monkeypatch):
    monkeypatch.setenv("MC_WEATHER_LAT", "45.4642")
    monkeypatch.setenv("MC_WEATHER_LON", "9.1900")
    loc = weather.resolve_location([gps_activity("2026-08-03 20:13:06")], as_of=date(2026, 8, 4))
    assert (loc.lat, loc.lon) == (45.46, 9.19)
    assert loc.source == "MC_WEATHER_LAT/LON"


def test_env_location_is_also_rounded(monkeypatch):
    monkeypatch.setenv("MC_WEATHER_LAT", "40.799423")
    monkeypatch.setenv("MC_WEATHER_LON", "-73.958044")
    assert weather.resolve_location([], as_of=date(2026, 8, 4)).lat == 40.8


def test_most_recent_gps_activity_wins():
    """This is what follows the athlete to Italy without being told."""
    loc = weather.location_from_activities(
        [
            gps_activity("2026-08-01 07:00:00", lat=40.79, lon=-73.95),
            gps_activity("2026-08-03 20:13:06", lat=45.46, lon=9.19),
        ],
        as_of=date(2026, 8, 4),
    )
    assert (loc.lat, loc.lon) == (45.46, 9.19)
    assert "03-08" in loc.source


def test_indoor_activities_have_no_coordinates_and_are_skipped():
    assert (
        weather.location_from_activities(
            [{"startTimeLocal": "2026-08-03 20:13:06"}], as_of=date(2026, 8, 4)
        )
        is None
    )


def test_a_stale_gps_fix_is_not_used():
    """After two weeks indoors, the last fix is a poor guess at where you are."""
    assert (
        weather.location_from_activities(
            [gps_activity("2026-06-01 07:00:00")], as_of=date(2026, 8, 4)
        )
        is None
    )


def test_no_location_at_all_resolves_to_none():
    assert weather.resolve_location([], as_of=date(2026, 8, 4)) is None


def test_partial_env_config_falls_through_to_gps(monkeypatch):
    monkeypatch.setenv("MC_WEATHER_LAT", "45.46")  # no LON
    loc = weather.resolve_location([gps_activity("2026-08-03 20:13:06")], as_of=date(2026, 8, 4))
    assert loc.source.startswith("last GPS")


def test_unparseable_env_config_falls_through_to_gps(monkeypatch):
    monkeypatch.setenv("MC_WEATHER_LAT", "north-ish")
    monkeypatch.setenv("MC_WEATHER_LON", "9.19")
    loc = weather.resolve_location([gps_activity("2026-08-03 20:13:06")], as_of=date(2026, 8, 4))
    assert loc.source.startswith("last GPS")


# --- parsing -----------------------------------------------------------------------


def test_hours_parse_into_naive_local_times():
    hours = weather.hours_from_payload(hours_for("2026-08-05", {6: (70.0, 60.0)}))
    assert hours[0].when == datetime(2026, 8, 5, 6, 0)
    assert hours[0].when.tzinfo is None  # matches Garmin's startTimeLocal


def test_short_series_are_padded_rather_than_raising():
    """Never trust one provider array to match another's length."""
    hours = weather.hours_from_payload(
        payload(["2026-08-05T06:00", "2026-08-05T07:00"], temperature_2m=[70.0])
    )
    assert len(hours) == 2
    assert hours[1].temp_f is None


def test_unparseable_timestamps_are_dropped():
    assert weather.hours_from_payload(payload(["not-a-time"])) == []


def test_empty_payload_yields_no_hours():
    assert weather.hours_from_payload({}) == []


# --- windows ------------------------------------------------------------------------


def test_window_is_summarised_by_its_worst_hour():
    """A window is a commitment to be outside for all of it, so the average
    would recommend a run that doesn't survive contact with 07:45."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-05", {5: (60.0, 50.0), 6: (65.0, 52.0), 7: (85.0, 55.0)})
    )
    early = weather.windows_for_day(hours, date(2026, 8, 5))[0]
    assert early.feels_like_f == 85.0


def test_windows_without_data_are_omitted():
    hours = weather.hours_from_payload(hours_for("2026-08-05", {6: (65.0, 50.0)}))
    names = {w.name for w in weather.windows_for_day(hours, date(2026, 8, 5))}
    assert names == {"early"}


def test_other_days_do_not_leak_into_a_window():
    hours = weather.hours_from_payload(hours_for("2026-08-06", {6: (65.0, 50.0)}))
    assert weather.windows_for_day(hours, date(2026, 8, 5)) == []


def test_best_window_prefers_the_lower_heat_level():
    hours = weather.hours_from_payload(
        hours_for(
            "2026-08-05",
            {6: (70.0, 55.0), 9: (84.0, 66.0), 12: (95.0, 68.0), 18: (86.0, 70.0)},
        )
    )
    best = weather.best_window(weather.windows_for_day(hours, date(2026, 8, 5)))
    assert best.name == "early"
    assert best.heat is weather.HeatLevel.NONE


def test_best_window_breaks_ties_toward_the_earlier_slot():
    hours = weather.hours_from_payload(
        hours_for("2026-08-05", {6: (70.0, 55.0), 18: (70.0, 55.0)})
    )
    best = weather.best_window(weather.windows_for_day(hours, date(2026, 8, 5)))
    assert best.name == "early"


def test_best_window_of_nothing_is_none():
    assert weather.best_window([]) is None


# --- sub-windows ----------------------------------------------------------------------
#
# The regression these exist for: the 12-08-2026 evening window read 86°F (its
# 17:00-19:00 plateau) while the 20:15 slot a 4-mile run would actually use was
# 80°F, and nothing in the output said so.


def _evening_12_08():
    """The real 12-08-2026 evening forecast, to the degree."""
    return weather.hours_from_payload(
        hours_for(
            "2026-08-12",
            {17: (86.0, 53.0), 18: (86.0, 54.0), 19: (86.0, 55.0), 20: (80.0, 61.0), 21: (78.0, 64.0)},
        )
    )


def _window_named(hours, day, name):
    return next(w for w in weather.windows_for_day(hours, day) if w.name == name)


def test_the_post_sunset_slot_is_found_inside_a_hot_evening_window():
    hours = _evening_12_08()
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    assert evening.feels_like_f == 86.0  # the window is still worst-hour

    slot = weather.sub_window_finding(hours, evening)
    assert slot is not None
    assert (slot.start_hour, slot.end_hour) == (20, 21)
    assert slot.feels_like_f == 80.0


def test_a_flat_window_reports_no_slot():
    """Most windows, most days. Returning None is the common case by design."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-12", {17: (84.0, 60.0), 18: (85.0, 61.0), 19: (86.0, 60.0), 20: (85.0, 61.0), 21: (84.0, 60.0)})
    )
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    assert weather.sub_window_finding(hours, evening) is None


def test_a_label_flip_on_a_stray_degree_is_not_a_finding():
    """The 12-08 early window: 74°F/65°F dew against 72°F/63°F an hour later.
    Two degrees straddling the HARD dew-point boundary flips the heat level,
    and that is exactly the bracket artifact this feature exists to see
    through — not a reason to tell anyone to move their run."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-12", {5: (74.0, 65.0), 6: (72.0, 63.0), 7: (72.0, 63.0), 8: (74.0, 63.0)})
    )
    early = _window_named(hours, date(2026, 8, 12), "early")
    assert early.heat is weather.HeatLevel.HARD
    coolest = weather.coolest_slot(hours, early)
    assert coolest.heat is weather.HeatLevel.NOTICEABLE  # the level does improve
    assert weather.sub_window_finding(hours, early) is None  # and it doesn't matter


def test_a_dew_point_swing_alone_qualifies():
    """Feels-like flat, dew point steep — a real difference the feels-like
    test alone would miss."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-12", {17: (82.0, 72.0), 18: (82.0, 71.0), 19: (82.0, 68.0), 20: (82.0, 64.0), 21: (81.0, 63.0)})
    )
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    slot = weather.sub_window_finding(hours, evening)
    assert slot is not None
    assert slot.dew_point_f == 64.0


def test_a_slot_is_bounded_by_both_its_endpoints():
    """20:00-21:00 means being outside at 21:00 too, so the worst of the pair
    bounds it — the same inclusive convention windows_for_day uses."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-12", {17: (95.0, 70.0), 18: (95.0, 70.0), 19: (95.0, 70.0), 20: (70.0, 55.0), 21: (90.0, 68.0)})
    )
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    slot = weather.coolest_slot(hours, evening)
    assert slot.feels_like_f == 90.0  # not the 70.0 at 20:00 alone


def test_ranking_ignores_heat_level_and_uses_the_numbers():
    """coolest_slot deliberately diverges from best_window here."""
    hours = weather.hours_from_payload(
        hours_for("2026-08-12", {17: (76.0, 66.0), 18: (76.0, 66.0), 19: (90.0, 64.0), 20: (90.0, 64.0), 21: (90.0, 64.0)})
    )
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    slot = weather.coolest_slot(hours, evening)
    # 19:00+ is a whole heat level cooler by dew point, and 14°F hotter.
    assert (slot.start_hour, slot.feels_like_f) == (17, 76.0)


def test_a_window_with_one_slot_reports_nothing():
    """Nothing to choose between when the only slot *is* the whole window —
    repeating it back as a finding would be noise dressed as advice."""
    hours = weather.hours_from_payload(hours_for("2026-08-12", {8: (70.0, 50.0), 9: (90.0, 70.0)}))
    one_hour_wide = weather.Window(
        name="morning", day=date(2026, 8, 12), start_hour=8, end_hour=9,
        feels_like_f=90.0, dew_point_f=70.0, precip_prob=0.0, wind_mph=5.0,
    )
    assert weather.coolest_slot(hours, one_hour_wide) is not None
    assert weather.sub_window_finding(hours, one_hour_wide) is None


def test_missing_readings_never_manufacture_a_finding():
    hours = weather.hours_from_payload(
        payload(
            [f"2026-08-12T{h:02d}:00" for h in (17, 18, 19, 20, 21)],
            apparent_temperature=[None] * 5,
            dew_point_2m=[None] * 5,
        )
    )
    evening = _window_named(hours, date(2026, 8, 12), "evening")
    assert weather.sub_window_finding(hours, evening) is None


def test_the_digest_carries_the_slot_under_its_window():
    hours = _evening_12_08()
    envelope = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": 40.82, "lon": -73.95, "source": "test"},
        "data": {
            "hourly": {
                "time": [h.when.isoformat() for h in hours],
                "apparent_temperature": [h.feels_like_f for h in hours],
                "dew_point_2m": [h.dew_point_f for h in hours],
            }
        },
    }
    lines = weather.digest_lines(date(2026, 8, 12), envelope)
    slot_lines = [ln for ln in lines if "short session" in ln]
    assert len(slot_lines) == 1
    assert "20:00–21:00" in slot_lines[0]
    # and it says why the window figure differs, rather than just contradicting it
    assert "worst hour" in slot_lines[0]


# --- enable / disable ----------------------------------------------------------------


def test_weather_is_on_by_default():
    assert weather.enabled()


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_weather_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv("MC_WEATHER", value)
    assert not weather.enabled()


def test_disabled_sync_makes_no_call_and_reports_why(monkeypatch):
    monkeypatch.setenv("MC_WEATHER", "off")
    monkeypatch.setattr(
        weather, "fetch", lambda *a, **k: pytest.fail("must not call the network")
    )
    report = weather.sync_weather([])
    assert not report.attempted
    assert "disabled" in report.error


def test_sync_without_a_location_makes_no_call(monkeypatch):
    monkeypatch.setattr(
        weather, "fetch", lambda *a, **k: pytest.fail("must not call the network")
    )
    report = weather.sync_weather([])
    assert not report.attempted and not report.ok
    assert "no location" in report.error


def test_a_fetch_failure_is_reported_not_raised(monkeypatch):
    """A failed forecast must never make a successful Garmin pull look failed."""

    def boom(*a, **k):
        raise weather.WeatherConnectionError("network down")

    monkeypatch.setattr(weather, "fetch", boom)
    report = weather.sync_weather([gps_activity(datetime.now().strftime("%Y-%m-%d 07:00:00"))])
    assert report.attempted and not report.ok
    assert "network down" in report.error
    assert report.location_source is not None  # still says where it tried


# --- cache ----------------------------------------------------------------------------


def test_missing_cache_reads_as_none():
    assert weather.load_cached() is None


def test_corrupt_cache_reads_as_none_rather_than_raising():
    path = weather.cfg.RAW_WEATHER_DIR / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert weather.load_cached() is None


def test_cache_age_is_measured_from_fetched_at():
    two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert round(weather.cache_age_hours({"fetched_at": two_hours_ago})) == 2


def test_cache_age_of_nothing_is_none():
    assert weather.cache_age_hours(None) is None
    assert weather.cache_age_hours({}) is None


# --- digest rendering --------------------------------------------------------------------


def envelope_for(hourly_payload, fetched_at=None, source="last GPS activity 03-08"):
    return {
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "location": {"lat": 40.8, "lon": -73.96, "source": source},
        "data": hourly_payload,
    }


def test_digest_states_the_location_source_every_time():
    lines = weather.digest_lines(date(2026, 8, 4), envelope_for(hours_for("2026-08-04", {6: (70.0, 55.0)})))
    assert any("last GPS activity 03-08" in line for line in lines)


def test_digest_marks_a_stale_forecast_in_bold():
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    lines = weather.digest_lines(
        date(2026, 8, 4), envelope_for(hours_for("2026-08-04", {6: (70.0, 55.0)}), fetched_at=old)
    )
    assert any("STALE" in line and line.startswith("- **") for line in lines)


def test_digest_covers_today_and_tomorrow():
    hourly = hours_for("2026-08-04", {6: (70.0, 55.0)})
    hourly["hourly"]["time"].append("2026-08-05T06:00")
    for key, value in (
        ("temperature_2m", 72.0), ("apparent_temperature", 72.0), ("dew_point_2m", 56.0),
        ("relative_humidity_2m", 50), ("precipitation_probability", 0),
        ("precipitation", 0.0), ("wind_speed_10m", 5.0),
    ):
        hourly["hourly"][key].append(value)
    lines = weather.digest_lines(date(2026, 8, 4), envelope_for(hourly))
    assert any("Today (04-08)" in line for line in lines)
    assert any("Tomorrow (05-08)" in line for line in lines)


def test_digest_says_so_when_nothing_is_cached():
    assert any("No weather cached" in line for line in weather.digest_lines(date(2026, 8, 4)))


def test_digest_never_presents_heat_as_a_rule_trigger():
    lines = weather.digest_lines(date(2026, 8, 4), envelope_for(hours_for("2026-08-04", {6: (70.0, 55.0)})))
    assert any("C2 is a permission" in line for line in lines)
