# TODO — future feature ideas

Assessed in `docs/todo-review.md`; the agreed sequence lives there.

## Next up

- **Run `/daily` from the phone.** The state split below is done, which was
  the blocker — a cloud agent can now clone code (public) + history (private)
  and have everything `/daily` reads. What's left is the environment, not this
  codebase: a cloud Claude Code session with network egress to Garmin and
  intervals.icu, `GARMIN_*` / `INTERVALS_*` injected as **environment
  secrets** (never a synced file), and `MC_STATE_DIR` pointed at the private
  clone. Then `mc state --save` at the end of a phone `/daily` and the Mac
  picks it up on its next `--check`.
  **Do this only once the split has been boring on the Mac for a couple of
  weeks.** One unresolved risk: garth refreshes Garmin tokens on use, so two
  machines refreshing independently can invalidate each other and force an
  interactive MFA prompt a headless run can't answer. One writer per day
  avoids it; there's no clean fix if it happens.
- **Headless `mc sync`.** Nothing in `cli.py` passes `interactive=False`, so
  on a machine with an expired token `mc sync` blocks on `input()` and dies
  with `EOFError` instead of the clear `GarminAuthError` that already exists
  for exactly this case (`garmin.py:87-92`). Small fix, needed before D4.

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
- **Private state repo** — [marathon-2026-state](https://github.com/MatteoPS/marathon-2026-state),
  wired via `MC_STATE_DIR`. This repo stays public and code-only; personal
  data physically cannot be committed here. Credentials in neither repo.
  `data/raw/garmin/wellness/` *is* tracked (HRV/sleep/RHR older than 7 days
  can't be re-fetched); the 55M of activity/intervals cache is not.
  `mc state --check` / `--save` enforce one-writer-per-day rather than
  documenting it, and `/daily`, `/week`, `/preview` call them.

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
