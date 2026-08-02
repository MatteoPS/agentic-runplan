# Development log

Changes to the **system**. Training-plan decisions live in `plan/plan.md`
(including its dated revision sections); this file is about the code, the
architecture, and the reasoning behind both.

Newest first. Each entry records what changed and — more usefully — *why*,
including the things that turned out to be wrong along the way. Git says what
changed; this says what we learned.

---

## 02-08-2026 — Headless Garmin auth

`14c8237`

Whether an MFA prompt is possible is now **detected** (`garmin.is_interactive`,
via `sys.stdin.isatty()`) rather than declared.

**The bug wasn't a missing flag — it was an unreachable code path.** A perfectly
good `GarminAuthError` for "non-interactive run, can't do MFA" had existed in
`garmin.py` since the start, and nothing in `cli.py` ever passed
`interactive=False` to reach it. On a machine with an expired token, `mc sync`
called `input()`, hit a closed stdin, and died with a bare `EOFError`.

Detection beats a flag here because the callers that need the non-interactive
path — cron, a cloud session running `/daily` from the phone — are precisely
the ones that won't think to pass one. Three intermediate layers
(`sync.run_sync`, `push_workout`/`unpush_workout`, `sync_garmin`) also had to
change from `bool = True` to `bool | None = None`, or they'd have passed a
hardcoded `True` straight past the detection.

Also: `_prompt_mfa_interactive` now converts `EOFError`/`KeyboardInterrupt` to
the same error, because `isatty()` can be True and the read still fail. And the
old message told you to run `uv run python -m mc.sync`, which isn't a real
command — it now says `uv run mc sync`.

**Still true:** the first run on any new machine needs one interactive login.
Only a human can read the MFA code. This made the failure legible, not
impossible.

---

## 02-08-2026 — Personal state split into a private repo

`106e2ea` · [marathon-2026-state](https://github.com/MatteoPS/marathon-2026-state) (private)

`MC_STATE_DIR` repoints `DATA_DIR`, `LOG_DIR`, `OUT_DIR` and
`OVERRIDES_LOG_PATH` at a separate private repo. Unset, `STATE_ROOT ==
PROJECT_ROOT` and nothing changes.

**Why:** this repo is public, and every file `/daily` reads — `log/`, `data/`,
`out/` — is real training and health data, gitignored for exactly that reason.
That made "run `/daily` from my phone" impossible: a cloud agent clones the
code and none of the history. Splitting by *what a file is* rather than by
branch makes the leak structurally impossible instead of carefully avoided.

**Rejected: a private fork with cherry-picks back to public.** It relies on
discipline at the exact moment discipline fails — one `git push` from the wrong
branch publishes a month of health data — and the two histories diverge from
the first `.gitignore` change onward, making every feature a cherry-pick.

**Git as the sync layer, deliberately.** Three state files are
read-modify-**rewrite-whole-file** with no merge logic:
`log/training-log.md`, `data/strength_schedule.json`, `data/pushed.json`. Two
machines writing the same day loses one silently, and a lost key in
`pushed.json` makes the next push *create a duplicate* Garmin workout rather
than updating in place. A cloud drive resolves that class of conflict quietly
or leaves a `(conflicted copy)` nothing reads; git refuses and makes you look.
For an audit trail whose whole value is being trustworthy, loud beats silent.

So `mc state --check` refuses to run from a checkout that's behind, and
`--save` commits and pushes. Single-writer-per-day is **enforced, not
documented**. Tested against two real clones of a bare remote.

**What's tracked, and the one non-obvious call:** `data/raw/garmin/wellness/`
*is* committed even though it's "cache", because `mc sync` only looks back
`WELLNESS_LOOKBACK_DAYS = 7` — HRV/sleep/RHR older than a week **cannot be
re-fetched**, and it's the evidence behind every `READINESS` decision. The 55M
of activity/intervals cache is not tracked: re-fetchable by ID, and it would
grow git forever.

Credentials are in **neither** repo, including `data/.garmin_tokens/` — it
holds refresh tokens, and a private repo is still a history every clone and
integration can read.

**Known unresolved risk:** garth refreshes Garmin tokens on use, so two
machines refreshing independently can invalidate each other and force an
interactive MFA prompt a headless run can't answer. One writer per day avoids
it; there's no clean fix if it happens.

---

## 02-08-2026 — `mc drift` and `mc override`

`b117026`

A plain-language 4-week report: miles short, which days deviated, which reason
codes recur, overrides against E5's limit of 2.

**Why:** §6 E5 only fires *after* 2 overrides in a block have happened. By then
the drift already occurred — the useful signal was in the preceding weeks, in
the shape of what kept going wrong. Three SHIN deviations and a 15% shortfall
is a plan that needs revising whether or not anyone typed OVERRIDE.

Reports counts and dates only. Never a diagnosis (§6 D6), never a plan change —
that's the agent's job with §6 in hand.

**Caught by checking against the real log, not the fixtures:** Proposed and
Actual need *opposite* parsing rules. `/daily` often continues a Proposed cell
into the rest of the week ("10.5mi (locked 11.0); Sat 01-08 3mi easy, Sun 02-08
2mi easy"), so summing it reported a 4-mile shortfall that did not exist. The
day's own distance is always the first figure; the Actual column is
machine-written and genuinely lists every activity, so it still sums.

`context/overrides.md` had no format and no writer — E4/E5's count was
uncountable. `mc override` is that writer. Until it's used, drift says
"not tracked yet" rather than a confident `0`.

---

## 02-08-2026 — Week layout, `/plan [n]`, `/preview`

`2f7aeeb`

`plan.lock.json` freezes weekly totals only; day-of-week placement is
deliberately not frozen and was being decided conversationally in `/week` and
then **thrown away**. The system could describe today and nothing else —
"what is Thursday?" had no answer anywhere in the repo.

`mc layout` (`data/week_layout.json`) persists what `/week` already computes.
It also silently unblocked multi-day `mc push`, which `push.md` had been
advertising even though `_check_today_md_date` refused any date but today's.

**The subtle constraint:** the layout is rewritable mid-week (C1 lets easy runs
be reordered freely), but `strength.set_fixed_days` stays first-write-wins, or
"unskippable" stops meaning anything. `revise()` therefore never calls into
strength; there's a regression test asserting a reshuffle doesn't re-pick the
fixed days.

**Found while writing tests:** a layout that stored only miles can't be checked
against A8/A9, which weigh cross-training by minutes. Cross days now carry
minutes rather than miles — matching how cross is prescribed everywhere else in
the project.

`/plan [n]` (default 3) and `/preview` sit on top. Day 1 is ACTUAL; days 2+ are
PROJECTED under stated assumptions. **The failure mode being designed against
is a projection quietly hardening into a commitment**, so: never `mc propose`d,
never pushed (`mc push` refuses anything marked provisional, scoped so
`/daily`'s appended lookahead doesn't false-positive), no substitution table
(a same-day judgement), and `mc render` skips a stale `out/tomorrow.md` instead
of turning yesterday's guess into a fresh-looking page.

---

## 02-08-2026 — Constant-HR workouts collapse to one step; `mc export`

`a0974b4`

`build_workout` emitted warmup + interval + cooldown all carrying the **same**
HR target — three watch alerts for one instruction, and a mid-run "cooldown"
banner for a run that was one continuous effort. Now one step when the targets
match. The 3-step path is kept, with a tripwire test, for when warmup gets a
target of its own.

`mc export` copies `out/*.html` and `today.md` into `MC_EXPORT_DIR`. Chosen
over a Google Keep / Apple Notes integration because this is file sync, not an
API problem: a plain local copy needs no OAuth, no credentials, no network call
and no new dependency, and works with whatever cloud client owns the folder.
Write-only, so a conflict-mangled copy in a cloud folder can never re-enter the
system's state.

It refuses to create the destination if the *parent* is missing — that means
the sync root isn't mounted, and silently creating a stray local tree would
report success every day while the phone showed nothing.

---

## 02-08-2026 — TODO feasibility review

`a1f2caf` · `docs/todo-review.md`

Assessed each TODO item for cost and value before building anything. Two
conclusions worth keeping:

**Pushing elliptical as "elliptical" is not possible.** Garmin's workout sport
types are `RUNNING CYCLING OTHER SWIMMING STRENGTH_TRAINING CARDIO_TRAINING
YOGA PILATES HIIT MULTI_SPORT MOBILITY`. Elliptical exists as an *activity*
type the watch records, not a workout type the API can create, so
`cardio_training` was already the only correct choice.

**A PC GUI is deferred indefinitely**, and not for effort reasons: a GUI has to
re-express §6 in a second place, and a second gate is a drift-shaped hole in an
anti-drift system.

---

## 31-07-2026 — Initial system

`bfd9b02`, `0fff72b`

Plan lock, rule engine (§6 A–E), Garmin + intervals.icu sync with
cross-source reconciliation, digest, equivalence engine, strength progression,
render, push, and the `/daily` `/week` `/travel` `/italy` `/push` commands.
209 tests.

See `plan/plan.md` for the training-plan reasoning (18→14 compression, the
Italy block, the shin adaptation) and `instructionforclaudecode.md` for the
original spec.
