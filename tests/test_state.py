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
