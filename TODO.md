# TODO — future feature ideas

Assessed in `docs/todo-review.md`; the agreed sequence lives there.

## Next up

- **Private state repo + run from the phone.** The blocker isn't Claude — it's
  that this repo is public and every file `/daily` reads (`log/`, `data/`,
  `.env`) is gitignored, so a cloud agent gets the code and none of the
  history. Plan: public repo keeps code, plan and tests; a **private** repo
  holds `log/`, `out/`, `data/` and `overrides.md`, cloned in as `state/` and
  reached via a new `MC_STATE_DIR` (`config.py` already centralizes every
  path, so it's four constants). Git is the sync layer, so a two-machine
  conflict fails loudly instead of a cloud drive silently picking a winner —
  `training-log.md`, `strength_schedule.json` and `pushed.json` are all
  whole-file rewrites with no merge logic, and a lost key in the last one
  creates duplicate Garmin workouts. Add `mc state --check` to refuse running
  from a stale checkout, enforcing single-writer-per-day rather than
  documenting it. Credentials live in neither repo: env vars in the cloud,
  local `.env` on the Mac, and `data/.garmin_tokens/` gitignored in both since
  it holds refresh tokens.
  **Needs a decision first:** create the private repo. Then D1-D3 on the Mac
  alone until boring, and only then a second writer.

## Done

- **Edit pushed activities** — a constant HR target now emits one workout step
  instead of warmup/interval/cooldown all at the same HR. The 3-step path
  remains for when warmup gets a target of its own (`push._build_steps`).
- **Auto-send `out/` to phone** — `mc render --all` copies `out/*.html` and
  `today.md` into `MC_EXPORT_DIR`, a plain local folder. Whatever cloud client
  owns that folder does the syncing; no cloud API, no credentials, write-only,
  off unless the env var is set.
- **Persist the week's day layout** — `mc layout` / `data/week_layout.json`.
  `/week` decided the layout and threw it away; now it's remembered, so the
  system can answer "what is Thursday?". Rewritable mid-week under C1 while
  the fixed strength days stay put. Also unblocks multi-day `mc push`.
- **`/plan [n]` (default 3) and `/preview`** — `/daily` now also projects the
  next 2 days; `/preview` closes today out and previews tomorrow, answering
  "early alarm and outside, or elliptical with AC any time?". Projections
  state their assumptions, and can't harden into commitments: never proposed,
  never pushed, and `mc render` skips a stale `out/tomorrow.md`.
- **`mc drift`** — trailing 4 weeks in plain sentences: miles short, which
  days deviated, which reason codes recur, overrides against E5's limit of 2.
  Surfaces the trend before the tripwire. `mc override` is the writer that
  makes the count real; an empty log reports "not tracked yet", never a
  confident zero.

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
