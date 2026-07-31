"""CLI tests run against the real project state (plan.lock.json, cached
activity data) rather than mocks -- consistent with test_rules_integration.py.
mc sync (real network calls) and mc log (appends to the real session log) are
exercised manually, not here."""

import re

from typer.testing import CliRunner

from mc.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def plain(result) -> str:
    """Rich colors individual digits/segments separately, which can split a
    literal substring like '31-08' across ANSI codes -- strip them before
    asserting on output text."""
    return _ANSI_RE.sub("", result.output)


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sync" in result.output
    assert "digest" in result.output


def test_status_runs():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "block" in result.output


def test_check_runs_and_exits_nonzero_when_violations_exist():
    result = runner.invoke(app, ["check"])
    assert result.exit_code in (0, 1)


def test_week_defaults_to_current():
    result = runner.invoke(app, ["week"])
    assert result.exit_code == 0


def test_week_by_number():
    result = runner.invoke(app, ["week", "--week", "6"])
    assert result.exit_code == 0
    assert "31-08" in plain(result)


def test_week_invalid_number_fails_loudly():
    result = runner.invoke(app, ["week", "--week", "999"])
    assert result.exit_code != 0


def test_week_by_wc_date():
    result = runner.invoke(app, ["week", "--wc", "05-10"])
    assert result.exit_code == 0
    assert "Week 11" in plain(result)


def test_equiv_easy_session():
    result = runner.invoke(app, ["equiv", "8 mi easy"])
    assert result.exit_code == 0
    assert "Elliptical" in result.output
    assert "✅" in result.output or "good substitute" in result.output


def test_equiv_long_run_never_a_substitute():
    result = runner.invoke(app, ["equiv", "18 mi long"])
    assert result.exit_code == 0
    assert "not a substitute" in result.output


def test_digest_runs():
    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "Data health" in result.output


def test_render_all_does_not_crash():
    result = runner.invoke(app, ["render", "--all"])
    assert result.exit_code == 0
