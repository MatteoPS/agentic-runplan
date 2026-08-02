# TODO — future feature ideas

Assessed in `docs/todo-review.md`; the agreed sequence lives there.

## In flight

- **`/plan [n]` (default 3) and `/preview`.** `/daily` produces today plus the
  next 2 days. Day 1 uses real data (sleep, HRV, RHR, yesterday's actual);
  days 2-3 are projections assuming normal sleep, full compliance and no new
  injury, and say so. `/preview` runs at the end of the day: logs what was
  actually done, then previews tomorrow under the same assumptions — enough to
  decide early alarm + outdoor vs. elliptical with AC. Provisional output is
  never pushed and never written to `log/training-log.md`.
- **Persist the week's day layout** (`data/week_layout.json`). Prerequisite for
  the above: day-of-week is currently decided in `/week` and discarded, so
  nothing can answer "what is Thursday?". Also unblocks multi-day `mc push`,
  which `push.md` advertises but which can't work today.
- **`mc drift`.** Plain-language 4-week summary: which reason codes keep
  appearing, planned vs. actual miles, override count against the E5 limit of
  2. The point is to surface "the plan isn't matching my life" *before* the
  tripwire. Needs a format and a writer for `context/overrides.md` first — it
  currently has no entries and no code path.
- **Private state repo + run from the phone.** Public repo keeps code, plan and
  tests; a private repo holds `log/`, `out/`, `data/` and `overrides.md`,
  cloned in as `state/` and reached via `MC_STATE_DIR`. Git is the sync layer,
  so a two-machine conflict fails loudly instead of a cloud drive silently
  picking a winner. Credentials live in neither repo — env vars in the cloud,
  local `.env` on the Mac. Only worth starting once the rest is boring.

## Done

- **Edit pushed activities** — a constant HR target now emits one workout step
  instead of warmup/interval/cooldown all at the same HR. The 3-step path
  remains for when warmup gets a target of its own (`push._build_steps`).
- **Auto-send `out/` to phone** — `mc render --all` copies `out/*.html` and
  `today.md` into `MC_EXPORT_DIR`, a plain local folder. Whatever cloud client
  owns that folder does the syncing; no cloud API, no credentials, write-only,
  off unless the env var is set.

## Not doing

- **Push elliptical as "elliptical".** Not possible. Garmin's workout sport
  types are `RUNNING CYCLING OTHER SWIMMING STRENGTH_TRAINING CARDIO_TRAINING
  YOGA PILATES HIIT MULTI_SPORT MOBILITY` — elliptical isn't among them. It
  exists as an *activity* type the watch records, not a workout type the API
  can create, so `push.py`'s `cardio_training` is already the only correct
  choice. Worth one on-watch test: start the Elliptical activity and see
  whether the Cardio workout is selectable there.
- **Standalone iPhone app.** Superseded by the private-state-repo route, which
  reaches the same goal without reimplementing ~4,200 lines of `mc` on a
  platform that can't run it.
- **Apple Health integration.** Tempting because the Garmin isn't always worn
  but the phone always is. Skipped anyway: the digest and rule engine are built
  on Garmin's HRV/sleep/RHR shape, and mixing a second sampling source would
  weaken exactly the readiness signals C2/D4 depend on, in exchange for step
  counts. `READINESS` requires citable data, and a noisier second source makes
  that harder to satisfy honestly.

## Deferred

- **PC GUI.** Re-ask after `/plan`, `/preview` and the export have been live a
  couple of weeks — most of the want may turn out to be those. The cost isn't
  code volume, it's that a GUI has to re-express §6 in a second place, and a
  second gate is a drift-shaped hole in an anti-drift system. If the want
  survives, a **read-only** dashboard (extend `render.build_dashboard_html`) is
  most of the value at little of the risk.
