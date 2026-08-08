import subprocess

import pytest

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


# --- not split: the guard must stay out of the way ----------------------------------


def test_unsplit_state_is_never_blocked(monkeypatch, tmp_path):
    """Default single-machine setup — nothing to guard, nothing to refuse."""
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "state_is_split", lambda: False)
    st = state.check(tmp_path)
    assert not st.is_split
    assert st.safe_to_write


def test_split_but_not_a_git_repo_is_reported_not_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "state_is_split", lambda: True)
    st = state.check(tmp_path)
    assert not st.is_git_repo


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


def test_save_is_a_no_op_when_state_is_not_split(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "state_is_split", lambda: False)
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
    """Unsplit setup: no repo, no remote, but two local sessions still collide."""
    monkeypatch.setattr(cfg, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "state_is_split", lambda: False)
    as_device(monkeypatch, "laptop")
    state.claim("daily 05-08", tmp_path)
    with pytest.raises(state.StateError, match="already holds"):
        state.claim("daily 05-08", tmp_path)
    assert state.release(tmp_path)
    assert state.read_lease(tmp_path) is None
