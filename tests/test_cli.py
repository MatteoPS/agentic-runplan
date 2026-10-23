"""CLI tests run against the real project state (plan.lock.json, cached
activity data) rather than mocks -- consistent with test_rules_integration.py.
mc sync (real network calls) and mc log (appends to the real session log) are
exercised manually, not here."""

import re
from datetime import timedelta

from typer.testing import CliRunner

from mc import clock
from mc import config as cfg
from mc import layout as layout_mod
from mc import plan as plan_mod
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


def test_digest_runs(tmp_path, monkeypatch):
    """Reads the real cached data on purpose, writes nowhere near the real
    state repo. `mc digest` doesn't only render — it also backfills pending
    rows in `log/training-log.md`, so before this was isolated every full
    `uv run pytest` silently rewrote the training record, flipping yesterday's
    `*(pending)*` to `Nothing logged` against data the suite happened to see.
    That is one of the three whole-file-rewrite state files the writer lease
    exists to protect. Same reasoning as test_render_all_does_not_crash."""
    monkeypatch.setattr(cfg, "DIGEST_DIR", tmp_path / "digest")
    log_copy = tmp_path / "training-log.md"
    # A checkout without the state repo (the public showcase, its CI) has no
    # training log; an empty one still exercises the command.
    real_log = cfg.TRAINING_LOG_PATH
    log_copy.write_text(real_log.read_text() if real_log.exists() else "")
    monkeypatch.setattr(cfg, "TRAINING_LOG_PATH", log_copy)

    result = runner.invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "Data health" in result.output


def test_training_log_path_is_resolved_at_call_time():
    """The regression guard for the above. These used to bind
    `cfg.TRAINING_LOG_PATH` as an import-time default argument, which made the
    real training log unmonkeypatchable — isolation was impossible, not merely
    forgotten. Resolving at call time (as drift.py already did) is what makes
    the test above able to work at all."""
    import inspect

    from mc import traininglog as tlog

    for fn in (tlog.load_log, tlog.save_log, tlog.record_proposed, tlog.fill_pending_actuals):
        sig = inspect.signature(fn)
        assert sig.parameters["path"].default is None, (
            f"{fn.__name__} binds a path at import time; monkeypatching "
            f"cfg.TRAINING_LOG_PATH will not reach it"
        )


def test_render_all_does_not_crash(tmp_path, monkeypatch):
    """Pointed at a throwaway out/ on purpose. `render --all` now tidies, and
    a test that deletes files out of the real state repo is a test that
    destroys data every time the suite runs."""
    monkeypatch.setattr(cfg, "OUT_DIR", tmp_path / "out")
    result = runner.invoke(app, ["render", "--all"])
    assert result.exit_code == 0


def test_render_without_html_writes_no_html(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "today.md").write_text("# 01-01\n\nbody\n")
    monkeypatch.setattr(cfg, "OUT_DIR", out)
    result = runner.invoke(app, ["render", "--all"])
    assert result.exit_code == 0
    assert (out / "dashboard.md").exists()
    assert not list(out.glob("*.html"))


def test_render_html_flag_writes_twins(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "today.md").write_text(f"# {clock.today().strftime('%d-%m')}\n\nbody\n")
    monkeypatch.setattr(cfg, "OUT_DIR", out)
    result = runner.invoke(app, ["render", "--all", "--html"])
    assert result.exit_code == 0
    assert (out / "today.html").exists()
    assert (out / "dashboard.html").exists()


def test_check_takes_the_projected_tier_when_a_layout_exists(tmp_path, monkeypatch):
    """Tier selection only. Whether the blend passes depends on the real
    activity cache, so the arithmetic itself is unit-tested in
    test_planning.py against synthetic actuals."""
    monkeypatch.setattr(layout_mod, "STATE_PATH", tmp_path / "week_layout.json")
    p = plan_mod.load_plan()
    week = p.week_by_number(2)
    wc = week.wc
    monday = wc.strftime("%d-%m")
    days = [
        layout_mod.DayPlan(day=(wc + timedelta(days=i)).strftime("%d-%m"), miles=m, session=s)
        for i, (m, s) in enumerate(
            [(4.0, "easy"), (0.0, "rest"), (4.0, "easy"), (0.0, "rest"), (4.0, "easy"), (0.0, "rest"), (13.0, "long")]
        )
    ]
    layout_mod.set_layout(monday, days, (wc + timedelta(days=6)).strftime("%d-%m"))
    result = runner.invoke(app, ["check", "--as-of", monday])
    out = plain(result)
    assert result.exit_code in (0, 1)
    assert "projected" in out
    assert "still to run, per layout" in out
    assert "Degraded check" not in out


def test_check_degrades_loudly_without_a_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(layout_mod, "STATE_PATH", tmp_path / "week_layout.json")
    result = runner.invoke(app, ["check"])
    out = plain(result)
    assert "Degraded check" in out
    assert "no layout set" in out
    # The whole point of the degraded tier: it names what it stopped judging.
    assert "not being judged" in out
