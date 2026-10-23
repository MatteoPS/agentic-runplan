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

## The writer lease (added 05-08-2026, for running /daily from the phone)

`check()` catches a checkout that is behind something *already pushed*. It
cannot catch the case the phone introduces: two rituals **in flight at the
same time**. Both machines fetch clean, both pass `check()`, both write the
day, and the second `save()` either loses the first or lands on a rejected
push that has to be untangled by hand at 6am.

So a write is now announced before it happens, not only after. `claim()`
writes `writer.json` into the state repo — device, when, what for — commits
and pushes it, and refuses if another device already holds a live one.
`save()` clears it in the same commit that saves the day. `writer.json` is
the flag that says *where the update came from*: it is in the repo, so the
other device sees it by fetching, and the commit trailer (`Device: …`)
leaves the same answer in the history afterwards.

Two properties worth stating plainly, because the guard is only honest if
its limits are:

- The lease is **advisory across devices and only as fresh as the last
  fetch**. It closes the window from minutes to the seconds between claim and
  push. It is not a distributed lock and nothing here pretends it is; the
  behind-check and git's refusal to merge remain the real backstop.
- It **expires** (`MC_LEASE_TTL_MIN`, default 120). A ritual abandoned
  half-way on a phone that then went flat must not lock the laptop out of
  tomorrow.

Device identity is `MC_DEVICE`, falling back to the hostname. Set it
explicitly on any machine whose hostname isn't obvious in a commit log.

## One /daily per day (added 14-08-2026)

The lease answers "is someone writing *right now*". It says nothing about a
ritual that already finished, and a second /daily hours later is a different
failure: it rewrites today's prescription, re-runs `mc propose` over the same
row, and produces a second `log/sessions/` entry for a day already decided.
Nothing is corrupted, but the record stops matching what actually happened,
and the day's answers get re-asked and re-answered from a different mood.

So `claim()` also refuses a *daily* purpose when `out/today.md` already
declares today. That file is the ritual's own output and carries its own
`# DD-MM` header — the same "believe the file, not the filename" precedent as
`tidy` and `push._check_today_md_date` — so no new bookkeeping is needed and
nothing can disagree with it.

Cross-device falls out of the existing machinery rather than needing its own:
`out/` is tracked, so a today.md written on the phone reaches the laptop as a
commit, and the behind-check refuses to proceed until it is pulled. It is
therefore exactly as strong as the behind-check — with `MC_STATE_GIT=off`, no
remote, or an unpushed save, it only guards the device it ran on. Say that
rather than implying a global lock.

`--again` is the escape hatch, and it is deliberately *not* `--force`: taking
over a dead session's lease and rewriting a day that already happened are
different decisions and should not share a flag.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mc import clock
from mc import config as cfg

LEASE_FILENAME = "writer.json"
DEFAULT_LEASE_TTL_MIN = 120

# The daily ritual's own output, relative to STATE_ROOT.
DAILY_OUTPUT_RELPATH = "out/today.md"

# Same header shape render/push/tidy already read. Duplicated rather than
# imported: `mc render` pulls in sync and digest, and the writer guard has no
# business dragging the whole data layer in to read one line of markdown.
_HEADER_DATE_RE = re.compile(r"^#\s*(\d{2}-\d{2})", re.MULTILINE)

_DEVICE_TRAILER_RE = re.compile(r"^Device:\s*(.+)$", re.MULTILINE)


class StateError(Exception):
    pass


def device_id() -> str:
    """Which machine is writing. `MC_DEVICE` wins; hostname is the fallback so
    an unconfigured machine still identifies itself rather than writing
    anonymously."""
    explicit = (os.environ.get("MC_DEVICE") or "").strip()
    if explicit:
        return explicit
    return socket.gethostname().split(".")[0] or "unknown"


def _lease_ttl() -> timedelta:
    raw = os.environ.get("MC_LEASE_TTL_MIN")
    try:
        minutes = int(raw) if raw else DEFAULT_LEASE_TTL_MIN
    except ValueError:
        minutes = DEFAULT_LEASE_TTL_MIN
    # 0 is meaningful: it disables the lease entirely, which is the escape
    # hatch when the guard itself is in the way.
    return timedelta(minutes=max(minutes, 0))


@dataclass(frozen=True)
class Lease:
    device: str
    purpose: str
    claimed_at: datetime
    pid: int

    @property
    def age(self) -> timedelta:
        return datetime.now(timezone.utc) - self.claimed_at

    @property
    def expired(self) -> bool:
        return self.age > _lease_ttl()

    @property
    def mine(self) -> bool:
        return self.device == device_id()

    def describe(self) -> str:
        mins = int(self.age.total_seconds() // 60)
        when = self.claimed_at.astimezone().strftime("%H:%M")
        tail = " (expired)" if self.expired else ""
        return f"{self.device} — {self.purpose}, claimed {when} ({mins}m ago){tail}"


@dataclass(frozen=True)
class StateStatus:
    root: Path
    is_split: bool
    is_git_repo: bool
    has_remote: bool
    git_enabled: bool
    dirty: list[str]  # porcelain lines
    behind: int
    ahead: int

    @property
    def clean(self) -> bool:
        return not self.dirty

    @property
    def guarded(self) -> bool:
        """Whether the git side of the writer guard is active at all.

        Deliberately *not* is_split: state living beside the code is a layout
        choice, while losing another machine's write is a property of the
        files. See cfg.state_git_enabled().
        """
        return self.git_enabled and self.is_git_repo

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
    git_enabled = cfg.state_git_enabled()

    if not git_enabled or not (root / ".git").exists():
        return StateStatus(
            root=root, is_split=is_split, is_git_repo=(root / ".git").exists(),
            has_remote=False, git_enabled=git_enabled,
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
        git_enabled=git_enabled, dirty=dirty, behind=behind, ahead=ahead,
    )


def lease_path(root: Path | None = None) -> Path:
    return (root or cfg.STATE_ROOT) / LEASE_FILENAME


def read_lease(root: Path | None = None) -> Lease | None:
    """The current writer lease, or None. A malformed file is treated as no
    lease rather than as an error: a guard that can be bricked by a bad byte
    is worse than one that fails open onto the behind-check."""
    path = lease_path(root)
    try:
        raw = json.loads(path.read_text())
        return Lease(
            device=str(raw["device"]),
            purpose=str(raw.get("purpose", "unspecified")),
            claimed_at=datetime.fromisoformat(raw["claimed_at"]),
            pid=int(raw.get("pid", 0)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_lease(root: Path, purpose: str) -> Lease:
    lease = Lease(
        device=device_id(),
        purpose=purpose,
        claimed_at=datetime.now(timezone.utc),
        pid=os.getpid(),
    )
    lease_path(root).write_text(
        json.dumps(
            {
                "device": lease.device,
                "purpose": lease.purpose,
                "claimed_at": lease.claimed_at.isoformat(),
                "pid": lease.pid,
            },
            indent=2,
        )
        + "\n"
    )
    return lease


@dataclass(frozen=True)
class DailyRun:
    """A /daily that has already produced its output for a given day."""

    path: Path
    day: str  # the DD-MM the file declares in its own header
    written_at: datetime  # local time, from the file's mtime
    device: str | None  # from the commit trailer, when it was committed

    def describe(self) -> str:
        who = f" by {self.device}" if self.device else ""
        return f"{self.path.name} is dated {self.day}, written {self.written_at.strftime('%H:%M')}{who}"


def is_daily_purpose(purpose: str) -> bool:
    """Whether a lease purpose names the daily ritual.

    /daily claims `daily DD-MM`, /week claims `week review ...`, /preview
    claims `preview ...` — only the first writes out/today.md, so only the
    first is gated. Matched on the first word so a purpose with a note after
    the date still counts.
    """
    first = purpose.strip().lower().split()
    return bool(first) and first[0] == "daily"


_PURPOSE_DAY_RE = re.compile(r"\b(\d{2}-\d{2})\b")


def has_uncommitted_content(path: Path, root: Path | None = None) -> bool:
    """Whether git would lose this file's current content if it disappeared.

    True when the file is untracked, or tracked with changes not yet committed.
    False when git already holds exactly what is on disk -- and false, too,
    when there is no repo to ask, because then this answers nothing and the
    caller's existing behaviour is the honest default.

    `mc tidy` deletes from out/ on the stated understanding that "git history
    is the durable record". That was an assumption, never a check, and the two
    came apart on 24-08-2026: /daily writes today.md, runs `mc render --all`
    (which tidies) and only *then* runs `mc state --save`, so a file deleted in
    that window was deleted before anything had a copy of it.
    """
    root = root or cfg.STATE_ROOT
    if not (root / ".git").exists():
        return False
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False  # outside the repo entirely; not ours to protect
    try:
        porcelain = _git(root, "status", "--porcelain", "--", str(rel), check=False)
    except (StateError, OSError):
        return False
    return bool(porcelain.strip())


def purpose_day_mismatch(purpose: str, as_of: date | None = None) -> str | None:
    """A warning when a lease purpose names a day that isn't the training day.

    The purpose string is written by whoever runs the ritual, and in a cloud
    session that is an agent whose own sense of the date comes from the
    container — i.e. UTC, i.e. a day ahead all evening. A `daily 25-08` typed
    on the evening of the 24th is this bug arriving from the outside, and it
    is the last cheap moment to notice: everything downstream (the header, the
    training-log row, the session file) is about to be written to match it.

    A warning rather than a refusal. The purpose is free text, a date in it is
    a convention rather than a contract, and refusing to take a lease over a
    naming disagreement would block the ritual for the wrong reason.
    """
    match = _PURPOSE_DAY_RE.search(purpose)
    if match is None:
        return None
    day = as_of or clock.today()
    if match.group(1) == day.strftime("%d-%m"):
        return None
    return (
        f"purpose says {match.group(1)}, but the training day is "
        f"{clock.describe()}. Check `mc today` before writing any DD-MM — "
        f"the system clock is not the training day here."
    )


def _last_commit_device(root: Path, relpath: str) -> str | None:
    """Which device last committed a path, from `save()`'s trailer. Best
    effort — an uncommitted file, a repo without the trailer, or no git at all
    all mean 'unknown', never an error."""
    try:
        body = _git(root, "log", "-1", "--format=%B", "--", relpath, check=False)
    except (StateError, OSError):
        return None
    match = _DEVICE_TRAILER_RE.search(body or "")
    return match.group(1).strip() if match else None


def daily_run_for(as_of: date | None = None, root: Path | None = None) -> DailyRun | None:
    """The finished /daily for `as_of`, or None if today hasn't been written.

    Reads out/today.md's own `# DD-MM` header rather than its mtime: the
    header is what every other consumer believes (push, tidy, render), and an
    mtime moves for reasons that have nothing to do with which day the file
    is about — a checkout, a pull, an export.
    """
    root = root or cfg.STATE_ROOT
    as_of = as_of or clock.today()
    path = root / DAILY_OUTPUT_RELPATH
    try:
        declared = _HEADER_DATE_RE.search(path.read_text())
    except OSError:
        return None
    if declared is None or declared.group(1) != as_of.strftime("%d-%m"):
        return None
    return DailyRun(
        path=path,
        day=declared.group(1),
        written_at=datetime.fromtimestamp(path.stat().st_mtime),
        device=_last_commit_device(root, DAILY_OUTPUT_RELPATH) if (root / ".git").exists() else None,
    )


def _refuse_second_daily(run: DailyRun, purpose: str) -> StateError:
    where = f" on {run.device}" if run.device and run.device != device_id() else ""
    return StateError(
        f"/daily has already run today ({run.day}){where} — {run.describe()}.\n"
        f"Running it again rewrites today's prescription, re-proposes the same row in "
        f"training-log.md and logs a second session for one day.\n"
        f"  • new activity data to fold in → mc sync\n"
        f"  • close the day out / project tomorrow → /preview\n"
        f"  • just re-read today's plan → out/today.md\n"
        f"If today genuinely has to be rewritten (wrong answers, changed circumstances), "
        f"say so and re-claim with: mc state --claim '{purpose}' --again"
    )


def check(root: Path | None = None, *, respect_lease: bool = True) -> StateStatus:
    """Raises when it is not safe to write state. Call before /daily writes."""
    st = status(root)
    if not st.guarded:
        return st  # nothing to guard -- no git history to lose a write from
    if not st.safe_to_write:
        raise StateError(
            f"State repo is {st.behind} commit(s) behind its remote — another machine "
            f"has written training state you don't have yet. Writing now would silently "
            f"drop it (training-log.md and the JSON state files are whole-file rewrites).\n"
            f"Run: git -C {st.root} pull"
        )
    if respect_lease:
        held = read_lease(st.root)
        if held is not None and not held.expired and not held.mine:
            raise StateError(
                f"Another device holds the writer lease: {held.describe()}.\n"
                f"You are {device_id()}. Finish or abandon that session there, or — if you "
                f"know it is dead — take it over with: mc state --claim '<purpose>' --force"
            )
    return st


def claim(
    purpose: str, root: Path | None = None, *, force: bool = False, again: bool = False
) -> tuple[Lease, str | None]:
    """Announce a write before making it. Returns the lease and a warning
    string (None when everything went cleanly).

    The warning is not decoration: an unpushed lease is invisible to the other
    device, so the caller must be able to say so out loud instead of implying
    a protection that isn't there."""
    root = root or cfg.STATE_ROOT
    st = check(root, respect_lease=not force)

    # After the behind-check, never before: a today.md written on the other
    # device is only visible here once it has been pulled, and the behind-check
    # is what makes the caller pull it.
    if is_daily_purpose(purpose) and not again:
        done = daily_run_for(root=root)
        if done is not None:
            raise _refuse_second_daily(done, purpose)

    held = read_lease(root)
    warning = None
    if held is not None and not held.expired and held.mine and not force:
        raise StateError(
            f"This device already holds a writer lease: {held.describe()} (pid {held.pid}).\n"
            f"Another session on {device_id()} may be part-way through a ritual — two of them "
            f"share one working tree and the last one to write wins.\n"
            f"Finish it, or take over with: mc state --claim '{purpose}' --force"
        )
    if held is not None and (held.expired or force) and not held.mine:
        warning = f"Took over a lease from {held.device} ({held.describe()})"

    lease = _write_lease(root, purpose)

    if st.guarded:
        _git(root, "add", "--", LEASE_FILENAME)
        _git(
            root, "commit", "-q", "-m", f"state: {lease.device} claims — {purpose}",
            "--only", "--", LEASE_FILENAME, check=False,
        )
        if st.has_remote:
            pushed = subprocess.run(
                ["git", "-C", str(root), "push", "--quiet"], capture_output=True, text=True, check=False
            )
            if pushed.returncode != 0:
                warning = (
                    "Lease claimed locally but NOT pushed — the other device cannot see it, "
                    f"so it is not protecting you right now ({pushed.stderr.strip().splitlines()[-1] if pushed.stderr.strip() else 'push failed'})."
                )
    return lease, warning


def release(root: Path | None = None) -> bool:
    """Drop the lease. Left uncommitted on purpose — `save()` commits it along
    with the day's actual state, so a released lease and the work it covered
    land in the same commit."""
    path = lease_path(root)
    if not path.exists():
        return False
    path.unlink()
    return True


def save(message: str, root: Path | None = None, *, push: bool = True) -> str | None:
    """Commit and push state, releasing the writer lease in the same commit.
    Returns the commit subject, or None if there was nothing to save."""
    root = root or cfg.STATE_ROOT
    if not cfg.state_git_enabled() or not (root / ".git").exists():
        release(root)
        return None
    release(root)
    st = status(root, fetch=False)
    if not st.dirty:
        return None
    _git(root, "add", "-A")
    # The trailer answers "which device wrote this day?" from the history
    # alone, months later, when writer.json has long since been cleared.
    _git(root, "commit", "-m", f"{message}\n\nDevice: {device_id()}")
    if push and st.has_remote:
        _git(root, "push", "--quiet")
    return message
