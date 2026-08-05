# Development log

Changes to the **system**. Training-plan decisions live in `plan/plan.md`
(including its dated revision sections); this file is about the code, the
architecture, and the reasoning behind both.

Newest first. Each entry records what changed and — more usefully — *why*,
including the things that turned out to be wrong along the way. Git says what
changed; this says what we learned.

---

## 05-08-2026 — Fuelling, and the muscle group nobody was training

Second half of the NYC-marathon post-mortem. Where the stride-length work below
fixed the *measurement*, this fixes two things the measurement pointed at.

**Fuelling wasn't tracked anywhere.** Reconstructing what was actually eaten in
the 2025 race — 5-6 gels over 4h49 — gives about **27 g of carbohydrate per
hour** against a 60-90 g/hr need. That makes the most likely single cause of a
17-minute positive split the one variable the system never recorded. A measured
long run on 05-08-2026 came in at 43 g/hr: better, still short.

New `mc fuel`, silent under 75 min so it doesn't fire on every easy day.

The design decision worth recording is the **ramp**. The obvious implementation
is a constant race target, and it's wrong: absorption is trainable, and going
from 43 g/hr to race rate overnight produces GI distress rather than
adaptation. So the target climbs 50 → 80 g/hr across the plan, holds flat
through the Italy block (travel is the wrong place for a new GI stressor —
B7's reasoning), and peaks at week 11. Week 11 is flagged explicitly as the
dress rehearsal because **A4 freezes the taper**: it is the last long run that
can test anything.

One thing caught by checking the arithmetic instead of trusting it. Rounding
the gel interval to something a runner will actually follow (nearest 5 min)
means the schedule under-delivers the stated total — 9 gels at 20 min is 225 g
against a 260 g target. Rather than hide the gap or quote an unfollowable
17-minute interval, the plan now names the shortfall and assigns it to drink
mix, which is the realistic strategy anyway. A test asserts the two halves sum
to the total, so the digest can't print a number the schedule beneath it
doesn't deliver.

**The strength routine had no quad work.** It trained calves, tibialis and
glutes: the shins and the hamstring, which are the two tissues that hurt in
*training*. The race failed at neither — quads burned from mile 19, hamstring
was fine at the finish, after a season of avoiding hills specifically to
protect the hamstring. So the quads met 1,447 ft of descent unadapted.

`QUAD_ECCENTRIC_TIERS` added on the existing 3-tier / 3-weeks-per-tier
structure, eccentric-biased because that's what downhill running is, and
knee-dominant with an upright torso so it stays hamstring-safe by the same
standard the module already applies to excluding RDLs.

Noticed while doing it: `bodyweight_only` is declared on `StrengthMobilityItem`
and consumed by nothing except `propose_strength_mobility`. The weighted tier-3
lifts are therefore still offered during the Italy block, which is `no_gym`.
The flag is now set truthfully on all three weighted items, but the fixed
session doesn't read it — flagged in `CLAUDE.md` as a manual swap rather than
silently fixed, since it's a pre-existing behaviour change and not what this
piece of work was for.

---

## 05-08-2026 — Stride length, because cadence missed the one run that mattered

Prompted by reviewing the lap file from the 2025 NYC marathon (02-11-2025,
4:48:58) for lessons for this year's build. The result was a direct critique of
code written the day before.

The race was a 17-minute positive split: 10:22/mi for the first half, 11:25/mi
for the second. Grade-adjusted pace ruled the bridges out as the cause — the
Queensboro climb ran at first-half effort, and the damage was on flat ground at
miles 19-21. What actually collapsed was **stride length**, 0.966m → 0.845m.
Cadence *rose*: 160 spm through Brooklyn, 166-169 over the final three miles.

Which means the within-run decay check built the previous day, keyed on cadence
alone, would have reported **nothing** about the most instructive run in this
athlete's history. Cadence measures turnover; a tiring runner gives up ground
per step first. `metrics.py`'s own docstring had listed `avgStrideLength` under
"deliberately not here — no §6 rule reads them, available the day there's a
question that needs them". That day arrived.

`CadenceSplits` became `RunSplits`, carrying cadence, stride length, raw pace
and grade-adjusted pace as thirds. `directStrideLength` and
`directGradeAdjustedSpeed` were already in the same cached detail payload, so
this stayed at zero extra API calls.

**Two things that turned out to be wrong along the way:**

*Grade-adjusted pace was implemented as a trigger and had to be demoted.* At a
20 s/mi threshold it fired on 10 of 15 real runs. Checking the cache showed why:
a warmup and a cooldown live in the first and last thirds, so a structured run
reads as a collapse — 23369959611 goes 9:01 → 7:28 → 10:06, which is a workout.
Every other threshold in this module errs toward saying nothing; pace decay is
the one metric that would err the other way, so it is now reported as context
beside a cadence or stride trip and never triggers alone. Per-third raw-vs-GAP
terrain cost is printed with it, so "that stretch was uphill" stays separable
from "that stretch was slower".

*The closing sentence asserted a pattern it hadn't checked.* It read "stride
falling while cadence holds is legs, not turnover" on runs where stride had
*risen*. Fixed by naming the actual pattern: cadence easing with stride intact
is what backing off or a cooldown looks like; stride shortening with cadence
held is legs. Still descriptive, never a verdict (§6 D6).

Worth recording: across the whole cached history, every 5mi+ run shows the
benign cooldown shape. None shows the marathon pattern.

---

## 04-08-2026 — Ambient weather, and the Garmin fields we were throwing away

`34f9a21`, `c27a22a`

Started as a question during a `/preview`: the digest only ever read four
fields off each Garmin activity (distance, duration, avg HR, start time), so
what about everything else the same payload carries?

Two separate answers fell out, and the split between them turned out to be
the interesting part.

**The fields were already on disk.** `get_activities_by_date` — one call,
made on every sync since day one — returns cadence, elevation gain/loss and
Garmin's own grade-adjusted speed. `get_activity_details` writes a per-sample
stream for every activity. None of it was read. So `mc.metrics` costs **zero
additional API calls**; it's a parsing change, not a pull. That framing
decided the whole design: no new fetch, no rate-limit budget, nothing to
schedule.

**Weather was the opposite — a genuine gap.** §6 C2 permits a cross-training
swap when "forecast heat is high", and nothing in the system could say what
the forecast was, while the neighbouring C2 triggers (HRV, sleep, RHR)
demanded cited numbers. `/preview` had the same hole at its centre: its entire
reason for existing is "early alarm outside, or indoors any time?", answered
nightly without a temperature. Open-Meteo closes it for one keyless call per
sync, on a different provider from Garmin so it competes for no rate budget.

**Why the heat vocabulary is deliberately not §4's.** `none / noticeable /
hard / extreme`, with a test asserting the two sets stay disjoint. §4's four
verdicts describe how well cross-training substitutes for a run and must never
be invented anew; letting "⚠️ aerobic only" drift into meaning "it's warm out"
would corrupt the one vocabulary the spec pins hardest. Different axis,
different words, enforced.

**`rules.py` was not touched, on purpose.** Heat data is *input to* a decision
a human makes, not a rule that fires. C2 is a permission exercised by citing
numbers, exactly as before — there is now something real to cite.

**Windows are summarised by their worst hour, not their average.** A window is
a commitment to be outside for all of it; averaging a pleasant 06:00 with an
unpleasant 07:45 produces a recommendation that doesn't survive the run.

**Location follows the runs.** Taken from the most recent GPS activity so it
reaches Italy in weeks 8-9 unprompted, rounded to 2dp before it leaves the
machine. The rounding isn't a gesture: Open-Meteo snaps to its own grid
anyway (a 40.7994/-73.9580 request resolves to 40.78858/-73.9661), so finer
coordinates describe a doorstep and buy nothing. `MC_WEATHER_LAT/LON`
overrides and wins when set — which means it keeps reporting home weather
after a flight, so the source used is printed on every run rather than only
when it's interesting.

**Fahrenheit is canonical internally**, Celsius a display conversion. Fetching
in whichever unit was configured would make every threshold in the file depend
on an env var — the same class of bug "miles, always, never km" exists to
prevent.

**Garmin's own temperature stays unused,** and the module says why so nobody
re-adds it: it's a wrist sensor against a warm arm in the sun, measuring the
watch rather than the air.

**What the second commit added, and what it revealed.** Splitting the cached
per-sample cadence stream into thirds *by distance* (not elapsed time — a long
red light shouldn't count as a third of a run) answers what an average
structurally cannot. On real data: 31-07's 10.5-miler held 167/165/165, while
23-07 went 172/174/165. Identical 165-166 averages, completely different runs.

Then `past_days` 1 → 14 in the same single call, so every run in the form
window knows what the air was doing while it happened. 23-07 ran 8:48 at a
53°F dew point; 31-07 ran 9:32 at 66°F.

**The design problem that took the most thought: not building an excuse
machine.** Heat genuinely slows this athlete down *and* is the easiest thing
in the system to hide behind, and E3 says never soften the framing. So
`pace_note` fires only on real outliers (30+ s/mi off the trailing GAP
median), quotes the conditions, and **asks** — "was it hot, was it meant to be
easy, did something hurt?" — rather than concluding. Conditions explain a
pace; they never excuse a session, which still needs the `HEAT` reason code.
The 23-07 case shows why stating conditions unconditionally matters: that fade
happened in the *coolest* air of the fortnight, so the clause ruled heat out
as readily as it would have implicated it. A system that mentioned weather
only when it was hot would be an excuse generator.

**Deliberately not built: a fitted heat-vs-pace number.** With 15 runs and no
session-type labels in the Garmin summary, "hot day" can't be separated from
"that was meant to be a hard 5K". A regression there would read far more
authoritative than it deserves. Per-run conditions plus a question is the
honest version at this n; see TODO for what would change that.

**A pleasant surprise from the data.** Cadence turned out to be nearly
pace-independent for this athlete — 44 s/mi of pace spread (8:48 → 9:32)
moved cadence only 165 → 168. That's what makes a flat baseline usable at all;
for a runner whose cadence swung 10 spm with pace it would have needed banding
by pace first. Recorded as a comment on the threshold, because it's an
assumption that could stop being true.

**Fixed along the way:** `test_garmin_auth`'s `run_sync` test wrote for real,
overwriting the actual `sync_report.json` in `MC_STATE_DIR` with a fabricated
MFA failure on every `pytest` run — pre-existing, but this change would also
have had it making live network calls from the suite.

**Also learned, while deciding whether a Garmin CSV export was worth
importing:** intervals.icu already holds 217 activities / 146 runs back to
2025-07-28, through credentials already in `.env`. The CSV was the worse
version of something already reachable. TODO records the two traps a backfill
would hit — intervals reports single-leg cadence where Garmin reports
double-leg (exactly 2×), and its summary carries no GPS at all.

---

## 03-08-2026 — `/daily` and `/preview` stop auto-rendering HTML

`13e433c`, `cf3942f`

Both slash commands ended their run with `mc render --all`, regenerating
`out/*.html` and `dashboard.html` every single day even though the only
consumer that matters day-to-day is GitHub's markdown viewer.

**Why:** rendering HTML automatically meant every `/daily`/`/preview` diff
carried a machine-generated HTML twin alongside the markdown that was
actually read, for no reader. `mc render` and `MC_EXPORT_DIR` export still
exist and work exactly as before — this only removes the two places that
called them *unprompted*. `/week` never called render, so it was untouched.

**Kept deliberately reversible:** `mc render --all` is still one command
away for anyone who wants the HTML view or the phone-export copy; nothing
about the renderer itself changed, only who triggers it.

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
