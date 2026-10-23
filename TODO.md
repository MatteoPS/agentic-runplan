# TODO — future feature ideas

Assessed in `docs/todo-review.md`; the agreed sequence lives there.

## Next up

- **Agent confusion — cross-training is minutes, not miles, and the units
  convention doesn't say so where the agent actually reads it.** Recurring
  pattern, noticed 08-09-2026: the agent drafts a cross day in miles (matching
  the CLAUDE.md line "Units: miles and min/mile. Always."), then self-corrects
  after hitting the actual number in `mc` output or `layout.py`. It always
  ends up right, but only after a visible stumble in the transcript.

  The code itself is not confused — `DayPlan.cross_minutes` is an explicit
  field, `layout.py:81-85` spells out "Running days carry miles; cross days
  carry minutes," and `push.py:360` documents the same split for parsing. The
  gap is that CLAUDE.md's units paragraph — the thing read every session
  before any plan is drafted — states the run unit ("miles and min/mile") but
  never says cross-training's *quantity* is duration, not distance, so there's
  nothing at that altitude to stop the first draft from reaching for miles.

  Fix is documentation, not code: add one explicit line to CLAUDE.md's units
  convention (or wherever `/daily`, `/week`, `/plan` state their output
  format) — e.g. "Cross-training days are prescribed and logged in minutes,
  never miles or mi-equivalent" — right next to the existing units line, so
  the distinction is visible at the point a prescription gets drafted rather
  than only in `layout.py`'s docstring, which nothing prompts the agent to
  re-read every session.

- **BUG — `mc fuel`'s own output contradicts itself on carb-bottle refills.**
  Found 08-09-2026 while checking the 09-09 15-miler's fuel plan. The prep
  section correctly says the carb mix goes in **once, at the start** and
  refills are water + a fresh tab only — matching `carb_sachets`'s docstring
  (`fuel.py:278-286`, the 17-08-2026 decision). But the "Carry" line
  (`fuel.py:450-452`) says the opposite: "Re-dose the carb bottle from a
  sachet at each refill." Same command, same output, two answers.

  Root cause: `carbs_from_bottles` (`fuel.py:261-271`) still computes its
  "the bottle could deliver ~N g" ceiling assuming per-fill re-dosing — a
  leftover from the abandoned pre-17-08 drink-led design that `carb_sachets`
  was already fixed to reject. Its docstring even says so ("Re-dosed from a
  sachet at every refill") right next to the one that says the opposite. Fix:
  make `carbs_from_bottles` reflect one dose at the start (i.e. just
  `carb_g_per_fill`, not `(refills + 1) * carb_g_per_fill`), and rewrite the
  `fuel.py:450-452` line to match the prep section's wording. Add a regression
  test asserting the "Carry" section's text and `carbs_from_bottles`'s value
  agree with the once-at-start protocol.

- **URGENT — two devices, one day: the concurrency rules are not written down,
  and today proved the lease does not cover what I assumed it did.**
  Raised 13-08-2026, out of the first cloud-session run. This blocks relying on
  `/daily` from the phone while the Mac is also in use — which is precisely the
  Italy setup, so it wants settling before 10-09.

  **What today actually demonstrated, not hypothesised.** While a cloud session
  worked on a branch, the Mac pushed three commits to `main` (a weather test
  fix and a git-identity hook). Both devices had added a second `SessionStart`
  hook in the same position, so `.claude/settings.json` conflicted for real.
  That one ended well — git refused to merge, the conflict was structural and
  additive, and both hooks survived. **That is the good case**, and it is worth
  being clear about why: the file conflicted *textually*, so git could see it.

  **The bad case is the one the lease exists for and today did not test.**
  `log/training-log.md`, `data/strength_schedule.json` and `data/pushed.json`
  are rewritten whole. Two devices writing the same day does not reliably
  produce a conflict there — it produces a clean-looking file that silently
  lost one side. `pushed.json` is the sharpest: a lost key makes the next
  `mc push` create a **duplicate Garmin workout** rather than update in place.

  **And the lease is thinner than the CLAUDE.md paragraph makes it sound.** It
  is advisory, only as fresh as the last fetch, and narrows the window to the
  seconds between claim and push — all of which is stated, but the practical
  consequence is not: on a **fresh branch it does not push at all** (git aborts
  for want of an upstream, `git push -u origin <branch>` fixes it), so the
  day's *first* claim protects nothing unless that has been done. A rule that
  silently no-ops on the first use of the day is not yet a rule.

  **Evidence it is not merely theoretical:** this very session ran `mc sync`
  without holding a lease and overwrote `data/sync_report.json` — replacing the
  Mac's good 03:40 report with a record of its own failed sync — plus the
  digest. Caught only by looking at the diff before committing. Nothing
  enforced anything; nothing warned.

  **Questions the rules have to answer**, none of which have an agreed answer
  today:
  1. Does a read-only-looking command that writes state (`mc sync`, `mc digest`,
     `mc render`) require a lease, or only `/daily` `/week` `/preview`? Today
     the ritual is documented as the unit, but `mc sync` writes state outside
     it.
  2. What happens when the lease is held by the *other* device and I genuinely
     need to write — wait, `--force`, or is there a merge path? `MC_LEASE_TTL_MIN`
     expiry is a timeout, not an answer.
  3. Should the three whole-file-rewrite files get a real merge or an
     append-only format, so git can see a conflict instead of a clean
     overwrite? That is the only fix that removes the silence rather than
     narrowing the window.
  4. Which branch does a phone session write to — `main` directly (verified
     possible 13-08) or a branch someone merges? Direct `main` removes a step
     and removes the branch-conflict safety net at the same time.

  Until they exist, the operating rule is the conservative one: **one device
  per day, and the phone only when the Mac is off.** State that plainly rather
  than trusting the lease to arbitrate.

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

  **Two traps, both confirmed against real data — and both now handled in
  code** (12-08-2026), which makes this item smaller than it was:
  1. intervals reports **single-leg** cadence (83.9) where Garmin reports
     **double-leg** (167.65) — exactly 2×. A backfill that merges them
     naively halves the cadence baseline and every note built on it goes
     quietly wrong. **Now normalised on the way in** by
     `sources.CADENCE_LEG_FACTOR`, re-confirmed across 28 runs present in both
     caches, with `tests/test_sources.py` asserting the two parsers produce
     identical streams. A backfill inherits this for free. (The same probe
     found a conversion this note missed: step length is **millimetres** where
     Garmin's `directStrideLength` is centimetres.)
  2. intervals' activity summary carries **no GPS coordinates**, so historical
     runs can't be weather-attributed the way current ones are. **Partly
     solved**: coordinates do exist in the per-activity `latlng` stream and
     `intervals.pull_first_fix` reads them, so a backfill *can* place each run
     rather than assuming — at the cost of one stream call per activity, which
     over 217 activities is the thing to weigh. If that cost is refused,
     Open-Meteo's archive API can backfill from an *assumed* location, which
     is fine for a mostly-NYC year but is an assumption that must be recorded
     per row, not folded silently into the numbers.

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

- **Verify `context/downhill.md`'s grades against the Strava API.** That file
  drives the whole downhill progression — Harlem Hill, the Morningside
  escarpment, the Riverside ramps — and every location in it is tagged
  `[VERIFY]`: general knowledge of Manhattan geography, not a survey. The
  progression counts *continuous descents of ≥100 ft*, so if Morningside is
  really 60 ft rather than 150, week 5's prescription is wrong and nobody
  finds out until race day.

  **Strava's API can answer this properly.** `GET /segments/{id}` returns
  `average_grade`, `maximum_grade`, `elevation_high`, `elevation_low` and
  `distance`; `GET /segments/explore` finds segments inside a bounding box and
  can filter to climbs. Running explore over a box covering Central Park,
  Morningside and Riverside, then pulling the detail for each hit, turns every
  `[VERIFY]` tag into a real number and would probably surface sustained
  descents nobody thought to look for.

  **Cost, honestly assessed:** this needs a new OAuth integration (Strava is
  OAuth2 with refresh tokens, unlike the API-key clients already in `.env`),
  which is real work for a **one-off measurement**. The output is a static
  table of grades that doesn't change. So the cheap version — open Strava or
  a topo map by hand, write the real numbers into `downhill.md`, delete the
  `[VERIFY]` tags — probably wins unless route-picking becomes a recurring
  need. Segment *descents* are also awkward: Strava indexes climbs, so a
  descent is usually the reverse of a climb segment and may not exist as its
  own entry.

  Either way the tags must not survive into the peak weeks unchecked.

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
