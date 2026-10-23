"""out/ must hold only files that are current.

The failure these guard against is not a crash -- it is a stale file that
looks exactly like a fresh one on a phone screen at 6am.
"""

import subprocess
from datetime import date, timedelta

import pytest

from mc import config as cfg
from mc import tidy


TODAY = date(2026, 8, 8)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def ddmm(d: date) -> str:
    return d.strftime("%d-%m")


@pytest.fixture
def out(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    return d


def write(out, name: str, header: date | None = None, body: str = "body") -> None:
    text = f"# {ddmm(header)} · session\n\n{body}\n" if header else f"{body}\n"
    (out / name).write_text(text)


# --- header-dated files ------------------------------------------------------------


def test_yesterdays_today_md_is_removed(out):
    write(out, "today.md", header=YESTERDAY)
    result = tidy.tidy(out, as_of=TODAY)
    assert [r.name for r in result.removed] == ["today.md"]
    assert not (out / "today.md").exists()


def test_todays_today_md_survives(out):
    write(out, "today.md", header=TODAY)
    assert tidy.tidy(out, as_of=TODAY).removed == []
    assert (out / "today.md").exists()


def test_tomorrow_md_written_last_night_survives_through_its_day(out):
    """/preview writes it the evening before, so its header names tomorrow --
    and it stays valid through the day it actually describes."""
    write(out, "tomorrow.md", header=TOMORROW)
    assert tidy.tidy(out, as_of=TODAY).removed == []
    write(out, "tomorrow.md", header=TODAY)
    assert tidy.tidy(out, as_of=TODAY).removed == []


def test_tomorrow_md_superseded_by_todays_today_md_is_removed(out):
    """/preview wrote tomorrow.md headed for today; /daily has since run and
    written today.md for that same day. Keeping both would put two files
    headed with today's date in out/, one of them still called
    "tomorrow.md" -- the projection is superseded, not merely early."""
    write(out, "today.md", header=TODAY)
    write(out, "tomorrow.md", header=TODAY)
    result = tidy.tidy(out, as_of=TODAY)
    assert [r.name for r in result.removed] == ["tomorrow.md"]
    assert (out / "today.md").exists()
    assert not (out / "tomorrow.md").exists()


def test_tomorrow_md_from_two_days_ago_is_removed(out):
    write(out, "tomorrow.md", header=TODAY - timedelta(days=2))
    assert [r.name for r in tidy.tidy(out, as_of=TODAY).removed] == ["tomorrow.md"]


def test_provisional_file_that_wont_say_its_day_is_removed(out):
    """render.is_stale's reasoning, kept: a projection that won't name the day
    it is for cannot be trusted, so absence of a header is itself the answer."""
    write(out, "tomorrow.md", header=None)
    assert [r.name for r in tidy.tidy(out, as_of=TODAY).removed] == ["tomorrow.md"]


# --- filename-dated one-offs -------------------------------------------------------


def test_dated_one_off_survives_its_own_day(out):
    write(out, f"race-strategy-{ddmm(TODAY)}.md", header=None)
    assert tidy.tidy(out, as_of=TODAY).removed == []


def test_dated_one_off_expires_the_day_after(out):
    name = f"race-strategy-{ddmm(YESTERDAY)}.md"
    write(out, name, header=None)
    assert [r.name for r in tidy.tidy(out, as_of=TODAY).removed] == [name]


def test_header_beats_filename(out):
    """We believe the file over its filename -- same precedent as
    push._check_today_md_date."""
    write(out, f"notes-{ddmm(YESTERDAY)}.md", header=TODAY)
    assert tidy.tidy(out, as_of=TODAY).removed == []


# --- html twins --------------------------------------------------------------------


def test_orphan_html_is_removed(out):
    (out / "gone.html").write_text("<h1>gone</h1>")
    assert [r.name for r in tidy.tidy(out, as_of=TODAY).removed] == ["gone.html"]


def test_html_older_than_its_markdown_is_removed(out):
    """This is what retires the HTML set now that markdown is the default:
    stop regenerating them and they age out on the next tidy."""
    (out / "today.html").write_text("<h1>old</h1>")
    write(out, "today.md", header=TODAY)
    import os

    old = (out / "today.md").stat().st_mtime - 100
    os.utime(out / "today.html", (old, old))
    assert [r.name for r in tidy.tidy(out, as_of=TODAY).removed] == ["today.html"]


def test_fresh_html_twin_survives(out):
    write(out, "today.md", header=TODAY)
    (out / "today.html").write_text("<h1>fresh</h1>")
    assert tidy.tidy(out, as_of=TODAY).removed == []


def test_removing_a_stale_md_takes_its_twin(out):
    write(out, "today.md", header=YESTERDAY)
    (out / "today.html").write_text("<h1>stale</h1>")
    names = {r.name for r in tidy.tidy(out, as_of=TODAY).removed}
    assert names == {"today.md", "today.html"}


# --- what tidy must never touch ----------------------------------------------------


def test_dashboard_md_is_exempt(out):
    """A rolling view of the whole plan, not a document about a day -- it has
    no date to go stale against, and render --all rewrites it every run."""
    write(out, "dashboard.md", header=None)
    assert tidy.tidy(out, as_of=TODAY).removed == []
    assert (out / "dashboard.md").exists()


def test_undated_markdown_is_reported_not_deleted(out):
    write(out, "scratch.md", header=None)
    result = tidy.tidy(out, as_of=TODAY)
    assert result.removed == []
    assert [p.name for p in result.undated] == ["scratch.md"]
    assert (out / "scratch.md").exists()


def test_dry_run_deletes_nothing(out):
    write(out, "today.md", header=YESTERDAY)
    result = tidy.tidy(out, as_of=TODAY, dry_run=True)
    assert [r.name for r in result.removed] == ["today.md"]
    assert (out / "today.md").exists()


def test_missing_out_dir_is_not_an_error(tmp_path):
    assert tidy.tidy(tmp_path / "nope", as_of=TODAY).removed == []


# --- the reason has to be true -----------------------------------------------------


def test_reasons_distinguish_why_each_file_went(out):
    """A deletion notice giving the wrong reason is the same failure this
    module exists to prevent, one step removed."""
    write(out, "today.md", header=YESTERDAY)
    (out / "today.html").write_text("<h1>twin of a dead file</h1>")
    (out / "orphan.html").write_text("<h1>no source</h1>")
    write(out, "dashboard.md", header=None)
    (out / "dashboard.html").write_text("<h1>superseded</h1>")
    import os

    old = (out / "dashboard.md").stat().st_mtime - 100
    os.utime(out / "dashboard.html", (old, old))

    reasons = {r.name: r.reason for r in tidy.tidy(out, as_of=TODAY).removed}
    assert reasons["today.md"] == "its day has passed"
    assert reasons["today.html"] == "the markdown it renders is gone"
    assert reasons["orphan.html"] == "no markdown source"
    assert reasons["dashboard.html"] == "older than dashboard.md"


# --- git holds it, or it doesn't go ------------------------------------------------
#
# /daily writes today.md, runs `mc render --all` (which tidies) and only then
# runs `mc state --save`. Everything deleted in that window is deleted before
# git has a copy, so "the history is the durable record" -- the justification
# for deleting at all -- is briefly false. On 24-08-2026 a clock a day ahead
# walked straight into it.


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo_out(tmp_path, monkeypatch):
    """An out/ inside a real git repo, with cfg.STATE_ROOT pointing at it."""
    root = tmp_path / "state"
    (root / "out").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "Test")
    monkeypatch.setattr(cfg, "STATE_ROOT", root)
    return root / "out"


def test_an_uncommitted_stale_file_is_kept_and_reported(repo_out):
    write(repo_out, "today.md", header=YESTERDAY)
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert [p.name for p in result.protected] == ["today.md"]
    assert result.removed == []
    assert (repo_out / "today.md").exists()


def test_a_committed_stale_file_still_goes(repo_out):
    write(repo_out, "today.md", header=YESTERDAY)
    git(repo_out.parent, "add", "-A")
    git(repo_out.parent, "commit", "-q", "-m", "save the day")
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert [r.name for r in result.removed] == ["today.md"]
    assert not (repo_out / "today.md").exists()


def test_uncommitted_edits_to_a_tracked_file_are_protected_too(repo_out):
    """Committed yesterday, rewritten since: the deletion would lose the edit,
    not just the file."""
    write(repo_out, "today.md", header=YESTERDAY)
    git(repo_out.parent, "add", "-A")
    git(repo_out.parent, "commit", "-q", "-m", "save the day")
    write(repo_out, "today.md", header=YESTERDAY, body="rewritten after the save")
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert [p.name for p in result.protected] == ["today.md"]
    assert (repo_out / "today.md").exists()


def test_html_twins_are_not_protected(repo_out):
    """Regenerable output. Protecting it would leave every uncommitted render
    in out/ forever, which is the accumulation this module exists to stop."""
    write(repo_out, "today.md", header=YESTERDAY)
    (repo_out / "today.html").write_text("<p>x</p>")
    git(repo_out.parent, "add", "-A")
    git(repo_out.parent, "commit", "-q", "-m", "save the day")
    (repo_out / "today.html").write_text("<p>regenerated, uncommitted</p>")
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert "today.html" in [r.name for r in result.removed]


def test_without_git_nothing_is_protected(out, monkeypatch):
    """MC_STATE_GIT=off or a plain checkout: the guarantee was always
    conditional on git, so the behaviour is unchanged rather than paralysed."""
    monkeypatch.setattr(cfg, "STATE_ROOT", out.parent)
    write(out, "today.md", header=YESTERDAY)
    result = tidy.tidy(out, as_of=TODAY)
    assert result.protected == []
    assert [r.name for r in result.removed] == ["today.md"]


def test_the_guard_covers_a_superseded_projection_too(repo_out):
    """Superseded and expired are different arguments for deleting; neither is
    an argument for deleting the only copy. /preview can leave an uncommitted
    tomorrow.md behind as easily as /daily can a today.md."""
    write(repo_out, "today.md", header=TODAY)
    write(repo_out, "tomorrow.md", header=TODAY)  # projected the day today.md now covers
    git(repo_out.parent, "add", "out/today.md")
    git(repo_out.parent, "commit", "-q", "-m", "today only")
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert [p.name for p in result.protected] == ["tomorrow.md"]
    assert (repo_out / "tomorrow.md").exists()

    git(repo_out.parent, "add", "-A")
    git(repo_out.parent, "commit", "-q", "-m", "and the projection")
    result = tidy.tidy(repo_out, as_of=TODAY)
    assert [r.name for r in result.removed] == ["tomorrow.md"]
