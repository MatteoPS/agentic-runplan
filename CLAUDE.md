# marathon-2026

> Before proposing any change to training, load `plan/plan.lock.json` and run
> `mc check`. If a proposal violates a rule, say so and propose a compliant
> alternative. **Do not present a violating plan with a caveat.** Do not agree
> with me that a rule should be bent — only an explicit typed `OVERRIDE:`
> does that. Units are miles and min/mile. Weeks are `Week N · w/c DD-MM`.
> Days are `DD-MM`.

Adaptive marathon training system for me — NYC Marathon, Sun 01-11-2026.
Base plan: Hal Higdon Intermediate 1, compressed 18→14 weeks, shin-adapted,
with a 3-week Italy trip built into `plan/plan.lock.json` as its own block.
Full spec: `instructionforclaudecode.md`. Frozen plan and its design
decisions: `plan/plan.md`.

## Running things

`uv run mc <command>` — see `mc --help`. `uv run pytest` for the test suite.
`mc today` first, always: it prints the training day and the timezone it came
from, and that day — not the system clock, and not your own sense of the date —
is what every `DD-MM` written that session must use.
Never call Garmin outside an explicit `mc sync` — everything else reads the
local cache under `data/` (gitignored, regenerated on demand).

## Date & unit conventions

- **Units: miles and min/mile. Always. Never km.**
- **Weeks**: `Week N · w/c DD-MM` (week starts Monday). Prefer the date over
  the number.
- **Days**: `DD-MM` (e.g. `28-07`). Never "Tuesday of week 3" alone.

## The daily ritual

`/daily` runs: `mc today` (the day every `DD-MM` written that session uses) →
`mc sync` (which also refreshes the forecast) → `mc digest` →
read the digest + `plan.lock.json` +
`context/` + last 14 days of `log/` → ask **at most 4** questions (feel 1-10,
sleep, shins/hamstring, anything changing in the next 7 days — never more,
never pad), **plus a 5th only when a fixed strength day from earlier this
week still needs a done/missed confirmation** → `mc check` → write
`out/today.md` → `mc render --all` (dashboard refresh + `out/` tidy) →
append to `log/sessions/`. See `.claude/commands/daily.md` for the exact
format, including which sections are conditional (substitutions, strength) and
which fire on their own (fuelling, on long days).

Other slash commands: `/week` (Monday review), `/plan [n]` (next n days,
default 3), `/preview` (end of day: log today, project tomorrow), `/travel`
(unplanned trip reshuffle), `/italy` (the known trip block, weeks 8-9),
`/push` (preview and push workouts to Garmin Connect — opt-in, never
automatic).

## Provisional vs. committed (added 02-08-2026)

The day layout for each week is decided in `/week` and **persisted** via
`mc layout` (`data/week_layout.json`) — `plan.lock.json` freezes weekly
totals only, so without this nothing can answer "what is Thursday?".

`/daily` now also projects the next 2 days, and `/preview` projects tomorrow.
Those projections assume normal sleep, full compliance and no new injury —
assumptions that must be **printed, never implied**. A projection must never
harden into a commitment: projected days are never `mc propose`d, never
pushed (`mc push` refuses anything marked provisional), and get no
substitution table, because whether to swap a run for the elliptical is a
same-day judgement. `mc tidy` deletes a stale `out/tomorrow.md` rather than
letting yesterday's guess sit there looking fresh.

Optional: `MC_EXPORT_DIR` in `.env` makes `mc render --all` copy `out/*.html`
and `today.md` into that local folder — typically one a cloud client already
syncs to the phone. Plain file copy, no cloud API, write-only, nothing read
back.

## out/ holds only what's current; markdown is the output (added 08-08-2026)

Nothing used to delete anything from `out/`, so it accumulated a `tomorrow.md`
for a day that had passed, HTML twins days older than the markdown they claimed
to render, and one-off documents that outlived their day. A stale file there is
worse than a missing one: missing is obvious, stale looks exactly like current,
and `out/` is what gets read on a phone at 6am.

`mc tidy` enforces one principle: **a file in `out/` must declare the day it is
for, and one whose day has passed is deleted.** Two ways to declare it, both
already conventions here rather than new syntax — a `# DD-MM` header in the
markdown (what `/daily` and `/preview` already write), or a `-DD-MM` suffix on
the filename (which retires `race-strategy-08-08.md` and every future dated
one-off with no registry to maintain). The header wins over the filename: we
believe the file, same precedent as `push._check_today_md_date`. An `.html`
whose `.md` is gone or newer goes too. `dashboard.md` is exempt — it is a
rolling view of the whole plan, not a document about a day. A `.md` carrying
**no** date signal is **reported and left alone**; silently deleting something
unrecognised is the wrong instinct for a folder a person keeps things in.
Deletion loses nothing — the state repo's git history and `log/sessions/` are
the durable record.

**HTML is opt-in.** `mc render --all` refreshes `out/dashboard.md`, tidies, and
exports — no `.html` at all. `mc render --all --html` adds the standalone
twins. The machinery all stays, one flag away; it was being generated on every
run and read by nobody, since the output is read as markdown on GitHub.

**The dashboard refreshes daily**, not weekly. `/daily`, `/preview` and `/week`
all run `mc render --all`, so completion percentages and finished runs move
every day. (Before this, *no* slash command ran it — the dashboard was stale
until refreshed by hand.)

## Mid-week compliance is checked against the week as proposed (added 08-08-2026)

§6's A-rules are **whole-week** metrics. `mc check` used to build its
`ProposedWeek` from actuals-so-far, which is a category error: A2's floor is a
fraction of the week's *planned* miles, so on a build week (floor 0.95) it
**cannot** pass before roughly Saturday. A1/A3 fired until the long run
happened, A10 until the third running day, and A9 worst of all — a partial
denominator makes the ratio *worse*, so an 11 mi long run done first in a 25 mi
week read as 100% against a 0.39 cap. Every mid-week run produced warnings that
were arithmetic rather than findings, and warnings you dismiss daily are
warnings you stop reading.

`mc check` now judges the **blend**: actuals for the days already settled, the
persisted layout for the days still ahead. Per day — anything before today
counts what actually happened (0.0 when nothing was logged; a miss is real),
today and later count the layout **unless** that day already has a logged
activity, in which case actuals win (`/preview` runs after the session, and a
day run longer than planned should count what was run). `long_run_mi` takes the
layout's figure only while the long-run day is still ahead; once it has passed
unrun, the shortfall is the finding.

This silences arithmetic, **not findings**. A skipped Tuesday still drags the
projection under the floor and A2 still fires — so a mid-week violation is
real, and must never be waved off as "we're only on Wednesday". The remedy is
`mc layout <n> --week-start DD-MM --revise` (C1, free, no approval), not an
override.

**Degraded tier**: with no persisted layout there is nothing to project from,
so the cumulative rules are suppressed and `mc check` **says so**, naming what
it stopped judging. Quieter output that hides what it gave up on would be worse
than the noise it replaced. Same rule-ID sets `mc push` already used
(`rules.PARTIAL_WEEK_BLOCKING_RULE_IDS` / `LONG_RUN_EVENT_RULE_IDS`, moved into
`rules.py` so there is one definition). `--actuals-only` forces this tier;
`--as-of DD-MM` moves the reference day.

`mc drift` needed no change — it is day-granular and pairs proposed against
actual per row, skipping `PENDING`, so a partial week just contributes fewer
days to both sides.

## One private repo, code and state together (merged 12-08-2026)

**This repo is private and holds everything** — `src/`, `tests/`, `plan/`,
`context/`, and the real `log/`, `out/`, `data/`. `MC_STATE_DIR` is **unset**,
so `config.py` resolves `STATE_ROOT == PROJECT_ROOT` and there is one root.

It was two repos from 02-08 to 12-08: a public `agentic-runplan` holding code,
with `MC_STATE_DIR` pointing at a private `marathon-2026-state` for personal
data. That split made a leak structurally impossible rather than a matter of
discipline, which was the right trade while the public repo was the working
one. It stopped being right when the goal became running `/daily` from a
phone: a cloud session needs **one** repo it can clone and run, and the
private half held no code.

`agentic-runplan` still exists at its URL, now a frozen showcase. Refresh it
with `scripts/publish.sh` — an **allowlist**, not an exclude-list, because the
failure mode is publishing training and health data irreversibly to a public
repo, and an exclude-list fails open the first time someone adds a directory
and forgets to exclude it. It dry-runs by default.

Credentials are still in **no** repo. `.env` is local; so is
`data/.garmin_tokens/`, which holds refresh tokens and is credential material
however private the repo is. The intervals.icu key sits in `.env` alongside
the Garmin password — the safer of the two (scoped, revocable on its own,
cannot reach back into Garmin), but still a credential and still belonging
nowhere git can see.

**What the merge changed about what is tracked**, since the two `.gitignore`s
said opposite things about the same paths and both had been right:

- `out/`, `log/`, `context/overrides.md` — were ignored *because the repo was
  public*. Now **tracked**. They are the durable record, and `mc tidy` deletes
  from `out/` on the understanding that git history is what makes that safe.
- `writer.json` — the public repo ignored it. That rule is now actively
  **wrong**: the lease only protects anything if the other device can fetch it.
- `data/raw/garmin/activities/` — **stays ignored**. ~55M of daily-changing
  JSON, re-fetchable by id.
- `data/raw/intervals/` — now **tracked**, the reverse case. It is the primary
  source for a session without Garmin credentials, and such a session is
  ephemeral; ignored, every run would re-fetch the whole window. Only dated
  duplicate snapshots are skipped — `latest.json` holds the same content under
  a stable name.

  The cost is real and worth stating properly: ~314 KB per stream file, only
  for runs ≥5 mi, so ~600 KB/week. `prune_streams` (30 days) bounds the
  **working tree**, not history — git keeps every object forever, so the repo
  grows monotonically, roughly +7 MB by race day against 4.5 MB today. Fine,
  but it is growth rather than a ceiling, and "bounded by the prune" would be
  the wrong thing to remember.
- `data/raw/garmin/wellness/` — **still tracked**, unchanged and for the
  unchanged reason: `mc sync` only looks back 7 days, so HRV/sleep/RHR older
  than that cannot be re-fetched, and it is the evidence behind every
  `READINESS` call.

**One writer per day, and it says which device it is** (lease added
05-08-2026). `mc state --check` catches a checkout that is behind something
already *pushed*. It cannot catch two rituals **in flight at once** — phone
and laptop both fetch clean, both write the day, and the second save either
loses the first or lands on a rejected push. So a write is announced before
it happens: `mc state --claim "<purpose>"` writes `writer.json` (device, time,
purpose) into the state repo, commits and pushes it, and refuses if another
device holds a live one. `mc state --save` clears it in the same commit and
stamps `Device: <id>` on the history. `mc state --release` for a ritual that
ends without writing. `MC_DEVICE` names the device (hostname otherwise);
`MC_LEASE_TTL_MIN` expires a lease (default 120) so an abandoned session on a
flat phone never locks the laptop out.

**One `/daily` per day, too** (added 14-08-2026). The lease answers "is someone
writing *right now*" and says nothing about a ritual that already finished, so
a second `/daily` hours later — same device or the other one — sailed through:
it rewrites a prescription I have already acted on, re-`propose`s the same
training-log row, logs the day twice, and re-asks the four questions to be
answered from a different mood. So `mc state --claim "daily DD-MM"` now
**refuses** when `out/today.md` already carries today's `# DD-MM` header, and
names what I actually wanted instead — `mc sync` for data recorded since,
`/preview` to close the day out, or just re-reading `out/today.md`. The file's
own header is the evidence, not its mtime: same "believe the file" precedent as
`mc tidy` and `push._check_today_md_date`, and it needs no new bookkeeping to
disagree with.

Cross-device coverage **rides on the behind-check** rather than adding a
second mechanism: `out/` is tracked, so a `today.md` written on the phone
reaches the laptop as a commit and the laptop cannot write until it pulls. It
is therefore exactly as strong as the behind-check and no stronger — with
`MC_STATE_GIT=off`, no remote, or a ritual that never reached `--save`, it
guards only the device it ran on. The escape hatch is `--again`, deliberately
**not** `--force`: taking over a dead session's lease and rewriting a day that
already happened are different decisions and must not share a flag. `/week`,
`/preview` and `/push` are untouched — they write different files and
legitimately follow `/daily` on the same day.

The lease is **advisory and only as fresh as the last fetch** — it narrows the
window to the seconds between claim and push. Say so rather than implying more:
when `--claim` reports the lease was not pushed, it is not protecting anything.
The behind-check and git's refusal to merge remain the real backstop.

**The guard triggers on being a git repo, not on being split** (corrected
12-08-2026). All four gates — the behind-check in `check()`, the lease commit
in `claim()`, the commit in `save()`, and `mc state`'s own output — used to
test `state_is_split()`, i.e. "is `MC_STATE_DIR` pointing elsewhere". That is
a proxy for the wrong thing, and it fails *open*: merge code and state into
one repo and `mc state --save` releases the lease, commits nothing and returns
`None`, while `--check` skips the behind-check entirely. Silently. The guard
exists because three state files are whole-file rewrites with no merge logic,
which is a property of **those files**, not of where they sit relative to the
code. `MC_STATE_GIT=off` is the explicit opt-out for a plain local checkout.

`log/training-log.md`,
`data/strength_schedule.json` and `data/pushed.json` are rewritten whole with
no merge logic — two machines writing the same day loses one of them
silently, and a lost key in `pushed.json` makes the next push create a
*duplicate* Garmin workout. Git is the sync layer precisely because it
refuses to merge that, where a cloud drive would resolve it quietly. So:
`mc state --claim "..."` before `/daily`, `/week`, `/preview`; `mc state
--save "..."` after. The guard is enforced, not merely documented — if it
refuses, pull (behind) or wait (lease). Never work around it.

## Shin self-check & fixed strength (added 29-07-2026)

Every `/daily` asks a 0-3 shin/tibia scale, meaning restated in full each
time (see `.claude/commands/daily.md`): `0 = nothing` · `1 = tender to
palpation only, not felt during running` · `2 = aware during runs but not
limiting` · `3 = changes how you run`. A **3** (or any gait-changing/hamstring
pain) is a D1-D3 safety stop. A **1-2** is a C2-eligible readiness signal —
weigh it, don't auto-stop.

Two strength sessions/week are **fixed, not optional** — chosen each `/week`
(`mc strength --set-days`) as that week's two shortest non-long-run running
days, done after the run, and persisted so they don't drift under C1
reshuffling. This sits under C4 (strength/mobility needs no approval to add)
— it never touches `plan.lock.json` or §6. Exercises progress on a 3-tier,
3-weeks-per-tier schedule (`src/mc/strength.py`) — tempo/load is the
progression variable for the shin-specific lifts, not rep count.

The `/daily` after each fixed day checks it (`mc strength --pending`) and
asks me to confirm done/missed. Done gets logged; missed
auto-reschedules onto the best remaining day that week (`mc strength
--confirm ...:missed --reschedule-candidates ...`) or, if nothing suitable
is left, stays missed — no cross-week makeup.

## Two sources, one shape (added 12-08-2026)

Garmin and intervals.icu were both already synced and cross-checked, but only
Garmin was *read* — intervals supplied a single CTL/ATL/TSB line. It is now a
**complete substitute**, and `src/mc/sources.py` is the only place that knows
there are two of anything: it emits **Garmin-shaped** records whatever the
origin, so `check`, `plan`, `render`, `weather` and `metrics` keep their
existing field access untouched.

Why it matters: **`mc sync` against Garmin needs an account password plus TLS
impersonation** (`curl_cffi` exists in this project for exactly that) to get
past bot detection. intervals.icu needs a scoped API key that is *designed* to
be pasted into third-party tools, is revocable on its own without touching the
watch, and cannot reach back into Garmin. Only the second belongs anywhere
except this laptop. So: **Garmin is the Mac's fidelity layer; intervals is what
travels.**

Selection is per-item, never "one source wins the day":

- **Activities** — merged. A Garmin record wins wherever the same session
  exists in both (matched on bucket + start time, the tolerance `mc sync`
  already uses); intervals fills anything Garmin lacks. Not "Garmin if
  present": a Garmin cache three days stale would otherwise hide this
  morning's run.
- **Wellness** — **freshest usable** reading, Garmin breaking ties because it
  carries more (an HRV status word). Both caches walk back a week, so a fixed
  preference would answer a question about last night with a reading from four
  days ago whenever the watch missed a night. "Usable" is deliberate: Garmin
  writes a populated `dailySleepDTO` whose `sleepTimeSeconds` is **null** on a
  night it tracked nothing — a record that looks like data and carries none.
- **Every printed reading names its source**, always, not only when it is the
  unusual one — "unlabelled" would otherwise have to mean "garmin", a
  convention a reader has no way to know (§7).

**The two unit conversions are the dangerous part**, because getting one wrong
yields a plausible number rather than a crash, and the decay thresholds are
calibrated on Garmin's units. intervals reports cadence **per leg** (×2) and
step length in **millimetres** (÷10 against Garmin's cm). Both were pinned
against 28 runs present in both caches; the ×2 was already recorded in
`TODO.md` from an earlier probe, the ÷10 was not. `tests/test_sources.py`
asserts the two parsers produce *identical* streams, which is the thing that
notices if either drifts.

**What intervals genuinely cannot supply**, and which is therefore absent
rather than approximated: Body Battery, training status, VO2max, race
predictions, lactate threshold. **No §6 rule reads any of them** — C2 uses
HRV/sleep/RHR/self-report directly. intervals' own `readiness` field is a
different quantity and is deliberately *not* mapped onto Garmin's label.

`mc push` stays Garmin-only and Mac-only: it needs Garmin `workoutId` /
`workoutScheduleId`, which intervals does not carry.

**One deliberate divergence from the spec.** `instructionforclaudecode.md` §1
says to derive habitual training times "from **Garmin** activity start times".
That now reads both sources. The clause names Garmin because it was the only
source when it was written, and what it is *for* is C6 — don't propose a 6am
session if I never run at 6am — which a session recorded only in intervals is
equally good evidence for. Its stated reason for one source (don't
double-count a session present in both) still holds and is still honoured, now
by the de-duplicating merge rather than by ignoring a source. Flagged here
rather than silently reinterpreted.

## Weather & running form (added 04-08-2026)

`mc weather` reports ambient conditions by training window (`early` /
`morning` / `midday` / `evening`), each summarised by its **worst** hour — a
window is a commitment to be outside for all of it. Source is Open-Meteo: no
API key, one call per `mc sync`, a different provider from Garmin so it
competes for no rate budget. The only thing sent is one coordinate pair
rounded to 2dp, taken from the most recent GPS activity (so it follows me to
Italy) unless `MC_WEATHER_LAT/LON` overrides it. The source used is printed
every time.

**An intervals activity carries no coordinates at all** — all 183 fields were
checked; they exist only in its `latlng` stream, as two parallel arrays. So
`mc sync` resolves the newest outdoor run's start fix once, caches the two
floats in `data/raw/intervals/location.json`, and `resolve_location` falls
back to it after the activity scan. Without that, an intervals-only session
has **no location and weather goes silently dark** — precisely the Italy case
this exists for. `MC_WEATHER_LAT/LON` is not a substitute: an override *wins*,
so it would keep reporting home weather after the flight. `MC_TEMP_UNIT=celsius` for the Italy block; °F is canonical
internally so thresholds never shift with the display.

Heat levels are `none · noticeable · hard · extreme` — a **separate
vocabulary from §4's verdicts**, deliberately not overlapping, and **not a §6
trigger on their own**. C2 is a permission I exercise citing these numbers,
the same way it already demands cited HRV/sleep/RHR. Classification takes the
worse of feels-like and dew point; dew point matters more, since it decides
whether sweat can evaporate.

**A long run occupies a window; a short run is placed inside one** (added
11-08-2026). Worst-hour summarising is right for the first and misleading for
the second, and nothing said so. On 12-08 the evening window read 86°F — its
17:00-19:00 plateau — while the 20:15 slot a 4-miler would actually use was
80°F; sunset at ~20:00 is a cliff the window figure hides. A start time was
called off the 86 and had to be corrected once the hourly numbers were dug out
of `data/raw/weather/latest.json` by hand.

`mc weather` and the digest now print a `↳` line naming the coolest hour inside
any window whose own hours differ enough to matter (`weather.sub_window_finding`).
It fires on **degrees, never on heat levels** — a first draft also fired
whenever the slot dropped a level, and reported the early window for a 2°F
difference straddling the 65°F dew-point boundary. A label that flips on 2°F is
the same bracket artifact the feature exists to see through. Either feels-like
or dew point may qualify a slot, at ≥5°F; ranking within a window is on the
numbers for the same reason. Most windows report nothing, which is the point.

**Do not trade sleep for a few degrees.** The heat number is one input and not
the dominant one: sleep <6h is itself a C2 readiness signal, so an alarm set to
dodge 6°F on an easy run spends more than it buys. C6 already says to weigh
observed patterns — the evening cluster in the digest's time-of-day table is a
real preference, not a default to be corrected.

The digest also carries a **Running form** section: cadence, elevation gain,
grade-adjusted pace against raw pace, and the dew point each run actually
happened in. All of it comes from calls `mc sync` already made — **zero extra
API calls**. Cadence is the cheapest objective proxy for D2 (gait change),
which is otherwise pure self-report — but it tracks pace and terrain too, so
a drop is reported next to that run's pace and is never a finding (§6 D6).
Garmin's own `minTemperature`/`maxTemperature` is deliberately **not** used:
it's a wrist sensor against a warm arm, it measures the watch rather than the
air, and Open-Meteo answers that question properly.

**Within-run decay.** For runs ≥5 mi, `mc digest` splits the cached per-sample
streams into thirds *by distance* and reports first vs last. This is the
question a per-activity average cannot answer: 166 spm over 10 miles is equally
consistent with holding 166 and with running 172 then 160.

The streams come from `data/raw/garmin/activities/details/` when Garmin fetched
them and `data/raw/intervals/streams/` otherwise (see "Two sources" above).
**The Garmin path costs zero extra API calls** — it rides on a payload `mc
sync` already had. **The intervals path does not**: streams are a separate call
per activity, made once for runs ≥5 mi within 30 days and then cached, which is
why that cache is committed and pruned rather than regenerated.

Three metrics, all from the same payload as each other:

- **Cadence** — turnover. Trips the note at −4 spm.
- **Stride length** (`directStrideLength`) — ground covered per step. Trips at
  −5%. Added 05-08-2026 after the 2025 NYC marathon lap file showed cadence
  *rising* over the final three miles (160 → 166-169 spm) while stride fell
  0.966m → 0.845m across a 17-minute positive split. A cadence-only check
  reports **nothing** about that run, which is why the two trip independently
  and are never required to agree.
- **Grade-adjusted pace**, with raw-vs-GAP terrain cost per third —
  **reported, never a trigger**. A warmup and a cooldown sit in the first and
  last thirds, so a structured run shows fade it did not have (a real cached
  workout goes 9:01 → 7:28 → 10:06). Every other threshold here errs toward
  saying nothing; this is the one that would err the other way.

  Garmin gives this per sample (`directGradeAdjustedSpeed`). intervals does
  **not** — `types=gap` is a 422 — but each lap carries `gap` alongside
  `start_index`/`end_index` into the stream arrays, so a sample takes its
  lap's figure. Per-mile laps against per-third medians land in the same
  place. The two models (Garmin's, and Strava's via `gap_model: STRAVA_RUN`)
  agree to ~2%, and the digest names which one produced a given row.

The note names *which* fell, because they mean different things: cadence
easing while stride holds is what backing off or a cooldown looks like; stride
shortening while cadence holds is legs. Both are still descriptions of a run,
never a verdict about a body (§6 D6).

**When something looks off, check the conditions before concluding anything.**
The form table carries each run's dew point, and pace/decay notes quote the
conditions that run happened in. I do run slower when it's hot and humid — so
when a run is a pace outlier or fades late, the right move is to **ask**
("was it hot out there? was it meant to be easy? did anything hurt?"), not to
assume fatigue and not to assume heat. This is a question that replaces one of
the existing four, never a fifth. And heat is the easiest thing in this system
to hide behind: E3 says never soften the framing, so conditions are context
for a question, never an excuse and never a substitute for the `HEAT` reason
code when a session actually deviates.

## Fuelling & quad work (added 05-08-2026)

Both came out of reading the 2025 NYC marathon lap file, and both sit under
**C4** — neither touches `plan.lock.json` or §6, and neither gates a session.

`mc fuel "<session>"` gives the in-run carbohydrate plan for anything over 75
min (~8 mi), and stays **silent** below that. `/daily` prints it verbatim as a
**Fuelling** section on those days; `/preview` prints the prep half the night
before; `/week` states next week's counts as a shopping note. It adds **no
question** to `/daily`'s four.

The 2025 race ran on ~**27 g/hr** — 5-6 gels over 4h49 — against a 60-90 g/hr
need, and the legs emptied at mile 19 with HR and breathing unremarkable. That
signature is genuinely ambiguous and is **not** treated as settled evidence of
a glycogen wall: a quiet HR points at least as strongly at localised eccentric
quad damage from the course's descents, which is why `context/downhill.md` and
the quad eccentric lift exist as a *separate* answer to mile 19. Fuelling and
quads are two risk factors, addressed independently.

**The cadence is fixed; g/hr is what falls out of it** (inverted 17-08-2026,
`context/fueling.md`). `mc fuel` used to pick a g/hr off a ramp and divide to
get an interval, which produced correct arithmetic nobody would run — five
gels inside a 13-miler, an interval that moved every week, and mental
subtraction at mile 8. Now: **one gel every 20 min, first at 40 min** on a
normal breakfast, **20 min without one** (`mc fuel --fasted`). Weeks 6 and 11
and race day take the 20-min start regardless — those are the three sessions
rehearsing race day's schedule, and A4 means a cadence untested by week 11
cannot appear on 01-11. **One packet of drink mix on runs ≥14 mi**, and
**none in Italy**, where a locally-bought 6-pack of gels covers both long runs
rather than sourcing mix abroad for two opportunistic sessions.

`FUEL_RAMP_G_PER_HR` survives as the **reference** that cadence is measured
against, never as a target it is solved for. Where the delivered rate lands
materially under the ramp (weeks 12-13, where the ramp says 80 and short taper
runs deliver ~38-51), `mc fuel` **prints the gap** — E3 applies to fuelling as
much as to mileage. Do not close it by adding a gel: the cadence is the
decision, and it was made knowing it trades some of the ramp's ceiling for a
schedule that gets followed. Above 60 g/hr the product must be mixed glucose +
fructose; one sugar saturates one transporter regardless of dose.

The fixed strength session gained a **quad eccentric** lift on the same 3-tier
schedule. Until then it trained shins and hamstring — the two tissues that
hurt in *training* — and nothing of the one that failed in the *race*. Quads
burned from mile 19 while the hamstring finished fine, after a season of
avoiding hills to protect it. Eccentric-biased because downhill running is an
eccentric load, and knee-dominant/upright so it stays hamstring-safe by the
same standard as `HAMSTRING_SAFE_ITEMS`.

**Downhill preparation lives in `context/downhill.md`** — a week-by-week route
plan, read by `/daily` and `/week` with the rest of `context/`. It changes
**routes, never mileage** (C1/C3); if a course-profile run comes out longer
than the planned distance, the planned distance wins. The finding it rests on:
the athlete's long runs already carry ~50-75 ft/mile against the course's 57,
so total elevation is *not* the gap — NYC delivers its descent in a few
unbroken chunks (210 ft inside mile 2) where the park delivers it in twenty
short ones. Progress **continuous descents of ≥100 ft**, not total gain. Week
11's 20 is the only full course-profile rehearsal available, because A4
freezes the taper.

**Gels carry the session; drink tops it up. Never the reverse.** This is
specificity, not preference: on race day 500 ml can't fuel four hours, so
intake will be gels plus course fluid, and a bolus every 20 min is what the
stomach must tolerate. Training mostly on sipped carbohydrate would adapt the
gut to a pattern race day won't use. Confirmed 05-08-2026 — do not "simplify"
a long run onto liquid because the arithmetic allows it.

**Carry is 2 × 250 ml bottles on a belt** (confirmed 05-08-2026, with an
explicit preference for not carrying more): one bottle carb mix, one water +
electrolyte tab, re-dosed from a sachet at each fountain refill. `mc fuel`
reports what the bottle *could* cover, so it is visible that the belt never
carries the session — a 20-miler needs 9 gels however the bottles are managed.
Past 6 gels, a refillable gel flask is the same product in less bulk.

**Carbohydrate and hydration are two separate lines, never merged.** An
electrolyte tab (Liquid I.V. ≈ 11 g carb, 500 mg sodium) is most of an hour's
sodium and about half a gel — it counts toward fluid/sodium, not toward the
g/hr target. They also differ in *timing*: a gel is a bolus and waits for the
first-gel offset, drink-mix carbohydrate is sipped continuously from the
start. Fluid
(400-800 ml/hr) and sodium (300-600 mg/hr) are printed as **ranges**, because
sweat rate isn't measured here.

**Weights during Italy: keep the weighted default, downgrade on request.**
`mc strength ... --bodyweight` swaps each lift for the hardest equipment-free
variant — a step down one tier, not to tier 1. Deliberately **opt-in and not
inferred from `no_gym`**: weights are often findable while travelling
(confirmed 05-08-2026), and deriving it from the block would downgrade every
Italy day including the ones with a gym. Tell me the gym is a bust and I'll
pass the flag.

Neither is medical advice (D6).

## Distances are half miles; §6 is judged to half a mile (added 14-08-2026)

A prescription of `5.11 mi` is a lie about how running works. A route is
eyeballed on the way out to avoid a long walk home and comes back a bit over
or under; a treadmill is precise but is still set by hand. Those hundredths
were never a measurement — they were the arithmetic of forcing a weekly total
inside its `[floor, ceiling]` band one decimal place at a time. `w/c 10-08`
carried days of **5.11** and **3.87** mi and had been **revised 8 times**,
which is what that looks like from the outside.

**Prescriptions snap to `layout.QUANTUM_MI` = 0.5 mi**, in `_write` (so
nothing reaches disk with hundredths whichever code path built it) *and* in
`_to_layout` (because this file is tracked state that syncs between devices,
and a phone on an older client can put them back). Two exemptions, both
because the number is a **measurement rather than a prescription**: the long
run, frozen in `plan.lock.json` under A1/A3 and week 14's being the marathon
itself (26.2); and cross days, whose number is minutes.

That exemption is why **`race` is now a session type**. The 08-08 Percy Sutton
5K was stored as `pace` at 3.1 mi, and quantization silently rewrote it to
3.0 — a 5K is 3.1 because that is what a 5K is. `race` holds a fixed event
distance; `pace` stays quantized, since a 5.5 mi pace run is an ordinary
prescription.

**The week-sum rules — A2, A4, A5, A6, A9 — now carry a ±0.5 mi tolerance**
(`rules._WEEK_TOLERANCE_MI`). They previously compared with a float epsilon,
so a week 0.05 mi under the floor was a *violation*. This is less a relaxation
than a consistency fix: the codebase had already decided the same question
twice in the other direction, at `_LONG_RUN_TOLERANCE_MI` (0.2 mi on A1/A3,
the strictest rules here) and `drift.DEVIATION_TOLERANCE_MI` (a full mile per
day, "rounding and GPS noise"). A2/A6/A9 were the ones nobody had got to.

It **cannot hide a missed session**: the shortest run anywhere in the plan is
3 mi, six times the tolerance, so a skipped day still drags the week under the
floor and A2 still fires. A9 applies it in **miles, not ratio space** —
the tolerance is a claim about how precisely a distance can be run, so it is
compared against `ratio_max × total` rather than fudging the percentage.

**It applies in the taper too**, deliberately. `compliance_floor` is 1.0 there,
so A2's floor *is* the plan value and A4 caps at that same value — the strict
band for week 12 is **28.0–28.0 mi**, a single point no outdoor week can hit.
The taper was unsatisfiable by construction and the tolerance is the only
thing that makes it runnable. A4 is the rule protecting the taper's shape, and
it is a ceiling, not a floor. Both decisions confirmed with me 14-08-2026.

Not extended to **A1/A3**, which judge one locked event rather than a sum of
five and keep their own tighter 0.2. By the "half a mile in one run cannot
matter" principle they would arguably go to 0.5 as well — but A3 protects the
18 and the 20, and that was not the change asked for. Raise it explicitly or
not at all.

**The root cause was laying weeks out flush against an edge**, so `mc check`
and `mc layout` now print the band and the slack either side, and `mc layout`
warns when a week sits within one quantum of an edge. `rules.week_band` names
the **binding** ceiling, which is not always A6's 105%: a frozen taper week
(A4) and a stepback week (A5) are both capped at the plan value itself. That
is not a detail — week 3 is a stepback with a plan of 22 mi, so its real band
is 20.9–22.0, and its layout was set to exactly 22.0, flush against a ceiling
nothing was printing.

## Max HR is snapshotted daily, because Garmin keeps no history (added 20-08-2026)

Garmin Connect shows the *current* Max HR and nothing else — no history, no
change log, nowhere in the app. So the only way this system will ever answer
"when did Max HR change" is to have been writing it down. `mc sync` now
snapshots the HR configuration into
`data/raw/garmin/wellness/hr_settings/YYYY-MM-DD.json` **and** `latest.json`.
The dated file is the point, since `latest.json` alone is overwritten tomorrow
and no series ever accumulates. (ISO filenames, matching every other cache
under `wellness/` — the `DD-MM` convention is for prose, not these.)

It sits under `wellness/` — the tracked-in-git half of `data/raw/garmin/` —
for a stronger version of that directory's own
reason: a 7-day wellness window cannot be re-fetched, and a settings change
cannot be re-fetched *at all*.

**Max HR is not where the endpoint names suggest**, which is worth recording
because two plausible guesses are both wrong (verified against live responses
20-08-2026, not from docs):

- `get_userprofile_settings()` — despite the name, locale and display
  preferences only. Its `heartRateFormat` is the string `"bpm"`. No HR value of
  any kind. Not called.
- `get_user_profile()` (`userData`) — carries `vo2MaxRunning`,
  `lactateThresholdHeartRate`, `thresholdHeartRateAutoDetected`, but **no
  maximum**.
- `get_heart_rate_zones()` — **this one**. `maxHeartRateUsed` on the zone
  configuration, i.e. the max the zones were computed from, which is also the
  right number to report: it is the value actually in force. Currently **183**,
  matching the app.

The last two share **one envelope** (`source:
"get_user_profile+get_heart_rate_zones"`), a deliberate break from the
one-call-one-file convention: "my HR configuration on day N" is a single fact,
and splitting it would let a settings change be read out of two files that fall
out of step when one call fails and the other does not. `digest.extract_max_hr`
prefers the `DEFAULT` sport profile, then any profile carrying a usable number,
so an added sport profile cannot blank the line. `lactateThresholdHeartRateUsed`
(162) sits in the same object and is plausible as a max — `test_digest.py` pins
that it is never mistaken for one.

`get_device_settings(device_id)` is captured alongside, dated the same way, for
the autodetect toggles. The device id is read off **cached** `training_status`
(`resolve_device_id`) rather than fetched — `get_devices()` would be a whole
call to learn something already on disk — and a first-ever sync with nothing
cached skips it without spending that call.

**What the toggles actually say**, which contradicts what I believed:
`lactateThresholdAutoDetectEnabled` is **True** on the device and
`thresholdHeartRateAutoDetected` is **True** on the profile. Threshold
autodetect is **on**, not off — so "the toggle was off" does not explain why the
08-08 5K produced no new lactate-threshold reading. And **no Max HR autodetect
flag exists in either payload**; every `auto*detect` field in both was
enumerated. Whatever the app exposes under that name is not in these responses,
so it is not being captured and must not be claimed.

All of it is supplementary: **no §6 rule reads Max HR**, so a failure here is
caught per-call and recorded in `supplementary_failures` rather than discarding
the activities and wellness already pulled. Three extra calls per sync
(`fixed_calls` 3 → 6).

## Long-run days are routed in advance (added 11-08-2026)

**`context/long-run-routing.md`** holds the agreed long-run date for every week
from 15-08 to the 20-miler on 11-10, the reasoning behind the non-obvious
placements, and the Italy arithmetic. Read by `/daily` and `/week` with the rest
of `context/`.

It exists because the natural places to write this down do not survive to the
day they matter: `mc tidy` deletes `out/today.md` once its day passes, and
`log/sessions/` drops out of `/daily`'s 14-day read window long before
September. A routing decision taken in August has to still be readable in
October, so it lives in `context/` alongside `downhill.md`.

The three findings most easily undone by accident: week 6's 18 **leaves Sun
06-09** for Thu 03-09 (left on Sunday it is 3 days from the 15 on Wed 09-09, a
hard B3 reject); **no 16-miler is reachable anywhere in Italy** (A6 caps week 8
at 19.95mi, A9 caps the long run at 64% of that = 12.8mi); and in Italy the long
run may **shrink to anything but must never be skipped** — A1 and A10 are both
switched off there, but B3 still needs a longest-run-of-the-week every 5-10 days,
and dropping either Italy long run opens a 15-16 day gap.

Long-run *distances* stay frozen in `plan.lock.json`; this file fixes only the
**day**, which is B1/C1 and needs no approval.

## `today.md` prints what applies today (added 17-08-2026)

Spec §8 fixed one shape for `out/today.md` and every section in it printed
every day. Two of them had nothing to say on most days, and a section that is
always there is one the eye learns to skip — which costs more than the section
was worth, because it takes its neighbours down with it.

**The substitution table is now off by default.** Whether to swap a run for the
elliptical is a same-day judgement I make, and I will ask; a table offered
unprompted every morning is an answer to a question nobody asked, sitting
directly under the prescription it undercuts. It still prints in full — same
✅/⚠️/❌ verdicts, same *Lost if substituted* line, same weekly count — in three
cases: **I ask** (in any wording, including "I can't run today"), a **D-rule
stop** (D1 says to offer the elliptical if it's pain-free; refusing the run and
then offering nothing would be worse than either), and a **C2 swap actually
being proposed** on cited heat/shin/readiness numbers. Never as a hedge
alongside a run I'm being told to do. Long runs still never get one, unchanged.

**Strength & mobility prints only on the week's two fixed days.** The optional
2-3 items on every other day were noise standing next to the thing that
matters — the two fixed sessions are fixed. Off-day mobility is still C4 and
still free for the asking; an ad-hoc session just doesn't count toward the
week's two, and `mc strength --confirm` refuses a day that isn't in the
schedule, which is correct.

**Fuelling leads with the counts, and `/preview` gets them first.** `mc fuel`
was one block: the in-run schedule, with the carry arithmetic inside it. But
"how many gels" and "when do I take them" are read at different moments and only
one of them can still be acted on — being two gels short is discovered either in
the drawer the night before or at mile 14. So `fuel.prep_lines` is split from
`plan_lines`: the count of gels, whether a packet of carb mix rides along, how
many electrolyte tabs, what to do before leaving, the meal timing that decides
the alarm, and the two things that are **purchases** rather than actions —
mixed glucose + fructose above 60 g/hr, a flask past 6 gels. `mc fuel --prep`
prints that alone, which is what `/preview` runs; `/daily` prints prep then
schedule. Deliberately **counts, never inventory**: this system doesn't know
what's in the cupboard, so it says what the run needs and leaves the comparison
to me.

**The two carry lines are counted differently, and must stay that way.**
Electrolyte tabs are `refills + 1` — one per fill, because the water bottle is
re-dosed at every fountain stop. Carb mix is **one packet, once, at the start**,
never per-fill: an earlier draft made both per-fill, which is internally
coherent but would have had a 20-miler packing three sachets and quietly
reinstated the drink-led fuelling the fixed cadence moved away from.

**`context/fueling.md` holds the protocol** — this was argued the other way
first, on the reasoning that fuelling is derivable and a prose copy would be a
second set of numbers to disagree with the code. That was right when the g/hr
ramp *was* the plan and everything else fell out of arithmetic. It stopped
being right when the cadence became a **decision**: 20 minutes, the 40/20
breakfast offsets, the three sessions that start early anyway, ≥14 mi for a
packet, gels-only in Italy, and the deliberate choice to accept a shortfall
against the ramp rather than close it — none of that is derivable from
anything, and it is exactly what `context/` is for. The original concern was
real, so it is answered rather than dismissed:
`test_the_whole_plan_matches_the_agreed_table` pins all 14 weeks' gel and
packet counts against that file, and the two cannot drift apart without a test
failing.

## The training day is a New York day (added 25-08-2026)

`mc render --all` deleted a live `out/today.md` on the evening of 24-08. Nothing
was wrong with `mc tidy`: the file declared `24-08`, `date.today()` said `25-08`,
and a file whose day has passed is deleted. **The clock was wrong.** This project
now also runs from a cloud container whose timezone is UTC, and from 20:00
Eastern onward UTC has already ticked into tomorrow — so for the four hours
`/preview` lives in, every `date.today()` in the codebase named the wrong day.

One deletion was the visible half. The silent half: `mc log` filing the evening's
session under tomorrow, `mc propose` writing the prescription onto tomorrow's
row, the training-log backfill marking *today* "Nothing logged" because it
believed the day was over, and the one-`/daily`-per-day guard comparing
`today.md`'s header against a day that hadn't started.

**`src/mc/clock.py` is now the only thing that knows what day it is.** Every
`date.today()` became `clock.today()` — the day in `MC_TZ`, defaulting to
`America/New_York`, which is home and where the race is. `--as-of` / `--date`
overrides are untouched. An explicit default beats reading the machine: the
machine that is wrong about this is precisely the one with no opinion of its own
(a container, on UTC), so falling back to it would fail open in the only place
the bug exists. An unloadable zone falls back to the system clock and **says so**
rather than crashing the 6am ritual.

**`MC_TZ=Europe/Rome` for the Italy block**, and back on 30-09. Rome runs six
hours ahead of New York, so anything before 06:00 there — a dawn long run to beat
the heat, which is most of what that block is for — falls on the *previous* New
York day if the zone is left at home. That is the same bug mirrored, which is why
the zone is configured rather than pinned. `/italy` and `/travel` carry it as a
checklist item in both directions, and **every printed day names its zone**, so a
setting left behind after a flight is visible rather than silent (§7, the same
rule that makes every reading name its source).

**`TZ` is set too, and is the belt rather than the braces.** The SessionStart
hook writes `TZ`/`MC_TZ` into cloud sessions alongside `MC_DEVICE`, so bash
`date`, git commit timestamps and the lease's own clock agree with `mc`. But an
env var is only as reliable as whatever applies it — a trigger-fired session, a
plain shell in the container, a runner that ignores the hook — and when it
doesn't apply, nothing says so. `MC_TZ` is read at the point of use and printed.

**`mc today` is the ritual's source of truth for the date, and this matters most
for the agent.** The date Claude is handed at the top of a cloud session is the
container's too, so after 20:00 Eastern *it* thinks it is tomorrow as well —
correct code and a confident model would still write `# 25-08` on the 24th. Every
slash command now starts by running `mc today` and takes every `DD-MM` it writes
from that. `mc state --claim` warns (never refuses — the purpose string is free
text) when the day named in it disagrees.

**`mc tidy` no longer deletes what git has no copy of.** Its whole justification
is "the history is the durable record", which was assumed and never checked — and
`/daily` tidies *before* `mc state --save`, so for the length of the ritual the
claim is false. An expired `.md` that is untracked or modified-since-commit is
now reported and kept ("commit it and it goes next run") — and that is **one**
rule covering both reasons a `.md` gets deleted, the expired day and the
projection superseded by `today.md` (19-08): they are different arguments for
deleting, and neither is an argument for deleting the only copy. `.html` twins
get no such protection on purpose: they are regenerable, and protecting them would leave
every uncommitted render in `out/` forever — the accumulation `tidy` exists to
stop. No git, or `MC_STATE_GIT=off`, behaves exactly as before; the guarantee was
always conditional on git.

**`uv run pytest` is now structurally unable to write real state.** The bug
itself was found and fixed on 17-08: `test_digest_runs` invoked the real
`digest` command, which rewrote `data/digest/latest.md` and backfilled
`log/training-log.md` — once flipping a `*(pending)*` row to `Nothing logged`
before that day's activity had synced. That fix pointed the test at `tmp_path`
and made `traininglog` resolve `cfg.TRAINING_LOG_PATH` at call time instead of
binding it as an import-time default, with a signature test guarding the trap.

Both stay, and a third layer sits under them, because path-by-path isolation
fails open on the next writable path anyone adds and the damage is invisible in
test output — the suite passes either way and the evidence is a dirty working
tree nobody looks at. `tests/conftest.py` points `MC_STATE_DIR` at a throwaway
directory **before anything imports `mc.config`**, which is also the only thing
that captures the constants derived at import time (`layout.STATE_PATH`,
`strength.STATE_PATH`) — a fixture monkeypatching `cfg` cannot reach those.
`tests/test_config.py` asserts the sandbox holds. `MC_STATE_GIT` is deliberately
left alone: setting it off globally would disable the machinery `test_state.py`
exists to check, and the sandbox is not a git repo anyway.

## §4 verdict vocabulary — fixed, never invent new labels

`✅ good substitute` · `⚠️ aerobic only` · `❌ not recommended` ·
`❌ not a substitute`

Always state the percentage **and** what specifically is lost. Long runs
never get a substitution table — no substitute exists, never offered.

## Reason codes — closed set (§6 E1)

`TRAVEL RACE ILLNESS INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS
OVERRIDE`

"I feel tired" is not a reason code. `READINESS` requires citing actual data
(HRV/sleep/RHR numbers), not a vibe. An `OVERRIDE` requires me to type the
literal string `OVERRIDE: <reason>` — never assume one from any other
phrasing, not even a close paraphrase. Overrides append to
`context/overrides.md` via `mc override "<reason>" --code CODE` — only ever
after I have typed the literal string, never on a paraphrase. More than 2 in
a 4-week block means the plan isn't matching real life — propose a
**structural** revision for approval, not another override.

`mc drift` reports the trailing 4 weeks in plain sentences: miles short,
which days deviated, which codes recur, overrides against the limit of 2. It
exists to surface that trend *before* the tripwire. It reports counts and
dates only — never a diagnosis (§6 D6), never a plan change.

## §6 — THE RULE ENGINE (verbatim)

Implemented in `src/mc/rules.py`. `check_week(proposed, plan)` returns
`(allowed: bool, violations: list[Violation])` for a proposed week against
`plan.lock.json`. Call it before showing me any plan.

### A — Immutable (hard reject)

- **A1** Weekly long-run distance equals the plan value for that week's block.
  It may move day-of-week. It may not shrink — except inside `travel_italy`,
  where `long_run_opportunistic` applies.
- **A2** Weekly total ≥ the `compliance_floor` for that week's block.
- **A3** The **20-miler on Sun 11-10 happens**. Never shortened, never split,
  never moved outside its week. Same for the 18 on Sun 06-09.
- **A4** Taper (weeks 12–14) is frozen. No additions, no substitutions, and
  explicitly **no making up missed volume**.
- **A5** Stepback weeks stay at their planned *lower* volume. Never topped up
  because I feel good or missed something earlier.
- **A6** **No increases.** Weekly total may not exceed 105% of plan. If I feel
  great, the correct answer is "stick to the plan" — say exactly that.
- **A7** Race date fixed.
- **A8** Non-running aerobic load ≤ 35% of weekly total aerobic load, outside
  the travel block.
- **A9** Long run ≤ `long_run_ratio_max` (default 0.32, per-week in the
  frozen plan — see `plan/plan.md` for why) of weekly total aerobic load. If
  a proposed cut to running volume breaches this, the cut is rejected —
  reduce the long run or restore the midweek miles instead.
- **A10** Running days: minimum 3/week outside travel and taper. Below that,
  running-specific adaptation degrades regardless of cross-training volume.

### B — Long-run shuffling (the travel machinery)

- **B1** The long run may be placed on any day of its own week. Preferably
  Sundays or Saturdays.
- **B2** ≥48h between the long run and any quality session (pace run, tune-up
  race) on both sides.
- **B3** Consecutive long runs **≥5 and ≤10 calendar days apart**. A shuffle
  that breaks this is rejected outright — solve it another way. (This is the
  classic failure: a Sunday→Monday shuffle that stacks two long runs 24h
  apart.)
- **B4** A long run may cross into an adjacent week at most once per 4-week
  block, and only if B3 holds.
- **B5** If travel makes the long run impossible, apply in **strict priority
  order**, never skipping ahead:
  1. move within the week (B1–B3)
  2. split 60/40, same day, ≤6h apart — max twice in the whole plan, never
     for an 18 or 20
  3. swap with an adjacent week's *shorter* long run (never carry the longer
     one forward into a peak week)
  4. reduce — max 25%, requires a reason code, forbidden for the 18 and the
     20
- **B6** No long run within 24h of a flight over 4h, either direction.
- **B7** After arrival in Italy (11-09) and after return to the US (30-09):
  **first 3 days easy only.** No quality, no long run. Poor sleep is expected
  and pre-declared — this is not an override, it is the plan.
- **B8** Max 5 consecutive running days (reduced from the usual 6, for
  shins), and at most once per 4-week block. Never 6.
- **B9** Preserve the Saturday-pace / Sunday-long pairing where the week
  allows. If you break it, state that you did and why.

### C — Free to adjust (no approval needed)

- **C1** Reorder easy runs within the week.
- **C2** Swap any easy run for its cross-equivalent (§4) when: forecast heat
  is high, I report shin symptoms, or ≥2 readiness signals are bad (HRV
  below baseline, sleep <6h, resting HR +5bpm, self-report ≤4/10). Log it.
  A8 still binds.
- **C3** Adjust easy pace freely for heat, fatigue, terrain.
- **C4** Add/remove strength and mobility.
- **C5** Drop a single easy run for travel — A2 still binds.
- **C6** Choose session time of day based on my observed patterns and the
  forecast.

### D — Safety stops (refuse to produce a running session)

- **D1** Shin pain that is sharp, localised to bone, or worsens during a run
  → no running. Offer elliptical only if pain-free. Say plainly that
  persistent shin pain needs a professional, and do not optimise around it.
- **D2** Any pain that changes my gait → no running plan today.
- **D3** Posterior thigh / sit-bone pain (hamstring tendinopathy signal) →
  no speed, no hills, no long stride. Flag it explicitly, given the history.
- **D4** Three consecutive days of self-report ≤3/10 → propose a recovery
  week, flag possible overreaching.
- **D5** Fever or systemic illness → no running.
- **D6** You are not a doctor or physio.

### E — Anti-drift

- **E1** Every deviation logged with a reason code from this closed set:
  `TRAVEL RACE ILLNESS INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS
  OVERRIDE`. "I feel tired" is not a reason code. `READINESS` requires cited
  data.
- **E2** If rolling 3-week actual < the block's compliance floor,
  `out/today.md` must **open** with a warning stating the shortfall in
  miles.
- **E3** Never soften the framing. If I'm behind, the first line says I'm
  behind.
- **E4** An `OVERRIDE` requires me to type `OVERRIDE: <reason>`. You may
  never assume one. Overrides append to `context/overrides.md`.
- **E5** If overrides exceed 2 in any 4-week block, `out/today.md` must
  state that the plan is not matching my life and propose a **structural**
  revision for my approval — not more overrides.
