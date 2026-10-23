Run the daily training ritual for marathon-2026. Follow this sequence exactly.

## 0. What day is it

Run `mc today` **before anything else**, and use the `DD-MM` it prints for
everything you write this session — the `# DD-MM` header, the
`mc state --claim "daily DD-MM"` string, `mc propose`, every table row.

Do not use your own sense of the date. This project runs from a container whose
clock is UTC, and so is the date you were given at the top of this session: from
20:00 Eastern onward both are already *tomorrow*. A `# 25-08` header written on
the evening of the 24th is how `out/today.md` gets deleted as stale by the next
`mc tidy` (which is exactly what happened on 24-08-2026), and how a session gets
logged onto the wrong training-log row.

`mc today` prints the timezone it used. If it says anything other than the zone
I am actually in — `America/New_York` at home, `Europe/Rome` during the Italy
block — say so rather than working from it: the fix is `MC_TZ`, not arithmetic.

## 1. State guard

Run `mc state --claim "daily DD-MM"` next. It runs the staleness check and
then announces this device as today's writer.

If it refuses, read *which* refusal it is:

- **behind its remote** — another machine wrote training history you don't
  have. **Stop and pull.** Do not work around it: `training-log.md`,
  `strength_schedule.json` and `pushed.json` are rewritten whole with no merge
  logic, so writing from a stale copy deletes the other machine's day
  silently.
- **another device holds the writer lease** — a ritual is in flight
  *elsewhere right now* (typically: the phone). Nothing is pushed yet, so
  there is nothing to pull; the answer is to finish it there, not to take it
  over. Only `--force` when you know that session is dead, and say out loud
  that you did.
- **this device already holds one** — a previous ritual on this machine never
  reached `mc state --save`. Say so; it usually means the last `/daily` or
  `/preview` was abandoned half-written.
- **`/daily` has already run today** — `out/today.md` is already dated today,
  on this device or on one whose save you just pulled. **Stop there.** Do not
  re-run any of the steps below, do not re-ask the four questions, and do not
  write `out/today.md`. Say which device wrote it and when, then point me at
  what I actually want: `mc sync` to fold in activity data recorded since,
  `/preview` to close the day out and project tomorrow, or `out/today.md`
  itself to re-read the plan. Running it twice rewrites a prescription I have
  already acted on and logs one day twice.

  Take it over only when I explicitly ask for today to be **rewritten** —
  `mc state --claim "daily DD-MM" --again` — and say out loud that the earlier
  version is being replaced. `--force` does not do this and must not be used
  for it; it takes over a *lease*, and reusing it here would mean a dead phone
  session and a finished day get the same answer.

If `--claim` prints a warning that the lease was **not pushed**, repeat it to
me verbatim: the other device cannot see it, so writing now is unguarded.

(No-op on the git side when `STATE_ROOT` isn't a git repo, or `MC_STATE_GIT=off`;
the lease still applies
locally, where it catches two sessions on one machine.)

## 2. Sync and digest

Run `mc sync` (in this terminal, not backgrounded — if it needs Garmin MFA it
will prompt interactively; the intervals.icu half never prompts, it is an API
key). Then run `mc digest`. If either source reports `ok: false` or
`stale_gt_36h: true`, that must appear in **bold** at the very top of
`out/today.md` later — never present an adaptation as data-driven when the
data didn't arrive (§7).

**One source failing is not the same as no data.** intervals.icu alone
supplies activities, per-sample form streams, and the HRV/sleep/resting-HR C2
spends; Garmin alone supplies everything plus Body Battery, training status
and VO2max. Say which source answered — `mc digest` labels each wellness
reading — rather than reporting a number as if both agreed when only one was
asked.

`mc digest` also backfills any pending rows in `log/training-log.md` from
this fresh data — if it reports backfilling entries, glance at what actually
happened on those days (the Actual column) before assuming yesterday went as
planned.

## 3. Read context

Read, in order:
- `plan/plan.lock.json` — today's week's targets (`mc week` is a fast way to see this)
- `data/digest/latest.md` — data health, time-of-day patterns, recent activity, wellness snapshot
- `context/equivalence.md`, `context/overrides.md`
- `log/training-log.md` — proposed vs. actual, so you know whether recent days
  went as planned or I had to skip/swap something (check for any row
  whose Actual doesn't match its Proposed)
- The last 14 days of `log/sessions/*.md`

Also run `mc plan --days 3` for this week's persisted day layout and the two
days after today — that's what fills the "Next 2 days" section below. If it
reports no layout for this week, `/week` hasn't run: decide the layout now per
`/week` step 5 and persist it with `mc layout` before continuing, rather than
projecting from a weekly average.

Run `mc weather` for today's and tomorrow's conditions by training window.
This is what backs the "forecast note" in the Today line below and the time-of
-day choice under C6 — pair it with the digest's time-of-day table, which shows
which slots I actually use. If the heat level is `hard` or `extreme` in every
window I'd realistically train in, that is a **cited** C2 trigger (quote the
feels-like and dew point, never just "it's hot"). It is still only a trigger,
never an automatic swap: weigh it with shins and readiness like any other
signal. If `mc weather` reports no cached forecast or a stale one, say so
rather than reasoning about weather you don't have (§7).

Also run `mc strength <week_num> --week-start DD-MM` (no `--set-days`) for
this week's fixed strength days and progression tier — this week's two days
were chosen during `/week`. If it reports "not yet set for this week" (e.g.
first `/daily` of a week that skipped `/week`), decide next week's day
layout right now per `/week` step 5 and call `mc strength` with `--set-days`
before continuing. **Whether today is one of those two days is what decides
whether `out/today.md` gets a Strength & mobility section at all** — see
"Sections that only appear when they apply" below.

Run `mc fuel "<today's session>"` too. It is silent under ~8 mi and prints a
plan above it, and on a day it prints one the counts go at the top of the
Fuelling section: gels, whether a packet of drink mix, tabs. `mc fuel ...
--prep` is the counts alone.

Then run `mc strength <week_num> --week-start DD-MM --pending <today's DD-MM>`
to check whether a fixed strength day from earlier this week (normally
yesterday) still needs a done/missed confirmation. If it prints a day
(not `none`), that becomes question 5 below.

## 4. Ask at most 4 questions (5 if a strength day needs confirming)

Ask me, in one message:
1. Feel today, 1–10
2. Sleep last night
3. `mc strength`'s `format_shin_check_prompt()` text verbatim — the 0-3 scale
   with its meaning restated every time, not assumed remembered:
   `0 = nothing; 1 = tender to palpation only, not felt during running;
   2 = aware of it during runs but not limiting; 3 = changes how you run.`
   Also ask about hamstring symptoms in the same breath (yes/no + description).
   A **3**, or any hamstring symptom, or gait-changing pain of any kind, is a
   D-rule safety stop — see §6 D1–D3. Don't optimise around real pain; say to
   see a professional and stop there. A **1-2** is a C2-eligible readiness
   signal, not a stop — note it in "Why" and weigh it with the other C2
   triggers (heat, ≥2 bad readiness signals) when deciding whether to swap
   today's run for cross.
4. Anything changing in the next 7 days? (travel, life, schedule)
   — **or**, when the digest's Running form section flags a pace outlier or a
   late-run cadence fade, spend this question on that instead: "your 31-07 ran
   X s/mi slower than baseline at a 66°F dew point — was it just hot, or was
   something else going on?" Ask about the specific run with its numbers. This
   **replaces** question 4, never adds a fifth.
5. **Only if step 3's `--pending` check returned a day**: "Did you do
   <DD-MM>'s fixed strength session?" (yes/no).

**Never more than 4 questions, 5 when a strength confirmation is pending.
Never pad with extra ones.** If the digest already answers something (e.g.
HRV, sleep from Garmin), don't ask it again — only ask what only I
know.

If Q5 was asked, record the answer before writing `out/today.md`:
- **Yes** → `mc strength <week_num> --week-start DD-MM --confirm "<DD-MM>:done"`.
- **No** → `mc strength <week_num> --week-start DD-MM --confirm "<DD-MM>:missed" --reschedule-candidates "DD-MM:mi,DD-MM:mi,..." --long-run-day DD-MM`
  (every remaining day this week with its planned miles). It auto-picks the
  best remaining day and reports it, or reports nothing suitable was left —
  either way, say what happened in "Why" and reflect the new day (if any) in
  the "Rest of the week" table, reason code `LIFE` unless I give a
  more specific one.

## 5. Check

Run `mc check`. If it reports violations, do not present a violating plan
with a caveat — propose a compliant alternative instead (per the top of
`CLAUDE.md`). If my answers imply I want to deviate from the plan,
that requires an explicit typed `OVERRIDE: <reason>` from me — never assume
one just because I said I feel good or tired.

`mc check` judges the week **as proposed**: actuals for the days already
settled, the persisted layout for the days still ahead. So a mid-week finding
is a real finding, not an artifact of an incomplete week — **do not dismiss it
as "we're only on Wednesday"**. The remedy for a week that no longer adds up is
`mc layout <n> --week-start DD-MM --revise` (C1, free), not an override.

If it prints **Degraded check**, no layout is set for this week and the
cumulative rules (A2/A9/A10 and friends) are not being judged at all. Say so in
the output rather than reporting a clean check — and run `mc layout` to fix it.

## 6. Write `out/today.md`

Follow the format below. It is spec §8's, with two sections made **conditional**
(17-08-2026) — §8 prints a substitution table and a strength block every day;
here they appear only when they have something to say. Everything else is §8
unchanged.

```markdown
# DD-MM · Week N/14 · w/c DD-MM · N weeks to NYC

> ⚠️ <only if E2/E5 triggered or data stale — omit this line entirely otherwise>

## Today — <session>
Usual slot: <time>. <forecast note if relevant> → <action>

## Why
- <2–4 bullets citing real numbers from the digest — no filler. Where a recent
  run's pace needs explaining, cite GAP and the dew point from the Running form
  table rather than calling it slow: "9:32 with 486 ft gain at a 66°F dew point
  (GAP 9:28)" is a fact; "a bit sluggish" is not. Conditions explain a pace;
  they never excuse a missed session — that still needs a reason code.>

## If you can't or shouldn't run
<**Omitted by default.** See "Sections that only appear when they apply" below —
this is printed when I ask for it, or when the ritual is itself steering me off
running.>

## Fuelling
<Only when `mc fuel "<today's session>"` returns a plan — it stays silent for
anything under 75 min, so omit this whole heading on those days. Print its
bullets verbatim, not freehanded: `prep_lines` first (the counts — how many
gels, whether a packet of drink mix, how many tabs), then the in-run schedule.
`mc fuel "<session>"` prints both in that order.

The counts lead because they are the part that can still be acted on at 6am —
being two gels short is discovered in the drawer or at mile 14, and only one of
those is fixable. If `/preview` already covered it last night, still print it:
this file is what gets read on the phone on the way out, and a number I have
already seen costs nothing to see again.

The schedule itself is **fixed**: a gel every 20 min, first at 40 min on a
normal breakfast, 20 min without one (pass `--fasted` — and if breakfast is in
doubt, fold the question into the existing "anything changing" one rather than
guessing). Weeks 6, 11 and race day start at 20 min regardless. Drink mix is
one packet on runs ≥14 mi, none in Italy. The g/hr figure is the
**consequence** of that cadence, not a target: never re-tune the gel count to
hit a rounder number, and never soften the shortfall line when `mc fuel` prints
one (E3). Full protocol and reasoning: `context/fueling.md`.

This is gut training — the 2025 NYC marathon ran on ~27 g/hr and the legs
emptied at mile 19. Ask what was actually taken and how the stomach handled it
in the next day's log — but this adds **no question** to the four; fold it into
the existing "anything changing" one or leave it.>

## Strength & mobility (N min)
<**Only on this week's two `mc strength` fixed days.** On one of them:
"**Fixed session X/2 this week — after today's run.**" followed by that
command's tiered items (name, protocol, minutes, source), verbatim, not
freehanded. On every other day omit the whole heading — see below.>

## Rest of the week
| Day | Planned | Adjusted | Reason |
|---|---|---|---|
<remaining days this week, reason column uses closed codes from §6 E1 or "—">

## Next 2 days (provisional)
<from `mc plan --days 3` — its rows for tomorrow and the day after, with the
assumptions line printed verbatim above them. See `.claude/commands/plan.md`
for what these days may and may not do: never `mc propose`d, never pushed,
no substitution table, and they add no questions. The heading must contain
the word "provisional" — that's what keeps `mc push` from consuming them.>

## Watch
- <specific things to monitor, or "nothing". Prefer items that can actually be
  checked tomorrow over ones that can't: "cadence has held 165-168 across paces
  from 8:48 to 9:32 — if the 12mi comes back under 162, say so" beats "monitor
  how the shins feel".>

## Compliance
Week N: X/Y mi · long run <day> Xmi (locked) · run days X/Y ·
long-run ratio X.XX (cap X.XX) · rolling 3wk X% · overrides this block X/2
```

Terse. No motivational filler. No emoji beyond ✅/⚠️/❌ verdict markers and the
⚠️ warning line. Units are miles and min/mile. If behind, the first line says
so plainly (§6 E3) — never soften it.

### Sections that only appear when they apply (17-08-2026)

A section printed every day whether or not it has anything to say is a section
that stops being read, and it takes the rest of the file down with it. Two were
printing unconditionally:

**The substitution table.** Omitted by default. Whether to swap a run for the
elliptical is a same-day judgement I make, and I will ask — the table is an
answer to a question, not a standing offer. It is printed in three cases, and
otherwise not at all:

- **I ask.** Anything from "can I do this indoors?" to "give me the swap" —
  run `mc equiv "<today's session>"` and add the section then, in full, with
  the ✅/⚠️/❌ verdicts, the *Lost if substituted* line and the substitutions
  -used-this-week count, exactly as it used to appear. Same on any day where I
  say up front that I can't run.
- **A D-rule stop.** D1–D5 refuse a running session, and D1 says in as many
  words to offer the elliptical if it's pain-free. Refusing the run and then
  offering nothing would be worse than either. The table appears, and so does
  "see a professional" — don't optimise around real pain.
- **A C2 swap I'm actually proposing.** If the cited signals (heat, shins at
  1-2, ≥2 bad readiness numbers) make cross the recommendation rather than an
  option, the table belongs with it. Cite the numbers, as C2 already requires.

Never as a hedge. If today is a run, prescribe the run.

Long runs never get one in any case — no substitute for a long run exists, and
offering one is how a long run quietly becomes 90 minutes on a bike.

**Strength & mobility.** Printed only on this week's two fixed `mc strength`
days. The old default — 2-3 optional items on every other day — was noise
against the thing that actually matters, which is that the two fixed sessions
are fixed. Off-day mobility is still C4 and still free: ask for it and it's
printed, same as the table. If I ask for the strength work on an unscheduled
day, print the tiered items for it and say plainly that it does **not** count
toward the week's two — the fixed days are set in `/week` and confirmed
done/missed by date, so an extra session is extra. Don't try to
`mc strength --confirm` it either; `confirm_day` refuses a day that isn't in
the schedule, and that refusal is right.

Neither omission changes what happens if I ask. Both are about the default.

`/daily` writes `out/today.md` — markdown only. Then run `mc render --all`,
which refreshes `out/dashboard.md` (so the completion percentages and finished
runs move every day, not just on Mondays), deletes anything in `out/` whose day
has passed, and exports if `MC_EXPORT_DIR` is set. It writes **no HTML** —
that's `--html`, and nothing in the ritual passes it.

Note the ordering: this tidies *before* `mc state --save` commits anything. If
`mc render --all` reports that it left a stale file in place because git has no
copy of it, that is the guard doing its job — save, and it goes next run. If it
ever reports deleting a file dated **today**, stop: the clock is wrong, and
`mc today` is the thing to check.

Append a summary line to
`log/sessions/YYYY-MM-DD.md` via `mc log "<summary>"`, and record the day's
prescription in `log/training-log.md` via `mc propose "<today's session>"`
(same text as the "## Today —" line). Its Actual column fills in
automatically by tomorrow's `mc digest` step, once real data exists — that's
how you'll know the day after whether I actually did this, did
something else, or skipped it, without having to ask again.

Finally, run `mc state --save "daily DD-MM"` to commit and push today's state.
This is what makes the day visible to any other machine — skipping it leaves
the next `/daily` there working from history that looks complete but isn't,
**and leaves this device holding the writer lease**, which will block the
other one until it expires. If the ritual ends without writing anything
(a D-rule stop, say), still run `mc state --release`.
(The commit records `Device: <id>`; no-op only when `STATE_ROOT` isn't a git
repo or `MC_STATE_GIT=off`.)

## Reason codes (closed set, §6 E1)

`TRAVEL RACE ILLNESS INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS OVERRIDE`

"I feel tired" is not a reason code. `READINESS` requires citing actual data
(HRV, sleep, RHR numbers), not a vibe.

If I type a literal `OVERRIDE: <reason>`, record it with
`mc override "<reason>" --code <CODE>`. Never run that command on a
paraphrase, however close — E4 means the literal string, and this command is
the writer for that moment, not the judge of it. It warns when the count
passes E5's limit of 2 in a 4-week block; if it does, propose a **structural**
revision for approval, not another override.

Run `mc drift` when the rolling picture is in question (E2/E5) — it states the
shortfall in miles and which reason codes keep recurring, in plain sentences.
