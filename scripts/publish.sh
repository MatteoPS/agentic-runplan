#!/usr/bin/env bash
#
# Refresh the public showcase repo (agentic-runplan) from this one.
#
# Since 12-08-2026 this repo is private and holds BOTH the code and the real
# training data. The public repo is a frozen showcase, refreshed by hand when
# there is something worth showing.
#
# ── Why this is an allowlist ───────────────────────────────────────────────────
#
# The failure mode here is publishing `log/`, `out/`, `data/` or
# `context/overrides.md` to a public GitHub repo — real training and health
# data, irreversibly, to anyone watching. An exclude-list fails *open*: add a
# new directory of personal data next year, forget to add it to the excludes,
# and it ships. An allowlist fails *closed* — a new directory is simply not
# copied until someone says so. That asymmetry is the whole design.
#
# For the same reason it prints what it would do and stops. Pass --commit to
# actually write, matching `mc push`'s opt-in discipline.
#
# Usage:
#   scripts/publish.sh                 # dry run, prints the file list
#   scripts/publish.sh --commit        # copy, commit and push
#   PUBLIC_REPO=~/elsewhere scripts/publish.sh

set -euo pipefail

PUBLIC_REPO="${PUBLIC_REPO:-$HOME/agentic-runplan}"
PRIVATE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMIT=0
[[ "${1:-}" == "--commit" ]] && COMMIT=1

# Everything the public repo is allowed to contain. Directories are copied
# wholesale; anything not named here never leaves this repo.
#
# Deliberately absent: log/, out/, data/, context/overrides.md, .env, and
# .gitignore — the last because the public repo needs its OWN, which ignores
# out/ and log/. Copying this repo's (which tracks them) would arm the very
# leak this script exists to prevent.
ALLOW_DIRS=(
  src
  tests
  plan
  docs
  examples
  scripts
  .claude/commands
)
ALLOW_FILES=(
  LICENSE
  CLAUDE.md
  README.md
  TODO.md
  instructionforclaudecode.md
  pyproject.toml
  uv.lock
  .env.example
  context/equivalence.md
)

if [[ ! -d "$PUBLIC_REPO/.git" ]]; then
  echo "error: $PUBLIC_REPO is not a git checkout. Set PUBLIC_REPO." >&2
  exit 1
fi

echo "from: $PRIVATE_REPO"
echo "to:   $PUBLIC_REPO"
echo

for d in "${ALLOW_DIRS[@]}"; do
  [[ -d "$PRIVATE_REPO/$d" ]] || continue
  if (( COMMIT )); then
    mkdir -p "$PUBLIC_REPO/$(dirname "$d")"
    rsync -a --delete \
      --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
      "$PRIVATE_REPO/$d/" "$PUBLIC_REPO/$d/"
  fi
  echo "  dir   $d/"
done

for f in "${ALLOW_FILES[@]}"; do
  [[ -f "$PRIVATE_REPO/$f" ]] || continue
  if (( COMMIT )); then
    mkdir -p "$PUBLIC_REPO/$(dirname "$f")"
    cp "$PRIVATE_REPO/$f" "$PUBLIC_REPO/$f"
  fi
  echo "  file  $f"
done

echo
if (( ! COMMIT )); then
  echo "Dry run — nothing written. Re-run with --commit to publish."
  exit 0
fi

# Last line of defence: refuse to commit if anything personal made it across,
# however it got there. Cheaper than a retraction.
cd "$PUBLIC_REPO"
if git status --porcelain | grep -E '^\?\?|^[AM]' | grep -qE ' (log|out|data)/|overrides\.md|^\.env$'; then
  echo "REFUSING: personal data staged in the public repo. Inspect and clean:" >&2
  git status --short >&2
  exit 1
fi

git add -A
if git diff --cached --quiet; then
  echo "Nothing changed."
  exit 0
fi
git commit -m "showcase: refresh from private repo"
git push
echo "Published."
