# TODO — future feature ideas

Assessed in `docs/todo-review.md`; the agreed sequence lives there.

## Next up

- **Backfill a year of history — from intervals.icu, not a Garmin CSV.**
  Probed 04-08-2026: intervals.icu already holds **217 activities / 146 runs
  back to 2025-07-28**, through the API key that's already in `.env` and the
  client that's already in `src/mc/intervals.py`. A manual CSV export is
  therefore the worse version of a thing already reachable — unstructured,
  un-repeatable, and stale the day after it's downloaded. What's needed is
  raising `MAX_SINCE_DAYS` (150 today) and a one-off backfill path, not a
  parser.

  **What it would unlock, specifically:** 146 runs spanning summer 2025 →
  winter → summer 2026 crosses seasons, which is the one thing that makes a
  *fitted* heat-vs-pace relationship defensible. Right now `pace_note` can
  only say "you were 30 s/mi slow and the dew point was 66°F, was it the
  heat?" — with a season of data it could say what this athlete's own pace
  actually does per 10°F of dew point, which is citable evidence for a §6 C2
  swap instead of a question.

  **Two traps, both confirmed against real data:**
  1. intervals reports **single-leg** cadence (83.9) where Garmin reports
     **double-leg** (167.65) — exactly 2×. A backfill that merges them
     naively halves the cadence baseline and every note built on it goes
     quietly wrong. Normalise on the way in, and assert the merged
     distribution doesn't straddle both conventions.
  2. intervals' activity summary carries **no GPS coordinates**, so historical
     runs can't be weather-attributed the way current ones are. Open-Meteo's
     archive API can backfill from an *assumed* location, which is fine for a
     mostly-NYC year but is an assumption that must be recorded per row, not
     folded silently into the numbers.

  **Not urgent.** The season generates this data anyway, and n grows weekly.
  Worth doing when the "was it hot?" question has been asked enough times to
  be worth answering in advance — not before.

  **Explicitly out of scope:** retrospective correlation of shin symptoms
  against past mileage. That's the diagnosis-shaped inference D6 rules out,
  and a year of n=1 observational data is exactly enough to produce a
  confident wrong answer.

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

## Done

- **Edit pushed activities** — a constant HR target now emits one workout step
  instead of warmup/interval/cooldown all at the same HR. The 3-step path
  remains for when warmup gets a target of its own (`push._build_steps`).
- **Get `out/` onto the phone** — solved twice over, pick either:
  1. **GitHub mobile app** (zero setup). `out/` is in the private state repo,
     so `out/today.md` is readable from the app the moment `mc state --save`
     runs. Markdown renders natively there; the `.html` twins show as source,
     so read the `.md` on the phone.
  2. **`MC_EXPORT_DIR`** — `mc render --all` copies `out/*.html` and
     `today.md` into a plain local folder. Whatever cloud client owns that
     folder syncs it. No cloud API, no credentials, write-only, off unless
     the env var is set. Worth it only if you want the *rendered* HTML or
     offline access; otherwise the GitHub app is simpler and already works.
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
- **Headless `mc sync`** — whether an MFA prompt is possible is now detected
  from the terminal (`garmin.is_interactive`), so a cron job or cloud session
  gets the clear `GarminAuthError` that already existed instead of blocking on
  `input()` and dying with `EOFError`. No flag needed, which matters because
  the callers that need it are the ones that won't pass one;
  `--non-interactive` forces it. `mc sync` reports the failure as a clean
  `ok: false` source, so `/daily` step 1 says the data didn't arrive (§7).

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
