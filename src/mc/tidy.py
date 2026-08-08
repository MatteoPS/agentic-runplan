"""Keeping out/ to only what is current.

Nothing used to delete anything here. `render.is_stale` *skipped* a stale
`out/tomorrow.md` rather than turning yesterday's guess into a fresh-looking
page -- the right call, but it left the file and its HTML twin on disk, so
out/ accumulated: a `tomorrow.md` for a day that had passed, HTML twins days
older than the markdown they claimed to render, and one-off documents
(`race-strategy-08-08.md`) that outlived the day they were written for.

A stale file in out/ is worse than a missing one. Missing is obvious; stale
looks exactly like current, and out/ is the folder that gets read on a phone
at 6am. The state repo's git history and log/sessions/ are the durable
record, so deletion loses nothing.

The principle, applied to every file: **a file in out/ must declare the day
it is for, and one whose day has passed is deleted.** Two ways to declare it,
both already conventions in this project rather than new syntax:

  1. a `# DD-MM` header in the markdown itself -- what /daily and /preview
     already write, and what render.target_date_of already reads. We believe
     the file over its filename, the same precedent as push._check_today_md_date.
  2. a `-DD-MM` suffix on the filename -- which retires race-strategy-08-08.md
     and every future dated one-off without anyone maintaining a registry.

A .md carrying neither signal is **reported and left alone**. Silently
deleting a file we don't recognise is exactly the wrong instinct for a
directory a person keeps things in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from mc import config as cfg
from mc import render as render_mod

# dashboard.md is a rolling view of the whole plan, not a document about a
# day, so it has no date to go stale against -- `mc render --all` rewrites it
# every run. Exempting it is what keeps rule 1 from deleting it on sight.
UNDATED_BY_DESIGN = {"dashboard.md"}

# Same tolerance render.is_stale already applies to tomorrow.md: written the
# evening before, so its header names tomorrow, and it stays valid through
# the day it describes.
LOOKAHEAD_FILES = {"tomorrow.md"}

_FILENAME_DATE_RE = re.compile(r"-(\d{2}-\d{2})$")


@dataclass(frozen=True)
class Removal:
    """A file and why it went. The reason is reported, not just logged: this
    whole module exists so out/ never misrepresents how current it is, and a
    deletion notice that gives the wrong reason is the same failure one step
    removed."""

    path: Path
    reason: str

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class TidyResult:
    removed: list[Removal] = field(default_factory=list)
    undated: list[Path] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.removed)


def _filename_date(md_path: Path) -> str | None:
    """The DD-MM in a `<name>-DD-MM.md` filename, if any."""
    match = _FILENAME_DATE_RE.search(md_path.stem)
    return match.group(1) if match else None


def _declared_date(md_path: Path) -> str | None:
    """The day this file is for: header first, filename second."""
    return render_mod.target_date_of(md_path) or _filename_date(md_path)


def is_expired(md_path: Path, as_of: date) -> bool:
    """True when the file's own declared day is behind `as_of`.

    A lookahead file (tomorrow.md) is also expired when it declares no day at
    all -- render.is_stale's reasoning, kept: a provisional projection that
    won't say which day it is for is not trustworthy. For every other file an
    absent date means "not datable", handled by the caller as undated.
    """
    declared = _declared_date(md_path)
    if declared is None:
        return md_path.name in LOOKAHEAD_FILES
    fresh = {as_of.strftime("%d-%m")}
    if md_path.name in LOOKAHEAD_FILES:
        fresh.add((as_of + timedelta(days=1)).strftime("%d-%m"))
    return declared not in fresh


# An .html twin goes when its .md source is gone or has moved on. That is what
# clears the existing HTML set now that markdown is the default: stop
# regenerating them and they age out as their sources get rewritten, with no
# dependence on which mode last ran. Under `--html` they are written after
# their source, so they never look older.


def tidy(out_dir: Path | None = None, as_of: date | None = None, dry_run: bool = False) -> TidyResult:
    """Delete everything in out/ whose declared day has passed.

    Removing a .md takes its .html twin with it -- a rendered page outliving
    its source is the same staleness one step removed.
    """
    out_dir = out_dir if out_dir is not None else cfg.OUT_DIR
    as_of = as_of or date.today()
    result = TidyResult()
    if not out_dir.exists():
        return result

    doomed: dict[Path, str] = {}
    for md_path in sorted(out_dir.glob("*.md")):
        if md_path.name in UNDATED_BY_DESIGN:
            continue
        if _declared_date(md_path) is None and md_path.name not in LOOKAHEAD_FILES:
            result.undated.append(md_path)
            continue
        if is_expired(md_path, as_of):
            doomed[md_path] = "its day has passed"
            doomed[md_path.with_suffix(".html")] = "the markdown it renders is gone"

    for html_path in sorted(out_dir.glob("*.html")):
        if html_path in doomed:
            continue
        md_path = html_path.with_suffix(".md")
        if not md_path.exists():
            doomed[html_path] = "no markdown source"
        elif html_path.stat().st_mtime < md_path.stat().st_mtime:
            doomed[html_path] = f"older than {md_path.name}"

    for path, reason in sorted(doomed.items()):
        if not path.exists():
            continue
        result.removed.append(Removal(path=path, reason=reason))
        if not dry_run:
            path.unlink()
    return result
