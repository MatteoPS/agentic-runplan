Run the daily training ritual for marathon-2026. Follow this sequence exactly.

## 0. State guard

Run `mc state --check` first. If it refuses, the private state repo is behind
its remote — another machine wrote training history you don't have. **Stop and
pull.** Do not work around it: `training-log.md`, `strength_schedule.json` and
`pushed.json` are rewritten whole with no merge logic, so writing from a stale
copy deletes the other machine's day silently. (No-op when `MC_STATE_DIR`
isn't set.)

## 1. Sync and digest

Run `mc sync` (in this terminal, not backgrounded — if it needs Garmin MFA it
will prompt interactively). Then run `mc digest`. If either source reports
`ok: false` or `stale_gt_36h: true`, that must appear in **bold** at the very
top of `out/today.md` later — never present an adaptation as data-driven when
the data didn't arrive (§7).

`mc digest` also backfills any pending rows in `log/training-log.md` from
this fresh data — if it reports backfilling entries, glance at what actually
happened on those days (the Actual column) before assuming yesterday went as
planned.

## 2. Read context

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

Also run `mc strength <week_num> --week-start DD-MM` (no `--set-days`) for
this week's fixed strength days and progression tier — this week's two days
were chosen during `/week`. If it reports "not yet set for this week" (e.g.
first `/daily` of a week that skipped `/week`), decide next week's day
layout right now per `/week` step 5 and call `mc strength` with `--set-days`
before continuing.

Then run `mc strength <week_num> --week-start DD-MM --pending <today's DD-MM>`
to check whether a fixed strength day from earlier this week (normally
yesterday) still needs a done/missed confirmation. If it prints a day
(not `none`), that becomes question 5 below.

## 3. Ask at most 4 questions (5 if a strength day needs confirming)

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
5. **Only if step 2's `--pending` check returned a day**: "Did you do
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

## 4. Check

Run `mc check`. If it reports violations, do not present a violating plan
with a caveat — propose a compliant alternative instead (per the top of
`CLAUDE.md`). If my answers imply I want to deviate from the plan,
that requires an explicit typed `OVERRIDE: <reason>` from me — never assume
one just because I said I feel good or tired.

## 5. Write `out/today.md`

Follow the exact format from spec §8:

```markdown
# DD-MM · Week N/14 · w/c DD-MM · N weeks to NYC

> ⚠️ <only if E2/E5 triggered or data stale — omit this line entirely otherwise>

## Today — <session>
Usual slot: <time>. <forecast note if relevant> → <action>

## Why
- <2–4 bullets citing real numbers from the digest — no filler>

## If you can't or shouldn't run
<substitution table from `mc equiv "<today's session>"`>

Lost if substituted: <from equiv output>. Substitutions used this week: X/Y.

## Strength & mobility (N min)
<If today is one of this week's `mc strength` fixed days: "**Fixed session
X/2 this week — after today's run.**" followed by that command's tiered
items (name, protocol, minutes, source), verbatim, not freehanded. Otherwise
2-3 items from equivalence.py's propose_strength_mobility, sourced, framed as
optional.>

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
- <specific things to monitor, or "nothing">

## Compliance
Week N: X/Y mi · long run <day> Xmi (locked) · run days X/Y ·
long-run ratio X.XX (cap X.XX) · rolling 3wk X% · overrides this block X/2
```

Terse. No motivational filler. No emoji beyond ✅/⚠️/❌ verdict markers and the
⚠️ warning line. Units are miles and min/mile. If behind, the first line says
so plainly (§6 E3) — never soften it.

`/daily` writes `out/today.md` only — no HTML rendering (read on GitHub as
markdown; run `mc render --all` yourself if you ever want the HTML twin).
Append a summary line to
`log/sessions/YYYY-MM-DD.md` via `mc log "<summary>"`, and record the day's
prescription in `log/training-log.md` via `mc propose "<today's session>"`
(same text as the "## Today —" line). Its Actual column fills in
automatically by tomorrow's `mc digest` step, once real data exists — that's
how you'll know the day after whether I actually did this, did
something else, or skipped it, without having to ask again.

Finally, run `mc state --save "daily DD-MM"` to commit and push today's state.
This is what makes the day visible to any other machine — skipping it leaves
the next `/daily` there working from history that looks complete but isn't.
(No-op when `MC_STATE_DIR` isn't set.)

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
