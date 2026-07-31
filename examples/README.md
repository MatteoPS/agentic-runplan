# examples/

Everything under this folder is **fabricated** — invented dates, distances,
heart rates, and wellness numbers, not a real training day. It exists purely
to show the *shape* of what the system produces, since the real equivalents
(`out/`, `log/`, `data/`) are gitignored: they hold real personal training
and health data once you actually run this against your own Garmin/intervals
account, and are never meant to be committed.

- `out/today.md` + `.html` — what `/daily` writes each morning: today's
  session, the reasoning behind it, a substitution table, strength/mobility,
  the rest of the week, and a compliance line.
- `log/training-log.md` — the running proposed-vs-actual table (`mc
  propose` / `mc digest`).
- `log/sessions/DD-MM.md` — one dated file per day, the raw session note
  `/daily` appends to.
- `data/raw/` — a couple of representative files showing what the Garmin
  and intervals.icu API caches look like on disk after `mc sync` (real
  caches live in the full `data/raw/garmin/` and `data/raw/intervals/` tree,
  far larger and gitignored).
- `data/digest/DD-MM.md` — what `mc digest` turns that raw cache into.

None of this is read by the CLI — it's illustrative only.
