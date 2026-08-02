"""Guard and sync the private state repo.

The state files this project writes are not merge-friendly. Three of them are
read-modify-rewrite-whole-file, with no merge logic anywhere:

    log/training-log.md         (traininglog.save_log rewrites the table)
    data/strength_schedule.json (strength._save_state)
    data/pushed.json            (push._save_pushed)

Two machines writing any of those on the same day is last-writer-wins, and
the failure is silent: a row written on the phone simply disappears when the
laptop rewrites from a stale copy, and a lost key in pushed.json makes the
next push *create a duplicate Garmin workout* instead of updating in place.

The mitigation is single-writer-per-day, and the point of this module is that
it is **enforced rather than documented**. `check()` runs at the top of
/daily, /week and /preview and refuses to proceed from a stale checkout;
`save()` commits and pushes at the end. The rule the human follows is just
"pull before, push after", and forgetting is caught instead of corrupting.

Git is the sync layer deliberately: it *refuses* to merge a conflict, where a
cloud drive would resolve it silently or leave a "(conflicted copy)" file
that nothing reads. For an audit trail whose entire value is being
trustworthy, loud beats silent.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mc import config as cfg


class StateError(Exception):
    pass


@dataclass(frozen=True)
class StateStatus:
    root: Path
    is_split: bool
    is_git_repo: bool
    has_remote: bool
    dirty: list[str]  # porcelain lines
    behind: int
    ahead: int

    @property
    def clean(self) -> bool:
        return not self.dirty

    @property
    def safe_to_write(self) -> bool:
        """Behind means another machine has written state we haven't seen --
        the one condition that silently destroys data on the next save."""
        return self.behind == 0


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise StateError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def status(root: Path | None = None, *, fetch: bool = True) -> StateStatus:
    root = root or cfg.STATE_ROOT
    is_split = cfg.state_is_split()

    if not (root / ".git").exists():
        return StateStatus(
            root=root, is_split=is_split, is_git_repo=False, has_remote=False,
            dirty=[], behind=0, ahead=0,
        )

    has_remote = bool(_git(root, "remote", check=False))
    if fetch and has_remote:
        # Never fail the whole check on a network hiccup -- offline is a
        # normal state for a laptop, and refusing to run /daily on a plane
        # would be worse than proceeding with a stale-but-known checkout.
        _git(root, "fetch", "--quiet", check=False)

    dirty = [ln for ln in _git(root, "status", "--porcelain").splitlines() if ln.strip()]

    behind = ahead = 0
    if has_remote:
        counts = _git(root, "rev-list", "--left-right", "--count", "@{upstream}...HEAD", check=False)
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])

    return StateStatus(
        root=root, is_split=is_split, is_git_repo=True, has_remote=has_remote,
        dirty=dirty, behind=behind, ahead=ahead,
    )


def check(root: Path | None = None) -> StateStatus:
    """Raises when it is not safe to write state. Call before /daily writes."""
    st = status(root)
    if not st.is_split or not st.is_git_repo:
        return st  # nothing to guard -- single machine, state lives in the checkout
    if not st.safe_to_write:
        raise StateError(
            f"State repo is {st.behind} commit(s) behind its remote — another machine "
            f"has written training state you don't have yet. Writing now would silently "
            f"drop it (training-log.md and the JSON state files are whole-file rewrites).\n"
            f"Run: git -C {st.root} pull"
        )
    return st


def save(message: str, root: Path | None = None, *, push: bool = True) -> str | None:
    """Commit and push state. Returns the commit subject, or None if there was
    nothing to save."""
    root = root or cfg.STATE_ROOT
    if not cfg.state_is_split() or not (root / ".git").exists():
        return None
    st = status(root, fetch=False)
    if not st.dirty:
        return None
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    if push and st.has_remote:
        _git(root, "push", "--quiet")
    return message
