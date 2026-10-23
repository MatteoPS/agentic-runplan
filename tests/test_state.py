import subprocess
from datetime import date

import pytest

from mc import clock
from mc import config as cfg
from mc import state


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path):
    """A bare 'remote' plus two clones — the laptop and the phone."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    laptop = tmp_path / "laptop"
    subprocess.run(["git", "clone", "-q", str(remote), str(laptop)], check=True)
    git(laptop, "config", "user.email", "t@example.com")
    git(laptop, "config", "user.name", "Test")
    (laptop / "log").mkdir()
    (laptop / "log" / "training-log.md").write_text("# Training log\n")
    git(laptop, "add", "-A")
    git(laptop, "commit", "-q", "-m", "init")
    git(laptop, "push", "-q", "-u", "origin", "HEAD")

    phone = tmp_path / "phone"
    subprocess.run(["git", "clone", "-q", str(remote), str(phone)], check=True)
    git(phone, "config", "user.email", "t@example.com")
    git(phone, "config", "user.name", "Test")
    return {"remote": remote, "laptop": laptop, "phone": phone}


@pytest.fixture
def split(monkeypatch, repos):
    """Pretend MC_STATE_DIR points at the laptop clone."""
    monkeypatch.setattr(cfg, "STATE_ROOT", repos["laptop"])
    monkeypatch.setattr(cfg, "state_is_split", lambda: True)
    return repos


@pytest.fixture
def merged(monkeypatch, repos):
    """Code and state in ONE repo — MC_STATE_DIR unset, so state_is_split() is
    False while the state still very much lives in a git repo with a remote.

    This is the shape the guard used to fail open on: it gated every piece of
    git work on is_split, so in a merged repo `mc state --save` released the
    lease, committed nothing, and returned None — silently.
    """
    monkeypatch.setattr(cfg, "STATE_ROOT", repos["laptop"])
    monkeypatch.setattr(cfg, "state_is_split", lambda: False)
    return repos


# --- no git repo: the guard must stay out of the way --------------------------------


def test_state_without_a_git_repo_is_never_blocked(monkeypatch, tmp_path):
    """Plain directory — nothing to guard, nothing to refuse."""
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    st = state.check(tmp_path)
    assert not st.is_git_repo
    assert not st.guarded
    assert st.safe_to_write


def test_missing_git_repo_is_reported_not_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    st = state.check(tmp_path)
    assert not st.is_git_repo


# --- the merged repo: the bug this gate change fixes --------------------------------


def test_merged_repo_still_commits_and_pushes(merged):
    """The regression. Not split, but a real repo — save() must do real work."""
    (merged["laptop"] / "log" / "training-log.md").write_text("# Training log\n| 12-08 |\n")
    assert state.save("daily 12-08", merged["laptop"]) == "daily 12-08"

    fresh = merged["laptop"].parent / "fresh-merged"
    subprocess.run(["git", "clone", "-q", str(merged["remote"]), str(fresh)], check=True)
    assert "12-08" in (fresh / "log" / "training-log.md").read_text()


def test_merged_repo_still_runs_the_behind_check(merged):
    """The most serious of the four gates: check() skipped the behind-check
    entirely when not split, which is the guard against dropping another
    machine's writes."""
    phone = merged["phone"]
    (phone / "log" / "training-log.md").write_text("# Training log\n| from the phone |\n")
    git(phone, "commit", "-qam", "phone writes")
    git(phone, "push", "-q")

    with pytest.raises(state.StateError, match="behind"):
        state.check(merged["laptop"])


def test_mc_state_git_off_disables_the_guard(monkeypatch, merged):
    monkeypatch.setenv("MC_STATE_GIT", "off")
    st = state.check(merged["laptop"])
    assert not st.guarded
    assert state.save("msg", merged["laptop"]) is None


# --- the actual hazard --------------------------------------------------------------


def test_clean_and_in_sync_passes(split):
    st = state.check(split["laptop"])
    assert st.clean and st.behind == 0 and st.safe_to_write


def test_behind_refuses_to_write(split):
    """The phone wrote a session; the laptop hasn't pulled. Writing now would
    silently drop it, because training-log.md is rewritten whole."""
    phone = split["phone"]
    (phone / "log" / "training-log.md").write_text("# Training log\n\n| 02-08 | 5mi | run 5.0mi |\n")
    git(phone, "commit", "-q", "-am", "phone: 02-08")
    git(phone, "push", "-q")

    with pytest.raises(state.StateError, match="behind"):
        state.check(split["laptop"])


def test_pulling_clears_the_refusal(split):
    phone = split["phone"]
    (phone / "log" / "training-log.md").write_text("# Training log\n\n| 02-08 | 5mi | run 5.0mi |\n")
    git(phone, "commit", "-q", "-am", "phone: 02-08")
    git(phone, "push", "-q")

    git(split["laptop"], "pull", "-q")
    assert state.check(split["laptop"]).safe_to_write


def test_uncommitted_local_changes_do_not_block(split):
    """Dirty is normal — /daily writes files and then saves them. Only being
    *behind* is dangerous."""
    (split["laptop"] / "log" / "sessions.md").write_text("today")
    st = state.check(split["laptop"])
    assert not st.clean
    assert st.safe_to_write


# --- save ---------------------------------------------------------------------------


def test_save_commits_and_pushes(split):
    (split["laptop"] / "log" / "training-log.md").write_text("# Training log\n\n| 02-08 | 5mi | done |\n")
    assert state.save("daily 02-08", split["laptop"]) == "daily 02-08"

    fresh = split["remote"].parent / "verify"
    subprocess.run(["git", "clone", "-q", str(split["remote"]), str(fresh)], check=True)
    assert "02-08" in (fresh / "log" / "training-log.md").read_text()


def test_save_with_nothing_to_commit_is_a_no_op(split):
    assert state.save("nothing changed", split["laptop"]) is None


def test_save_is_a_no_op_without_a_git_repo(tmp_path):
    """A plain directory has no history to commit to. Note this is the *only*
    reason save() may no-op — being unsplit is not one, see
    test_merged_repo_still_commits_and_pushes."""
    assert state.save("msg", tmp_path) is None


# --- the writer lease: two rituals in flight at once --------------------------------


@pytest.fixture
def as_laptop(monkeypatch):
    monkeypatch.setenv("MC_DEVICE", "laptop")


def as_device(monkeypatch, name):
    monkeypatch.setenv("MC_DEVICE", name)


def test_device_id_prefers_mc_device(monkeypatch):
    monkeypatch.setenv("MC_DEVICE", "phone")
    assert state.device_id() == "phone"


def test_device_id_falls_back_to_hostname(monkeypatch):
    monkeypatch.delenv("MC_DEVICE", raising=False)
    assert state.device_id()  # never anonymous


def test_claim_writes_commits_and_pushes_the_lease(split, as_laptop):
    lease, warning = state.claim("daily 05-08", split["laptop"])
    assert lease.device == "laptop" and not warning

    git(split["phone"], "pull", "-q")
    seen = state.read_lease(split["phone"])
    assert seen is not None and seen.device == "laptop"
    assert seen.purpose == "daily 05-08"


def test_a_live_lease_from_another_device_blocks_the_check(split, monkeypatch):
    """The case the behind-check cannot see: the phone is *mid-ritual* and has
    not saved anything yet, so there is nothing to be behind."""
    as_device(monkeypatch, "phone")
    state.claim("daily 05-08", split["phone"])

    git(split["laptop"], "pull", "-q")
    as_device(monkeypatch, "laptop")
    with pytest.raises(state.StateError, match="Another device holds the writer lease"):
        state.check(split["laptop"])


def test_same_device_second_session_is_refused(split, as_laptop):
    """Two Claude sessions on one machine share a working tree — the git
    guard is blind to that, the lease is not."""
    state.claim("daily 05-08", split["laptop"])
    with pytest.raises(state.StateError, match="already holds a writer lease"):
        state.claim("preview 05-08", split["laptop"])


def test_force_takes_over(split, as_laptop):
    state.claim("daily 05-08", split["laptop"])
    lease, warning = state.claim("preview 05-08", split["laptop"], force=True)
    assert lease.purpose == "preview 05-08"
    del warning  # same device taking over itself needs no warning


def test_an_expired_lease_does_not_lock_the_other_device_out(split, monkeypatch):
    """A ritual abandoned on a flat phone must not cost the laptop tomorrow."""
    as_device(monkeypatch, "phone")
    state.claim("daily 05-08", split["phone"])
    git(split["laptop"], "pull", "-q")

    monkeypatch.setenv("MC_LEASE_TTL_MIN", "0")
    as_device(monkeypatch, "laptop")
    st = state.check(split["laptop"])
    assert st.safe_to_write
    lease, warning = state.claim("daily 06-08", split["laptop"])
    assert lease.device == "laptop"
    assert warning and "phone" in warning


def test_save_releases_the_lease_and_records_the_device(split, as_laptop):
    state.claim("daily 05-08", split["laptop"])
    (split["laptop"] / "log" / "training-log.md").write_text("# Training log\n\n| 05-08 | 5mi | done |\n")
    assert state.save("daily 05-08", split["laptop"]) == "daily 05-08"

    assert state.read_lease(split["laptop"]) is None
    body = subprocess.run(
        ["git", "-C", str(split["laptop"]), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "Device: laptop" in body

    git(split["phone"], "pull", "-q")
    assert state.read_lease(split["phone"]) is None  # cleared for the other device too


def test_a_stale_lease_file_is_treated_as_no_lease(split, as_laptop):
    """Fail open onto the behind-check rather than bricking on a bad byte."""
    state.lease_path(split["laptop"]).write_text("{not json")
    assert state.read_lease(split["laptop"]) is None
    assert state.check(split["laptop"]).safe_to_write


def test_lease_works_without_git(monkeypatch, tmp_path):
    """No repo, no remote, but two local sessions still collide."""
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    as_device(monkeypatch, "laptop")
    state.claim("daily 05-08", tmp_path)
    with pytest.raises(state.StateError, match="already holds"):
        state.claim("daily 05-08", tmp_path)
    assert state.release(tmp_path)
    assert state.read_lease(tmp_path) is None


# --- one /daily per day: the ritual that already finished ---------------------------


def write_today_md(root, ddmm, body="\n## Today — 5 mi easy\n"):
    out = root / "out"
    out.mkdir(exist_ok=True)
    (out / "today.md").write_text(f"# {ddmm} · Week 3/14 · w/c 10-08 · 11 weeks to NYC\n{body}")
    return out / "today.md"


@pytest.fixture
def today(monkeypatch):
    """Freeze 'today' so the fixture's today.md and the guard agree."""
    frozen = date(2026, 8, 14)
    # One seam for the whole codebase now: every module asks clock.today()
    # rather than its own imported `date`, so freezing it here is enough.
    monkeypatch.setattr(clock, "today", lambda: frozen)
    return frozen


def test_second_daily_is_refused_once_today_md_exists(split, as_laptop, today):
    write_today_md(split["laptop"], "14-08")
    with pytest.raises(state.StateError, match="already run today"):
        state.claim("daily 14-08", split["laptop"])


def test_the_refusal_points_at_preview_and_sync(split, as_laptop, today):
    """A stop that doesn't say what to do instead just gets worked around."""
    write_today_md(split["laptop"], "14-08")
    with pytest.raises(state.StateError) as excinfo:
        state.claim("daily 14-08", split["laptop"])
    message = str(excinfo.value)
    assert "mc sync" in message and "/preview" in message and "--again" in message


def test_yesterdays_today_md_does_not_block(split, as_laptop, today):
    """The header names the day, so a file left over from yesterday is not
    evidence that today has run."""
    write_today_md(split["laptop"], "13-08")
    lease, _ = state.claim("daily 14-08", split["laptop"])
    assert lease.purpose == "daily 14-08"


def test_only_the_daily_purpose_is_gated(split, as_laptop, today):
    """/preview and /week write different files and legitimately run after
    /daily on the same day."""
    write_today_md(split["laptop"], "14-08")
    lease, _ = state.claim("preview 14-08", split["laptop"])
    assert lease.purpose == "preview 14-08"
    state.release(split["laptop"])
    lease, _ = state.claim("week review w/c 10-08", split["laptop"])
    assert lease.purpose == "week review w/c 10-08"


def test_again_overrides_the_refusal(split, as_laptop, today):
    write_today_md(split["laptop"], "14-08")
    lease, _ = state.claim("daily 14-08", split["laptop"], again=True)
    assert lease.device == "laptop"


def test_force_does_not_smuggle_a_second_daily_through(split, as_laptop, today):
    """--force is about a dead lease, not about rewriting a finished day."""
    write_today_md(split["laptop"], "14-08")
    with pytest.raises(state.StateError, match="already run today"):
        state.claim("daily 14-08", split["laptop"], force=True)


def test_the_other_device_is_blocked_after_pulling(split, monkeypatch, today):
    """Cross-device coverage rides on the behind-check: the phone cannot see
    the laptop's today.md until it pulls, and cannot write until it does."""
    as_device(monkeypatch, "laptop")
    write_today_md(split["laptop"], "14-08")
    state.save("daily 14-08", split["laptop"])

    as_device(monkeypatch, "phone")
    with pytest.raises(state.StateError, match="behind its remote"):
        state.claim("daily 14-08", split["phone"])

    git(split["phone"], "pull", "-q")
    with pytest.raises(state.StateError, match="already run today"):
        state.claim("daily 14-08", split["phone"])


def test_the_refusal_names_the_device_that_wrote_the_day(split, monkeypatch, today):
    as_device(monkeypatch, "laptop")
    write_today_md(split["laptop"], "14-08")
    state.save("daily 14-08", split["laptop"])
    git(split["phone"], "pull", "-q")

    as_device(monkeypatch, "phone")
    with pytest.raises(state.StateError, match="on laptop"):
        state.claim("daily 14-08", split["phone"])


def test_daily_run_for_reports_nothing_when_out_is_empty(split, today):
    assert state.daily_run_for(root=split["laptop"]) is None


def test_daily_run_for_ignores_a_file_with_no_header_date(split, today):
    (split["laptop"] / "out").mkdir(exist_ok=True)
    (split["laptop"] / "out" / "today.md").write_text("no header at all\n")
    assert state.daily_run_for(root=split["laptop"]) is None
