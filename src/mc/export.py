"""Copy rendered output into one local directory, so it reaches the phone.

Deliberately the dumbest possible mechanism: a file copy into a path from
`.env`. No cloud SDK, no OAuth, no credentials, no network call, no new
dependency. If that path happens to live inside iCloud Drive / Dropbox /
Google Drive's local folder, *their* sync client carries it to the phone --
`mc` neither knows nor cares which one, and could just as well be pointed at
a USB stick.

Two properties worth preserving:

- **Write-only.** Nothing here ever reads the destination back. A half-synced
  or conflict-mangled copy sitting in a cloud folder therefore cannot re-enter
  this system's state -- it is a dead end by construction. This is why only
  rendered artifacts go out, never `log/` or `data/`: those are the audit
  trail, and they sync via git precisely so conflicts fail loudly instead of
  being silently resolved by a cloud drive.
- **Off by default.** No `MC_EXPORT_DIR` means no export, silently. An unset
  optional feature is not an error.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mc import config as cfg

# today.md rides along with the HTML: it's the same content, but readable in
# any plain-text editor on the phone if the HTML renders badly.
EXPORT_PATTERNS = ("*.html", "today.md")


class ExportError(Exception):
    pass


@dataclass(frozen=True)
class ExportResult:
    destination: Path | None
    copied: list[Path]

    @property
    def enabled(self) -> bool:
        return self.destination is not None


def export_dir() -> Path | None:
    """None when unset/blank -- the feature is opt-in."""
    raw = (os.environ.get("MC_EXPORT_DIR") or "").strip()
    return Path(raw).expanduser() if raw else None


def export(out_dir: Path = cfg.OUT_DIR, destination: Path | None = None) -> ExportResult:
    dest = destination if destination is not None else export_dir()
    if dest is None:
        return ExportResult(destination=None, copied=[])

    # Create the leaf directory, but never its parents. A missing parent means
    # the sync root isn't where it was expected -- iCloud not mounted, a typo,
    # a renamed folder. mkdir(parents=True) there would cheerfully build a
    # stray local tree that never syncs anywhere, and the export would report
    # success every day while the phone showed nothing.
    if not dest.parent.exists():
        raise ExportError(
            f"Export destination's parent doesn't exist: {dest.parent}. "
            f"That usually means the sync folder isn't mounted or MC_EXPORT_DIR "
            f"has a typo — refusing to create a stray directory that would never sync."
        )
    dest.mkdir(exist_ok=True)

    if not out_dir.exists():
        return ExportResult(destination=dest, copied=[])

    sources: list[Path] = []
    for pattern in EXPORT_PATTERNS:
        sources.extend(p for p in sorted(out_dir.glob(pattern)) if p.is_file())

    copied = []
    for src in sources:
        shutil.copy2(src, dest / src.name)  # copy2 keeps mtime, so the phone shows the real age
        copied.append(dest / src.name)
    return ExportResult(destination=dest, copied=copied)
