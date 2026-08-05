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
Never call Garmin outside an explicit `mc sync` — everything else reads the
local cache under `data/` (gitignored, regenerated on demand).

## Date & unit conventions

- **Units: miles and min/mile. Always. Never km.**
- **Weeks**: `Week N · w/c DD-MM` (week starts Monday). Prefer the date over
  the number.
- **Days**: `DD-MM` (e.g. `28-07`). Never "Tuesday of week 3" alone.

## The daily ritual

`/daily` runs: `mc sync` (which also refreshes the forecast) → `mc digest` →
read the digest + `plan.lock.json` +
`context/` + last 14 days of `log/` → ask **at most 4** questions (feel 1-10,
sleep, shins/hamstring, anything changing in the next 7 days — never more,
never pad), **plus a 5th only when a fixed strength day from earlier this
week still needs a done/missed confirmation** → `mc check` → write
`out/today.md` + `.html` → append to `log/sessions/`. See
`.claude/commands/daily.md` for the exact format.

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
same-day judgement. `mc render` skips a stale `out/tomorrow.md` rather than
turning yesterday's guess into a fresh-looking page.

Optional: `MC_EXPORT_DIR` in `.env` makes `mc render --all` copy `out/*.html`
and `today.md` into that local folder — typically one a cloud client already
syncs to the phone. Plain file copy, no cloud API, write-only, nothing read
back.

## State lives in a private repo (added 02-08-2026)

This repo is **public**. `MC_STATE_DIR` points at
`marathon-2026-state` (private), which holds `log/`, `out/`, `data/` and
`context/overrides.md`. `plan/` and `context/equivalence.md` stay here — the
plan is frozen and versioned, equivalence.md is sourced research. Unset,
everything falls back to this checkout and behaves as before.

Credentials are in **neither** repo. `.env` is local; so is
`data/.garmin_tokens/`, which holds refresh tokens and is credential material
however private the repo is.

**One writer per day.** `log/training-log.md`,
`data/strength_schedule.json` and `data/pushed.json` are rewritten whole with
no merge logic — two machines writing the same day loses one of them
silently, and a lost key in `pushed.json` makes the next push create a
*duplicate* Garmin workout. Git is the sync layer precisely because it
refuses to merge that, where a cloud drive would resolve it quietly. So:
`mc state --check` before `/daily`, `/week`, `/preview`; `mc state --save
"..."` after. The guard is enforced, not merely documented — if it refuses,
pull. Never work around it.

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

## Weather & running form (added 04-08-2026)

`mc weather` reports ambient conditions by training window (`early` /
`morning` / `midday` / `evening`), each summarised by its **worst** hour — a
window is a commitment to be outside for all of it. Source is Open-Meteo: no
API key, one call per `mc sync`, a different provider from Garmin so it
competes for no rate budget. The only thing sent is one coordinate pair
rounded to 2dp, taken from the most recent GPS activity (so it follows me to
Italy) unless `MC_WEATHER_LAT/LON` overrides it. The source used is printed
every time. `MC_TEMP_UNIT=celsius` for the Italy block; °F is canonical
internally so thresholds never shift with the display.

Heat levels are `none · noticeable · hard · extreme` — a **separate
vocabulary from §4's verdicts**, deliberately not overlapping, and **not a §6
trigger on their own**. C2 is a permission I exercise citing these numbers,
the same way it already demands cited HRV/sleep/RHR. Classification takes the
worse of feels-like and dew point; dew point matters more, since it decides
whether sweat can evaporate.

The digest also carries a **Running form** section: cadence, elevation gain,
grade-adjusted pace against raw pace, and the dew point each run actually
happened in. All of it comes from calls `mc sync` already made — **zero extra
API calls**. Cadence is the cheapest objective proxy for D2 (gait change),
which is otherwise pure self-report — but it tracks pace and terrain too, so
a drop is reported next to that run's pace and is never a finding (§6 D6).
Garmin's own `minTemperature`/`maxTemperature` is deliberately **not** used:
it's a wrist sensor against a warm arm, it measures the watch rather than the
air, and Open-Meteo answers that question properly.

**Within-run decay.** For runs ≥5 mi, `mc digest` splits the already-cached
per-sample streams (`data/raw/garmin/activities/details/`) into thirds *by
distance* and reports first vs last. This is the question a per-activity
average cannot answer: 166 spm over 10 miles is equally consistent with
holding 166 and with running 172 then 160.

Three metrics, all from that same payload, still **zero extra API calls**:

- **Cadence** — turnover. Trips the note at −4 spm.
- **Stride length** (`directStrideLength`) — ground covered per step. Trips at
  −5%. Added 05-08-2026 after the 2025 NYC marathon lap file showed cadence
  *rising* over the final three miles (160 → 166-169 spm) while stride fell
  0.966m → 0.845m across a 17-minute positive split. A cadence-only check
  reports **nothing** about that run, which is why the two trip independently
  and are never required to agree.
- **Grade-adjusted pace** (`directGradeAdjustedSpeed`), with raw-vs-GAP
  terrain cost per third — **reported, never a trigger**. A warmup and a
  cooldown sit in the first and last thirds, so a structured run shows fade it
  did not have (a real cached workout goes 9:01 → 7:28 → 10:06). Every other
  threshold here errs toward saying nothing; this is the one that would err
  the other way.

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
- **B7** After arrival in Italy (10-09) and after return to the US (30-09):
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
