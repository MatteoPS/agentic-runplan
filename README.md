# agentic-runplan

A local system that daily adjusts a fixed training plan with a rule-based
agent-driven tool. Built to get me to the [TCS NYC Marathon](https://www.nyrr.org/tcsnycmarathon) on November 1st 2026.

The mechanism is NOT marathon or running-specific. Swap in a different plan and it works for any fixed-endpoint program: a race, a strength cycle, a diet — anything with a start date, an end date, and rules about how much you can deviate along the way.

- **Plan** — `plan/plan.lock.json`, frozen. Encodes the plan once: what
  happens, when, and how much.
- **Rules** — `src/mc/rules.py`, ~30 explicit rules (`CLAUDE.md` §6):
  ```
  A  immutable       — long-run distance, compliance floor, race date
  B  shuffleable     — travel machinery, under hard constraints
  C  free to adjust  — reordering, pace, cross-training swaps
  D  safety stops    — refuse to produce a session
  E  anti-drift      — every deviation logged with a reason code
  ```
- **Data** — Garmin Connect + intervals.icu, cross-checked against each
  other, feeding real numbers into every decision.
- **Agent** — [Claude Code](https://claude.com/product/claude-code) slash
  commands (`/daily`, `/plan`, `/preview`, `/week`, `/travel`) run it
  day-to-day, governed by `CLAUDE.md`.

Every proposed change is checked against the rule engine before it's shown;
every deviation gets a reason code from a closed set, logged — so
"I felt tired" never quietly becomes the new plan.

See `examples/` for fabricated sample output (what `/daily` actually
produces) without any of my real training or health data.

**Personal data never lives in this repo.** `out/`, `log/` and `data/` are
gitignored here, and in my own setup `MC_STATE_DIR` points them at a separate
*private* repo entirely — so the split is structural rather than a matter of
remembering. Unset, everything falls back to this checkout and behaves as a
normal single-repo project. See [Private state](#private-state-optional).

## What it actually does

- **Pulls real data** from Garmin Connect and intervals.icu, cross-checks
  the two sources against each other, and tells you plainly when something's
  stale or missing rather than pretending it isn't (`mc sync`).
- **Turns the cache into a daily digest** — data health, actual habitual
  training times (weekday vs. weekend, AM vs. PM), recent activity log,
  rolling volume, running form, weather, and a wellness snapshot
  (`mc digest`).
- **Knows what the weather will actually be** (`mc weather`) — ambient
  conditions by training window (early / morning / midday / evening), each
  summarised by its *worst* hour, because a window is a commitment to be
  outside for all of it. Source is [Open-Meteo](https://open-meteo.com):
  no API key, one call per sync. This is what turns "is it too hot to run
  outside?" from a guess into a cited number — and the location comes from
  your most recent GPS activity, so it follows you when you travel.
- **Reads the metrics your watch already recorded and nobody looked at** —
  cadence, elevation gain, grade-adjusted vs. raw pace, and for longer runs
  whether cadence, *stride length* and grade-adjusted pace held from the first
  third to the last. All of it parsed from data already on disk: **zero extra
  API calls**. A 166 spm average over 10 miles is equally consistent with
  holding 166 and with running 172 then 160; only the split can tell you
  which. And cadence alone isn't enough — in the 2025 NYC marathon that fed
  this design, cadence *rose* over the closing miles while stride length fell
  10%, so the two are tracked separately and the digest says which one moved.
- **Asks instead of assuming when something looks off.** Every run is tagged
  with the dew point it actually happened in, so a slow one gets a question
  ("was it hot, was it meant to be easy, did something hurt?") rather than a
  verdict. Conditions explain a pace; they never excuse a session, which
  still needs a reason code. None of this is a diagnosis — it's descriptive,
  and no rule fires on it.
- **Holds a frozen, immutable plan** (`plan/plan.lock.json`) — in my case a
  [Hal Higdon Intermediate 1 marathon](https://www.halhigdon.com/training-programs/marathon-training/intermediate-1-marathon/) plan compressed 18→14 weeks, with a
  3-week travel block built in as a first-class part of the plan (not a pile
  of one-off overrides) and a reduced-running-days adaptation for a shin
  injury history.
- **Enforces the rules for real.** `rules.py` checks any proposed week
  against the plan — protected long runs, compliance floors, a "no
  increases even if I feel great" ceiling, aerobic-load ratios, the whole
  travel-shuffling machinery (move within the week → split same-day → swap
  with an adjacent week → reduce, in that strict priority order, never
  skipping ahead), safety stops for real symptoms, and an anti-drift system
  that catches when overrides are becoming the norm instead of the
  exception.
- **Tells you what a substitution actually costs** (`mc equiv`) — cross-
  training options for any prescribed session, with a real percentage and
  what specifically you lose, sourced from real research, not made-up
  numbers. Some sessions (a marathon's long run, in my case) never get a
  substitute — that's a hard rule, not a suggestion.
- **Can push workouts to a device** (Garmin Connect here), but only when you
  say so — `mc push` always shows a full preview first and requires an
  explicit confirmation flag before it touches your real account.

## Setup

You need Python 3.12+ and [uv](https://docs.astral.sh/uv/). From the repo
root:

```
uv sync
```

Then create `.env` (copied from `.env.example`) with your own credentials —
**edit this file yourself**, this tool will never ask you to paste secrets
into a chat:

```
GARMIN_EMAIL=you@example.com
GARMIN_PASSWORD=your-password
INTERVALS_API_KEY=your-intervals-api-key
INTERVALS_ATHLETE_ID=iXXXXXX
```

`INTERVALS_API_KEY` and `INTERVALS_ATHLETE_ID` are both on your intervals.icu
Settings page. Your intervals.icu account needs to actually have Garmin
connected to it (in intervals.icu's own settings) for it to have any
activity history to reconcile against.

First run needs to happen in your own terminal, not through an agent — if
your Garmin account has MFA on (probably does), it'll prompt for a code
interactively:

```
uv run mc sync
```

After that, a session token is cached under `data/.garmin_tokens/`
(gitignored) and you won't need to enter an MFA code again unless the cache
is invalidated. Every later run detects whether there's a terminal to prompt
in, so a cron job or a cloud session gets a clear error instead of hanging on
a prompt nobody can answer.

### Private state (optional)

```
MC_STATE_DIR=~/marathon-2026-state
```

Points `log/`, `out/`, `data/` and `context/overrides.md` at a separate
**private** repo, so this one can stay public and code-only. Unset, all of it
lives in this checkout and nothing changes — you don't need this to use the
system.

You keep working in *this* directory as normal; only the state files are
written elsewhere. Credentials stay out of both repos: `.env` is local, and
`data/.garmin_tokens/` holds refresh tokens, so it's gitignored in the state
repo too.

If you use it from more than one machine, **one writer per day**.
`log/training-log.md`, `data/strength_schedule.json` and `data/pushed.json`
are rewritten whole with no merge logic, so writing from a stale checkout
drops the other machine's day silently — and a lost key in `pushed.json`
makes the next push create a *duplicate* Garmin workout. `mc state --check`
enforces this rather than trusting you to remember; `/daily`, `/week` and
`/preview` call it before writing and `mc state --save` after.

Git is the sync layer on purpose: it refuses to merge that conflict, where a
cloud drive would resolve it quietly. A side benefit is that `out/today.md`
becomes readable from the GitHub mobile app with no further setup.

### Getting the daily output onto a phone (optional)

```
MC_EXPORT_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/marathon
```

Makes `mc render --all` copy `out/*.html` and `today.md` into that local
folder. If it happens to sit inside a folder your cloud client already syncs,
that client carries it to your phone — `mc` makes no network call and holds no
cloud credentials. Unset, the feature is off.

### Weather (optional, on by default)

No API key exists for [Open-Meteo](https://open-meteo.com), so there's nothing
to configure for the common case — `mc sync` fetches a forecast and everything
else reads the cache. The only thing that leaves your machine is **one
coordinate pair, rounded to 2 decimal places** (~1.1 km), taken from your most
recent GPS activity so it follows you when you travel. Rounding costs nothing:
Open-Meteo snaps every request to its own model grid anyway, so finer
coordinates describe your doorstep without improving the forecast.

```
MC_WEATHER_LAT=40.80        # override the inferred location — wins when set,
MC_WEATHER_LON=-73.96       # so it won't follow you; `mc weather` prints which
                            # source was used on every run
MC_TEMP_UNIT=celsius        # display only; °F is canonical internally, so
                            # thresholds never shift when you flip this
MC_WEATHER=off              # no forecast, no outbound call at all
```

## Normal use — a typical day

Most days, you'd just run the `/daily` slash command in Claude Code. It:

1. Runs `mc sync` then `mc digest` so everything reflects real, fresh data.
2. Reads the digest, the locked plan, and recent training log.
3. Asks up to 4 quick questions — how you feel (1-10), sleep, any injury
   symptoms specific to your plan, anything changing in the next week. Never
   more than that, never padded with questions the data already answers.
4. Runs `mc check` against the current week and, if anything's off, proposes
   a compliant alternative instead of just noting the problem.
5. Writes `out/today.md` (and its HTML twin) — today's session, why, a
   substitution table in case you can't or shouldn't do it, a short sourced
   strength/mobility block, the rest of the week, and a compliance line that
   never softens the framing if you're behind.

If you want to see the plan without the full ritual:

```
uv run mc status              # this week: plan vs actual, compliance, ratios
uv run mc week --week 6       # any specific week
uv run mc check               # run the rule engine against the current week
uv run mc equiv "8 mi easy"   # what would elliptical/bike get me instead?
```

Then `/plan 3` shows today plus the next two days (projected, and labelled as
such), and `/preview` at the end of the day logs what you actually did and
previews tomorrow — enough to decide whether to set an early alarm.

Other slash commands: `/week` (Monday review — compliance trend, next week's
layout), `/travel` (an unplanned trip — reshuffles affected weeks under the
travel rules), `/italy` (my known trip block specifically — a template for
any pre-planned disruption baked into the plan up front), `/push` (preview
and push upcoming workouts to Garmin, always with an explicit confirmation
step).

## CLI reference

Everything runs as `uv run mc <command>`.

| Command                                                      | What it does                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mc sync [--since DAYS] [--source garmin\|intervals\|both]`  | Pull fresh data. Never runs automatically — this is the only thing that talks to Garmin's API.                                                                                                                                                                                                                                                                                                |
| `mc digest [--date DD-MM]`                                 | Regenerate the markdown digest from cached data.                                                                                                                                                                                                                                                                                                                                               |
| `mc weather [--date DD-MM] [--days N] [--refresh]`         | Conditions by training window, each summarised by its worst hour, coolest marked. Reads the cache written by `mc sync`; `--refresh` fetches now. Heat levels are `none/noticeable/hard/extreme` — a reporting label to cite, never a rule that fires on its own. |
| `mc status`                                                | Current week: plan vs. actual, compliance floor, long-run ratio.                                                                                                                                                                                                                                                                                                                               |
| `mc check`                                                 | Run the rule engine against the current week and print any violations.                                                                                                                                                                                                                                                                                                                         |
| `mc week [--week N \| --wc DD-MM]`                          | Show any week's plan and actuals.                                                                                                                                                                                                                                                                                                                                                              |
| `mc equiv "8 mi easy"`                                     | Substitution table for a prescribed session.                                                                                                                                                                                                                                                                                                                                                   |
| `mc strength N --week-start DD-MM [...]`                   | This week's fixed strength day(s), current progression tier, and done/missed confirmation + auto-reschedule for a missed fixed day.                                                                                                                                                                                                                                                            |
| `mc render [--all]`                                        | Markdown → standalone HTML.`--all` also regenerates `dashboard.html`.                                                                                                                                                                                                                                                                                                                     |
| `mc log "<text>"`                                          | Append a note to today's session log.                                                                                                                                                                                                                                                                                                                                                          |
| `mc propose "<text>" [--date DD-MM]`                       | Record today's proposed session into`log/training-log.md`. Its Actual column fills in automatically by the next day's `mc digest`, once real data exists — a running proposed-vs-actual table, so a missed or swapped session is never lost track of.                                                                                                                                     |
| `mc push --date DD-MM [--option NAME] [--dry-run] [--yes]` | Preview or push a workout to Garmin —`run`, `elliptical`, or `bike`, each as its own real Garmin workout type. `--option` picks a specific substitution-table alternative (e.g. `--option bike`) instead of the primary Today prescription. `--dry-run` prints the JSON payload with no network call; a real push needs `--yes` and will refuse outright if it violates a rule. |
| `mc unpush --date DD-MM`                                   | Remove a previously pushed workout.                                                                                                                                                                                                                                                                                                                                                            |
| `mc layout N --week-start DD-MM [--set "DD-MM:mi[:type]"]` | Show or set the week's day-of-week layout. `plan.lock.json` freezes weekly totals; day placement is decided each Monday and persisted here, so the rest of the system can answer "what is Thursday?". `--revise` overwrites a live week. Prints whether the layout passes §6. |
| `mc plan [--days N]`                                       | The next N days (default 3). Day 1 from real data; days 2+ projected under stated assumptions, and marked as such. |
| `mc drift [--weeks N]`                                     | Plain-language summary of the trailing 4 weeks: miles short, which days deviated, which reason codes recur, overrides against the limit of 2. Counts and dates only — never a diagnosis. |
| `mc override "<reason>" --code CODE`                       | Append a §6 E4 override to `context/overrides.md`. Only ever run after the literal `OVERRIDE:` string is typed — never inferred. |
| `mc export`                                                | Copy `out/*.html` and `today.md` into `MC_EXPORT_DIR`. Runs automatically at the end of `mc render --all`; this is the manual re-copy. |
| `mc state [--check \| --save "msg"]`                       | Guard and sync the private state repo. `--check` refuses to proceed from a checkout that's behind; `--save` commits and pushes. No-op unless `MC_STATE_DIR` is set. |

## Project layout

```
src/mc/          the actual system: sync, digest, plan, planning, rules, layout, equivalence,
                 render, export, drift, state, cli, push, strength, weather, metrics
plan/            plan-source.md (verbatim Higdon), plan.md (compressed + reasoning),
                 plan.lock.json (frozen, immutable — see CLAUDE.md for how it's protected)
context/         equivalence.md (sourced cross-training research), overrides.md, athlete context
log/             training-log.md, and a dated file per day under sessions/ — real data
data/            raw API caches, week layout, strength + push state — real data
out/             today.md/.html, dashboard.html — real data
                 ^ all three are gitignored here, and relocate wholesale to the private
                   state repo when MC_STATE_DIR is set
examples/        fabricated sample output/logs/data showing the shape of the above without real data
.claude/commands/ the slash commands (daily, plan, preview, week, travel, italy, push)
docs/            devlog.md (why the system changed, newest first), todo-review.md
tests/           pytest — 303 tests covering the rule engine, sync reconciliation, the equivalence
                 engine, digest generation, strength progression, and push.py, the week layout, drift and
                 the headless-auth path, run against synthetic
                 fixtures and, where it matters (like the travel-block dates), the real frozen plan
```

`CLAUDE.md` at the repo root has the full rule engine (§6) verbatim, the
verdict vocabulary, reason codes, and date/unit conventions — that's what
governs how any AI assistant working in this repo should behave, not just
documentation.

## Testing

```
uv run pytest
```

303 tests, no network calls — everything is checked against either a
synthetic plan fixture built to exercise every block type, or the real
frozen `plan.lock.json` where the test genuinely needs real dates (the
travel-block arrival/return windows) or wants to confirm the actual frozen
plan passes its own rule engine with zero violations.

## A few things worth knowing

- **Units are always miles and min/mile.** Never km.
- **Dates are `DD-MM`, weeks are `Week N · w/c DD-MM`** (weeks start Monday)
  — consistently, everywhere in this system.
- **`plan.lock.json` is immutable.** Once frozen, nothing rewrites it
  silently — see `CLAUDE.md`'s opening note on what it takes to actually
  change it (`OVERRIDE: <reason>`, typed explicitly, never assumed).
- **The rule engine's numbers were negotiated, not defaults.** The long-run
  ratio caps and compliance floors in the frozen plan were adjusted from the
  spec's own starting numbers after real discussion (see `plan/plan.md` for
  the reasoning) — they're not approximations waiting to be "corrected."
- This is not a substitute for medical advice. If something sounds like a
  real injury, the system is designed to say so and stop optimising, not
  push through it.
- **This instance is marathon-specific by content, not by design.** The plan
  data (`plan/plan.lock.json`), the rule numbers (§6), and the cross-training
  research (`context/equivalence.md`) are all specific to my NYC Marathon
  build. The engine itself (`rules.py`'s A–E rule categories, the
  lock/override/reason-code model, the travel-shuffling priority order) is
  generic to any fixed-endpoint plan with immutable milestones and a real
  cost to deviating from them.
