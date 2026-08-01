# Project: adaptive marathon training system — NYC Marathon, Sun 01-11-2026

Athlete: me. Today is 28-07-2026. Race is 01-11-2026 → **14 weeks**, week 1
starting Mon 27-07.

You are building a local system that helps me execute Hal Higdon **Intermediate 1**,
compressed to 14 weeks and adapted continuously — with two specific jobs:

1. **Shift load intelligently around travel.** I have a known 3-week trip to Italy
   (10-09 → 30-09) plus unpredictable smaller trips.
2. **Keep me off my shins.** I'm prone to shin splints. I want fewer pure running
   days than the plan prescribes, more elliptical, and short strength/mobility
   work — without silently gutting the aerobic build.

Build incrementally. Stop and show me after each phase. Do not build everything at once.

---

## 0. Constraints on YOU (the agent)

- **Do not trust API details in this spec.** After installing deps, read the
  installed `garminconnect` source and the live intervals.icu docs. Reality wins;
  tell me what differed.
- Never commit secrets. `.env` gitignored from commit #1.
- No network calls to Garmin outside an explicit `mc sync`. Garmin rate-limits and
  Cloudflare-blocks. Everything else reads the local cache.
- Use a venv. Ask before installing anything global.
- **When you're unsure about training science, say so and cite a source or ask.**
  Do not invent physiology. This applies especially to §4 (elliptical equivalence).
- You are not a doctor or physio. Anything that sounds like an injury: say "see a
  professional," stop optimising, do not prescribe rehab protocols.

---

## 1. Athlete profile (use this, don't re-ask)

**Units: miles and min/mile. Always. Never km.**

**Date conventions:**

- Weeks: `Week N · w/c DD-MM` (week starts **Monday**). Prefer the date over the number.
- Days: `DD-MM` (e.g. `28-07`). Never "Tuesday of week 3" alone.

**Known constraints:**

- **Shin splints:** recurrent. Primary reason for reducing run frequency.
- **Left proximal (high) hamstring tendinopathy:** ~1 year, largely resolved via
  targeted strength work through ~end June 2026. Cleared for fast running. **Care
  needed on hills and sprints** — deep hip flexion under load is the aggravator.
  Design implication: no hill repeats, no all-out sprint finishes, avoid sustained
  steep uphill. Strides on the flat are fine.
- **Heat:** poor tolerance, dislikes running in heat. Bias sessions to cool hours;
  aggressively offer the indoor cross-equivalent (§4) on hot days.
- **Cross-training preference:** elliptical, strongly. Also stationary bike.
  Treadmill only for sessions **under 45 minutes**.
- **No gym access during the Italy trip.**

**Known races:**

- **Sat 08-08** — NYRR Percy Sutton Harlem 5K. Racing this hard. Treat as a
  fitness benchmark and use the result to set all subsequent paces (VDOT or
  equivalent). Given the hamstring history, plan it as a hard controlled effort
  with **no flat-out final sprint**. Flag this in the pre-race note.
- Higdon's plan has a half marathon at plan-week 9. Decide during compression
  whether it survives, and tell me.

**Known travel — Italy, 10-09 → 30-09 (3 weeks):**

- Limited training time. Long runs possible but unpredictable in timing and length.
- No gym → no elliptical, no bike. Running and bodyweight only.
- **Sleep is reliably poor for the first ~2-3 days after arrival, and again after
  return to the US.** Recovery is sub-optimal throughout. Do not schedule quality
  or long efforts in those windows.
- My working hypothesis, which you should test and either endorse or challenge:
  **load up before departure, maintain only during the trip, one focused push in
  early October, then taper.** If you disagree, say so with reasons.

**Time-of-day:** derive my habitual training times from Garmin activity start
times (weekday vs weekend, by session type). Use the pattern when scheduling —
don't propose a 6am session if I never run at 6am, and factor heat into which
slot you recommend in summer.

* **Goal marathon time: ** finish strong, close to 4h 4h 15min. wait for the 08-08 5K result for estimation, check latest Garmin estiames if you can or ask me and i'll provide them over time. I prefer HR zones, but also estimate the avg pace you think i should do a workout
* **gym access in NYC** (elliptical/bike/treadmill/weights), access everyday

---

## 2. Environment & layout

Python 3.12+ (`garminconnect` requires it), `uv`, repo at `~/marathon-2026`, git-init.

Deps: `garminconnect`, `curl_cffi`, `ua-generator`, `httpx`, `pydantic`, `typer`,
`rich`, `jinja2`, `python-dotenv`, `pytest`.

```
marathon-2026/
├── CLAUDE.md
├── .env / .env.example
├── src/mc/
│   ├── config.py  garmin.py  intervals.py  sync.py
│   ├── digest.py            # cache -> markdown digest
│   ├── plan.py              # parse plan.md, enforce plan.lock.json
│   ├── rules.py             # THE rule engine (§6) — heavily tested
│   ├── equivalence.py       # cross-training substitution engine (§4)
│   ├── render.py            # markdown -> standalone HTML
│   ├── push.py              # build/upload/schedule Garmin workouts
│   └── cli.py
├── plan/
│   ├── plan-source.md       # verbatim Higdon Int 1 (below)
│   ├── plan.md              # compressed 14-week, human-readable
│   └── plan.lock.json       # IMMUTABLE machine targets
├── context/
│   ├── athlete.md  calendar.md  overrides.md
│   └── equivalence.md       # researched, SOURCED substitution table
├── log/
│   ├── training-log.md
│   └── sessions/YYYY-MM-DD.md
├── data/
│   ├── raw/garmin/  raw/intervals/  digest/  pushed.json
└── out/
    ├── today.md   today.html
    ├── week-NN.md week-NN.html
    └── dashboard.html
```

**Output format: Markdown is canonical; HTML is generated from it.**
`mc render` produces standalone, single-file HTML (inline CSS, no CDN, no build
step) — readable on phone. Every `.md` in `out/` gets an `.html` twin.
`dashboard.html` shows: weeks-to-race, plan vs actual long-run progression,
rolling volume compliance, run-days-per-week trend, and the travel block.

---

## 3. Source plan — Hal Higdon Intermediate 1 (verbatim, do not modify)

Write this to `plan/plan-source.md` exactly:

```
Week  Mon    Tue      Wed      Thu      Fri   Sat        Sun
1     Cross  3 mi     5 mi     3 mi     Rest  5 mi pace  8
2     Cross  3 mi     5 mi     3 mi     Rest  5 mi run   9
3     Cross  3 mi     5 mi     3 mi     Rest  5 mi pace  6
4     Cross  3 mi     6 mi     3 mi     Rest  6 mi pace  11
5     Cross  3 mi     6 mi     3 mi     Rest  6 mi run   12
6     Cross  3 mi     5 mi     3 mi     Rest  6 mi pace  9
7     Cross  4 mi     7 mi     4 mi     Rest  7 mi pace  14
8     Cross  4 mi     7 mi     4 mi     Rest  7 mi run   15
9     Cross  4 mi     5 mi     4 mi     Rest  Rest       Half Marathon
10    Cross  4 mi     8 mi     4 mi     Rest  8 mi pace  17
11    Cross  5 mi     8 mi     5 mi     Rest  8 mi run   18
12    Cross  5 mi     5 mi     5 mi     Rest  8 mi pace  13
13    Cross  5 mi     8 mi     5 mi     Rest  5 mi pace  20
14    Cross  5 mi     5 mi     5 mi     Rest  8 mi run   12
15    Cross  5 mi     8 mi     5 mi     Rest  5 mi pace  20
16    Cross  5 mi     6 mi     5 mi     Rest  4 mi pace  12
17    Cross  4 mi     5 mi     4 mi     Rest  3 mi run   8
18    Cross  3 mi     4 mi     Rest     Rest  2 mi run   Marathon
```

Higdon's own governing principles, which you must respect:

- Long run is the key session. Every 3rd week is a stepback. **Do not cheat on long runs.**
- Long runs 30–90+ s/mi slower than marathon pace. Physiological benefit kicks in
  at 90–120 min regardless of pace. Covering the distance matters, not the speed.
- Saturday pace run sits *before* Sunday long deliberately — to pre-fatigue, so the
  long run isn't run too fast. Preserve this pairing where possible.
- No speedwork in Int 1. Do not add any.
- Friday is a rest day by design. Monday is cross-training.
- 3/1 finish (last quarter faster) allowed on at most one long run in three.

**Two 20-milers total (weeks 13, 15). Not three.**

---

## 4. Cross-training equivalence engine — `equivalence.py` + `context/equivalence.md`

This is a first-class feature, not an afterthought. I need to know, concretely,
**what I lose** when I substitute.

### Research task (do this before coding it)

Search for and cite actual sources on cross-training transfer to running:
elliptical vs running aerobic equivalence, cycling transfer, injury-substitution
protocols (there's a decent literature on maintaining running fitness during
injury layoffs), and load-quantification approaches (TRIMP, rTSS, session-RPE).
Write `context/equivalence.md` with the numbers and where each came from.
**Flag clearly what is evidence-based vs coaching convention vs your own inference.**

### Starting position (challenge it if the research disagrees)

- **Match by TIME at equal effort/HR, never by machine distance.** Elliptical
  distance readouts are meaningless.
- **Elliptical:** ~85–95% aerobic transfer per minute at matched HR. But near-zero
  transfer for impact tolerance, tendon stiffness, and eccentric loading — which is
  exactly the durability the marathon needs. Call this out every time.
- **Stationary bike:** ~70–85% aerobic per minute at matched HR; lower
  musculoskeletal transfer than elliptical.
- **Treadmill:** 100% — it is running. Available only for sessions under 45 min.
- **Long runs: no substitute exists.** Never offer one.
- **Cap:** no more than ~35% of weekly aerobic load from non-running, or the
  specific durability adaptation degrades. Enforced as rule A8.

### `mc equiv` and the `today.md` block

Given a prescribed session, output a substitution table:

| Option             | Duration             | Est. equivalent   | Verdict                        |
| ------------------ | -------------------- | ----------------- | ------------------------------ |
| Elliptical         | 58 min @ HR 135–145 | ~88% of 8 mi easy | ✅ good substitute             |
| Bike               | 70 min @ HR 130–140 | ~72%              | ⚠️ aerobic only              |
| Ellip 35 + bike 30 | 65 min               | ~82%              | ✅ fine                        |
| Treadmill          | 8 mi ≈ 68 min       | 100%              | ❌ exceeds 45 min limit        |
| —                 | —                   | —                | ❌ not a substitute (long run) |

Verdict vocabulary, fixed: `✅ good substitute` · `⚠️ aerobic only` ·
`❌ not recommended` · `❌ not a substitute`.

Always state the **percentage AND what specifically is lost**, e.g. "88% aerobic,
0% impact adaptation — fine this week, but you've already used 2 substitutions."

This block appears in **every** `out/today.md`, not only on request. It is my main
tool for hot days, rain, and shin flare-ups.

### Strength & mobility

Where the plan has cross or rest, and on any day you downgrade for shin or
hamstring reasons, propose a **short (10–20 min) session**: calf/tibialis loading
for shin resilience, hip and posterior-chain work compatible with resolved
proximal hamstring tendinopathy, plus mobility. Cite the source for each protocol.
**Avoid loaded deep hip flexion** (deep RDLs, good mornings at end range,
sprint-specific drills) — that is the known hamstring aggravator.
No gym during Italy → bodyweight-only variants must exist for every prescription.

---

## 5. Compression 18 → 14 (do this BEFORE writing the rule engine)

### Step 1 — research

Before proposing anything, search for known critiques and consensus modifications
of Higdon Intermediate 1. Specifically look at: the long-run-to-weekly-volume
ratio (week 11 is 18/44 = 41%, well above the ~30% commonly flagged), the absence
of any midweek medium-long, and whether adding a small amount of aerobic quality
is standard practice. **The base must remain Intermediate 1** — I want light,
justified corrections, not a different plan. Present what you find and what you'd
change, with sources, and let me approve before you apply anything.

### Step 2 — get my current fitness

Run `mc sync` first, then compute from real data (do not ask me to estimate):
last 4 weeks' running mileage, longest run in the last 8 weeks, current easy pace
at a given HR, run days per week, and typical session times of day. Present it.

### Step 3 — compress with these anchors

- 14 weeks, Mon 27-07 → race Sun 01-11.
- Preserve the final 3 weeks (plan weeks 16/17/18) **verbatim**.
- Drop 4 weeks from the **early base only** (plan weeks 1–6 region).
- Long run must never jump more than 2–3 mi week-over-week. If it does, rebalance
  and tell me.
- Keep every-3rd-week stepbacks intact.
- **If compressed week 1 is more than ~2 mi (long run) or ~15% (volume) above my
  actual current fitness, stop and tell me the compression is too aggressive.**

### Step 4 — build the Italy block INTO the lock file

The trip is known in advance. It must be a **planned block with its own reduced
targets**, not something handled later by repeated overrides. Overriding the same
rule 15 times is exactly the failure mode this system exists to prevent.

Proposed shape — validate, then challenge or endorse:

- **Weeks 1–6 (27-07 → 06-09):** build. Peak long run **18 mi on Sun 06-09**.
  Not 20 — the jump is too fast from current base and 20 at 8 weeks out is wasteful.
- **Week 7 (w/c 07-09):** taper into travel. Departure 10-09. Nothing hard within
  24h of a long-haul flight.
- **Weeks 8–9 (14-09 → 27-09), Italy:** maintenance only. Target ~60–70% of
  planned volume. Long run 10–14 mi *if the opportunity appears* — opportunistic,
  never scheduled to a fixed day. No quality. No gym → bodyweight strength only.
  First 3 days after arrival: easy only, poor sleep expected.
- **Week 10 (w/c 28-09):** return 30-09. First 3 days back = easy only, jet lag
  and poor sleep expected. Rebuild.
- **Week 11 (w/c 05-10):** the push. **20 mi Sun 11-10** — exactly 3 weeks out,
  matching where Higdon puts his last 20.
- **Weeks 12–14:** taper verbatim (≈12, ≈8, race).

Net: one 20-miler and one 18, instead of two 20s. If you can find a defensible way
to protect a second 20 without stacking risk, propose it. If you can't, say so
plainly rather than inventing one.

### Step 5 — shin-splint adaptation, applied to the compressed plan

Convert the plan from "5 running days" to a **run-days budget** — I want 4 running
days most weeks, 5 in peak weeks, with elliptical covering the difference.

**Do not** simply delete a run day and keep everything else. That pushes the
long-run-to-weekly ratio even higher, which is the wrong direction for shins.
The correct shape: trim the **midweek long run** (Wed) and the easy days, keep the
long run, and add elliptical volume **on top of** the reduced running so total
aerobic load holds. Show me the resulting ratio per week; it must satisfy A9.

### Step 6 — freeze

Show me the full compressed plan as markdown + HTML. **Only after I approve**,
write `plan/plan.lock.json`:

```json
{
  "race_date": "2026-11-01",
  "plan": "Hal Higdon Intermediate 1, compressed 18->14, shin-adapted",
  "units": "miles",
  "locked_at": "<iso>",
  "weeks": [
    {
      "week": 1,
      "wc": "2026-07-27",
      "source_week": 1,
      "long_run_mi": 0,
      "run_miles": 0,
      "run_days": 0,
      "cross_minutes": 0,
      "quality_sessions": 0,
      "long_run_ratio_max": 0.32,
      "is_stepback": false,
      "is_taper": false,
      "is_twenty": false,
      "block": "build",
      "notes": ""
    }
  ],
  "blocks": {
    "build":       {"weeks": [1,6],   "compliance_floor": 0.90},
    "pre_travel":  {"weeks": [7,7],   "compliance_floor": 0.85},
    "travel_italy":{"weeks": [8,9],   "compliance_floor": 0.55,
                    "long_run_opportunistic": true, "no_quality": true,
                    "no_gym": true},
    "return":      {"weeks": [10,10], "compliance_floor": 0.70},
    "push":        {"weeks": [11,11], "compliance_floor": 0.95},
    "taper":       {"weeks": [12,14], "compliance_floor": 1.00, "frozen": true}
  }
}
```

Written once. Any command that would modify it must refuse:
`plan.lock.json is immutable — use OVERRIDE`.

---

## 6. THE RULE ENGINE — `rules.py`

Returns `(allowed: bool, violations: list[Violation])` for any proposed week
against `plan.lock.json`. You must call this before showing me any plan.
Unit-test every rule, including travel edge cases.

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
- **A8** Non-running aerobic load ≤ 35% of weekly total aerobic load, outside the
  travel block.
- **A9** Long run ≤ `long_run_ratio_max` (default 0.32) of weekly total aerobic
  load. If a proposed cut to running volume breaches this, the cut is rejected —
  reduce the long run or restore the midweek miles instead.
- **A10** Running days: minimum 3/week outside travel and taper. Below that,
  running-specific adaptation degrades regardless of cross-training volume.

### B — Long-run shuffling (the travel machinery)

- **B1** The long run may be placed on any day of its own week. preferably sundays or saturdays
- **B2** ≥48h between the long run and any quality session (pace run, tune-up
  race) on both sides.
- **B3** Consecutive long runs **≥5 and ≤10 calendar days apart**. A shuffle that
  breaks this is rejected outright — solve it another way. (This is the classic
  failure: a Sunday→Monday shuffle that stacks two long runs 24h apart.)
- **B4** A long run may cross into an adjacent week at most once per 4-week block,
  and only if B3 holds.
- **B5** If travel makes the long run impossible, apply in **strict priority
  order**, never skipping ahead:
  1. move within the week (B1–B3)
  2. split 60/40, same day, ≤6h apart — max twice in the whole plan, never for
     an 18 or 20
  3. swap with an adjacent week's *shorter* long run (never carry the longer one
     forward into a peak week)
  4. reduce — max 25%, requires a reason code, forbidden for the 18 and the 20
- **B6** No long run within 24h of a flight over 4h, either direction.
- **B7** After arrival in Italy (10-09) and after return to the US (30-09):
  **first 3 days easy only.** No quality, no long run. Poor sleep is expected and
  pre-declared — this is not an override, it is the plan.
- **B8** Max 5 consecutive running days (reduced from the usual 6, for shins),
  and at most once per 4-week block. Never 6.
- **B9** Preserve the Saturday-pace / Sunday-long pairing where the week allows.
  If you break it, state that you did and why.

### C — Free to adjust (no approval needed)

- **C1** Reorder easy runs within the week.
- **C2** Swap any easy run for its cross-equivalent (§4) when: forecast heat is
  high, I report shin symptoms, or ≥2 readiness signals are bad (HRV below
  baseline, sleep <6h, resting HR +5bpm, self-report ≤4/10). Log it. A8 still binds.
- **C3** Adjust easy pace freely for heat, fatigue, terrain.
- **C4** Add/remove strength and mobility.
- **C5** Drop a single easy run for travel — A2 still binds.
- **C6** Choose session time of day based on my observed patterns and the forecast.

### D — Safety stops (refuse to produce a running session)

- **D1** Shin pain that is sharp, localised to bone, or worsens during a run →
  no running. Offer elliptical only if pain-free. Say plainly that persistent
  shin pain needs a professional, and do not optimise around it.
- **D2** Any pain that changes my gait → no running plan today.
- **D3** Posterior thigh / sit-bone pain (hamstring tendinopathy signal) → no
  speed, no hills, no long stride. Flag it explicitly, given the history.
- **D4** Three consecutive days of self-report ≤3/10 → propose a recovery week,
  flag possible overreaching.
- **D5** Fever or systemic illness → no running.
- **D6** You are not a doctor or physio.

### E — Anti-drift

- **E1** Every deviation logged with a reason code from this closed set:
  `TRAVEL RACE ILLNESS INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS OVERRIDE`.
  "I feel tired" is not a reason code. `READINESS` requires cited data.
- **E2** If rolling 3-week actual < the block's compliance floor, `out/today.md`
  must **open** with a warning stating the shortfall in miles.
- **E3** Never soften the framing. If I'm behind, the first line says I'm behind.
- **E4** An `OVERRIDE` requires me to type `OVERRIDE: <reason>`. You may never
  assume one. Overrides append to `context/overrides.md`.
- **E5** If overrides exceed 2 in any 4-week block, `out/today.md` must state that
  the plan is not matching my life and propose a **structural** revision for my
  approval — not more overrides.

---

## 7. Data layer — run BOTH sources

### A — `garminconnect` (cyberjunky/python-garminconnect)

Email/password auth, MFA prompt supported, cache token (`~/.garminconnect`).
Pull: activities (last 150 days) + details, laps/splits, HR + pace streams,
**activity start times** (needed for §1 time-of-day), training readiness, training
status, acute/chronic load, HRV status, sleep, resting HR, body battery, stress,
VO2max, race predictions, lactate threshold pace/HR, daily stats.

Handle 401 / auth-changed / Cloudflare block / rate limit. **Fail loudly with the
real error — never silently return empty data.**

### B — intervals.icu REST

API key + athlete ID from `.env`. Verify the auth scheme against current docs
(I believe HTTP Basic, username `API_KEY`, key as password — confirm). Pull
activities, wellness (HRV, sleep, resting HR, weight, subjective fields),
events/calendar, and CTL/ATL/TSB.

### Reconciliation

`mc sync` writes both raw trees, then reports: activities present in one source
only, fields disagreeing >2% (distance, duration, avg HR), and staleness per
source. Every digest opens with a **Data health** block. If a source is stale

> 36h or failed, that must appear in bold at the top of `out/today.md`.
> **Never present an adaptation as data-driven when the data didn't arrive.**

---

## 8. `out/today.md` format

```markdown
# 28-07 · Week 1/14 · w/c 27-07 · 14 weeks to NYC

> ⚠️ <only if E2/E5 triggered or data stale>

## Today — 8 mi easy @ HR 135–145
Usual slot: 06:45. Forecast 84°F by 09:00 → **go before 07:30 or substitute**.

## Why
- <2–4 bullets citing real numbers from the digest>

## If you can't or shouldn't run
| Option | Duration | Equivalent | Verdict |
|---|---|---|---|
| Elliptical | 58 min @ HR 135–145 | ~88% | ✅ good substitute |
| Ellip 30 + bike 28 | 58 min | ~82% | ✅ fine |
| Bike | 72 min @ HR 130–140 | ~72% | ⚠️ aerobic only |
| Treadmill | 68 min | 100% | ❌ over 45 min limit |

Lost if substituted: impact/tendon adaptation. Substitutions used this week: 1/2.

## Strength & mobility (12 min)
- <2–3 items, sourced, hamstring-safe>

## Rest of the week
| Day | Planned | Adjusted | Reason |
|---|---|---|---|
| 01-08 | 5 mi pace | 5 mi pace | — |
| 02-08 | 10 long | 10 long | — |

## Watch
- <specific things to monitor, or "nothing">

## Compliance
Week 1: 26/28 mi · long run Sun 02-08 10 mi (locked) · run days 4/4 ·
long-run ratio 0.31 (cap 0.32) · rolling 3wk n/a · overrides this block 0/2
```

Terse. No motivational filler. No emoji beyond the verdict/warning markers.
try to use HR over min/mile, if you use min/mile just estimate it. provide HR goald to gramin connect
`mc render` produces `out/today.html` from this.

---

## 9. Push to Garmin Connect (opt-in, never automatic)

Use `garminconnect`'s workout API — verify the real surface, but expect
`RunningWorkout`, `WorkoutSegment`, `create_warmup_step`, `create_interval_step`,
`create_distance_interval_step`, `create_cooldown_step`, `create_repeat_group`,
then `upload_running_workout()`, `schedule_workout(id, "YYYY-MM-DD")`,
`update_workout()`, `delete_workout()`, `unschedule_workout()`.

- `mc push --date DD-MM` shows a full text preview, requires explicit `--yes`.
  Never push as part of `sync` or the daily ritual.
- Name workouts `MC W{week} {DD-MM} {type}`.
- `--dry-run` prints the JSON payload, no network.
- `mc unpush --date DD-MM` removes it.
- Store IDs in `data/pushed.json` so re-pushing updates in place, no duplicates.
- **Refuse to push any workout that violates §6.**
- Targets in min/mile and HR. Never pace targets on the long run beyond a ceiling.

---

## 10. CLI

```
mc sync [--since DAYS] [--source garmin|intervals|both]
mc digest [--date DD-MM]
mc status                    # week N of 14, plan vs actual, compliance, ratios
mc check                     # run rules.py on current week, print violations
mc week [--week N | --wc DD-MM]
mc equiv "8 mi easy"         # substitution table on demand
mc render [--all]            # markdown -> html
mc log "<free text>"
mc push --date DD-MM [--dry-run] [--yes]
mc unpush --date DD-MM
```

---

## 11. Slash commands — `.claude/commands/`

- **`daily.md`** — `mc sync` → `mc digest` → read digest, `plan.lock.json`,
  `context/`, last 14 days of log → ask me **at most 4** questions (feel 1–10,
  sleep, shins/hamstring, anything changed in the next 7 days) → `mc check` →
  write `out/today.md` + `.html` and append to `log/sessions/`. Never more than
  4 questions. Never pad.
- **`week.md`** — Monday review: last week plan vs actual, rolling compliance,
  long-run ratio trend, run-days trend, next week's layout, deviations table.
- **`travel.md`** — I paste dates; you re-lay-out affected weeks under §6B and
  show before/after with the rule that drove each decision.
- **`italy.md`** — dedicated: rebuild weeks 7–10 given whatever actually happened,
  bodyweight-only strength, opportunistic long runs, arrival/return sleep windows.
- **`push.md`** — preview and push next N days.

---

## 12. `CLAUDE.md`

Contains §6 verbatim, §4's verdict vocabulary, the daily ritual, the reason-code
set, the date/unit conventions, and at the top:

> Before proposing any change to training, load `plan/plan.lock.json` and run
> `mc check`. If a proposal violates a rule, say so and propose a compliant
> alternative. **Do not present a violating plan with a caveat.** Do not agree
> with me that a rule should be bent — only an explicit typed `OVERRIDE:`
> does that. Units are miles and min/mile. Weeks are `Week N · w/c DD-MM`.
> Days are `DD-MM`.

---

## 13. Tests

`pytest` covering every A-rule, every B-shuffle case (including the Sunday→Monday
stacking trap, cross-week swap, and the full Italy block), A9 ratio enforcement,
the equivalence engine, compression logic, and digest generation from fixtures.
Rules tested against synthetic travel scenarios, not happy paths.

---

## Build order

1. Repo, env, `.env.example`, git init
2. `garmin.py` + `intervals.py` + `sync.py` + reconciliation — **verify against
   real data before going further**
3. `digest.py`, including time-of-day extraction
4. §5 Step 1–2: research + my actual current fitness → show me
5. §4 research → `context/equivalence.md` → show me
6. Compression + Italy block + shin adaptation → show me → **freeze on my approval**
7. `rules.py` + full test suite
8. `equivalence.py`, `render.py`, `cli.py`, slash commands, `CLAUDE.md`
9. `push.py` last, dry-run only until I confirm
10. write an easy readme to explain all the feature, functions and example of a normal use
