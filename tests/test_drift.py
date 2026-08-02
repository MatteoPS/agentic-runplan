from datetime import date

import pytest

from mc import drift


AS_OF = date(2026, 8, 2)


@pytest.fixture
def paths(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    overrides = tmp_path / "overrides.md"
    overrides.write_text("# Overrides log\n\nHeader prose, no entries.\n")
    return {
        "log_path": tmp_path / "training-log.md",
        "sessions_dir": sessions,
        "overrides_path": overrides,
    }


def write_log(paths, *rows: str):
    body = "# Training log\n\n| Date | Proposed | Actual |\n|---|---|---|\n" + "".join(rows)
    paths["log_path"].write_text(body)


def report(paths, **kw):
    return drift.build_report(as_of=AS_OF, **paths, **kw)


# --- parsing helpers ----------------------------------------------------------------


def test_actual_miles_sums_every_activity_that_day():
    """The Actual column is machine-written and lists all activities."""
    assert drift.actual_miles_in("run 4.0mi 38min; run 2.1mi 20min") == 6.1


def test_proposed_miles_takes_the_days_own_distance_only():
    """/daily often continues a Proposed cell into the rest of the week.
    Summing it would invent a shortfall out of thin air — this exact row is
    from the real training log."""
    row = ("Long run, already done this morning — 10.5mi (locked 11.0); "
           "Sat 01-08 3mi easy + fixed strength 2/2, Sun 02-08 2mi easy")
    assert drift.proposed_miles_in(row) == 10.5


def test_miles_handle_nothing_logged_and_blanks():
    assert drift.actual_miles_in("Nothing logged") == 0.0
    assert drift.proposed_miles_in("") == 0.0


def test_miles_ignore_minutes():
    assert drift.actual_miles_in("60min elliptical") == 0.0
    assert drift.proposed_miles_in("60min elliptical") == 0.0


def test_codes_are_matched_as_whole_uppercase_words():
    assert drift.codes_in("SHIN at 2, cut short") == ("SHIN",)
    # the lowercase English words must not become reason codes
    assert drift.codes_in("travel was fine and life is busy") == ()
    assert drift.codes_in("felt HEAT, and HEAT again") == ("HEAT",)


# --- compliance ---------------------------------------------------------------------


def test_reports_shortfall_in_miles(paths):
    write_log(
        paths,
        "| 30-07 | 8mi easy | run 8.0mi 78min |\n",
        "| 31-07 | 11mi long | run 10.5mi 100min |\n",
    )
    r = report(paths)
    assert r.proposed_mi == 19.0
    assert r.actual_mi == 18.5
    assert r.compliance_pct == 97
    assert "18.5 of 19 planned miles" in drift.format_report(r)[0]


def test_pending_rows_are_not_counted_as_shortfalls(paths):
    """A day that hasn't happened yet isn't a deviation — otherwise every
    report run in the morning would look bad."""
    write_log(paths, "| 30-07 | 8mi easy | run 8.0mi |\n", "| 02-08 | 5mi easy | *(pending)* |\n")
    r = report(paths)
    assert r.days_logged == 1
    assert r.proposed_mi == 8.0
    assert r.deviations == []


def test_rows_outside_the_window_are_excluded(paths):
    write_log(paths, "| 01-01 | 20mi | run 20.0mi |\n", "| 30-07 | 8mi | run 8.0mi |\n")
    assert report(paths, weeks=4).proposed_mi == 8.0


# --- deviations ---------------------------------------------------------------------


def test_small_gaps_are_not_deviations(paths):
    write_log(paths, "| 30-07 | 8mi easy | run 7.5mi 74min |\n")
    assert report(paths).deviations == []


def test_a_missed_day_is_flagged(paths):
    write_log(paths, "| 30-07 | 8mi easy | Nothing logged |\n")
    r = report(paths)
    assert len(r.deviations) == 1
    assert r.deviations[0].missed_entirely
    assert r.deviations[0].shortfall_mi == 8.0
    assert "not run at all" in " ".join(drift.format_report(r))


def test_deviation_picks_up_reason_codes_from_the_session_log(paths):
    write_log(paths, "| 30-07 | 8mi easy | run 3.0mi 30min |\n")
    (paths["sessions_dir"] / "2026-07-30.md").write_text("# 30-07\n\n- cut short, SHIN at 2\n")
    r = report(paths)
    assert r.deviations[0].codes == ("SHIN",)
    assert r.code_mentions["SHIN"] == ["30-07"]


def test_codes_are_ranked_by_frequency(paths):
    write_log(
        paths,
        "| 29-07 | 5mi | Nothing logged |\n",
        "| 30-07 | 5mi | Nothing logged |\n",
        "| 31-07 | 5mi | Nothing logged |\n",
    )
    for day, note in [("29", "SHIN"), ("30", "SHIN"), ("31", "TRAVEL")]:
        (paths["sessions_dir"] / f"2026-07-{day}.md").write_text(note)
    line = next(x for x in drift.format_report(report(paths)) if x.startswith("Reasons"))
    assert line.index("SHIN") < line.index("TRAVEL")


def test_mention_counting_is_labelled_as_imprecise(paths):
    write_log(paths, "| 30-07 | 5mi | Nothing logged |\n")
    (paths["sessions_dir"] / "2026-07-30.md").write_text("SHIN")
    assert any("mentions, not a structured tally" in x for x in drift.format_report(report(paths)))


# --- overrides: the honesty requirement ---------------------------------------------


def test_empty_override_log_reports_untracked_not_zero(paths):
    """A confident 0 from a file nothing writes to would be worse than
    admitting it isn't tracked."""
    write_log(paths, "| 30-07 | 8mi | run 8.0mi |\n")
    r = report(paths)
    assert r.overrides is None
    text = " ".join(drift.format_report(r))
    assert "not tracked yet" in text
    assert "0 of the 2" not in text


def test_written_overrides_are_counted(paths):
    write_log(paths, "| 30-07 | 8mi | run 8.0mi |\n")
    drift.append_override("TRAVEL", "flight at 06:00", day=date(2026, 7, 30), path=paths["overrides_path"])
    r = report(paths)
    assert r.overrides == [("30-07", "TRAVEL")]
    assert "1 of the 2" in " ".join(drift.format_report(r))


def test_exceeding_the_limit_says_structural_revision(paths):
    write_log(paths, "| 30-07 | 8mi | run 8.0mi |\n")
    for i, code in enumerate(["TRAVEL", "LIFE", "HEAT"]):
        drift.append_override(code, f"reason {i}", day=date(2026, 7, 28 + i), path=paths["overrides_path"])
    r = report(paths)
    assert r.over_override_limit
    assert "structural revision" in " ".join(drift.format_report(r))


def test_append_override_rejects_codes_outside_the_closed_set(paths):
    with pytest.raises(drift.OverrideError, match="closed set"):
        drift.append_override("TIRED", "just tired", path=paths["overrides_path"])


def test_append_override_rejects_a_blank_reason(paths):
    with pytest.raises(drift.OverrideError):
        drift.append_override("LIFE", "   ", path=paths["overrides_path"])


def test_append_override_preserves_existing_content(paths):
    drift.append_override("LIFE", "first", day=date(2026, 7, 30), path=paths["overrides_path"])
    drift.append_override("HEAT", "second", day=date(2026, 7, 31), path=paths["overrides_path"])
    text = paths["overrides_path"].read_text()
    assert "Overrides log" in text and "first" in text and "second" in text


# --- empty state --------------------------------------------------------------------


def test_no_log_at_all_says_so_plainly(paths):
    r = report(paths)
    assert drift.format_report(r) == [
        f"Last 4 weeks ({r.since.strftime('%d-%m')} to 02-08): nothing logged yet — no drift to report."
    ]
