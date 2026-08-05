End-of-day command: close today out, then preview tomorrow.

Run in the evening. Two jobs, in this order.

The point of the preview is a decision I make tonight, not tomorrow morning:
**do I need to set an early alarm and run outside, or is this a session I can
do any time on the elliptical with AC?** Answer that explicitly — it's the
reason this command exists. It also covers the mornings I won't be able to
run `/daily` before heading out.

## 1. Close today out

1. `mc state --check`, then `mc sync`, then `mc digest`. If either reports `ok: false` or
   `stale_gt_36h: true`, say so in bold — never present an adaptation as
   data-driven when the data didn't arrive (§7).
2. Ask me **one** question: what did you actually do today? (If the digest
   already shows a completed activity matching the plan, don't ask — say what
   it shows and move on. Only ask when the data is absent or disagrees.)
3. Record it with `mc log "<what happened>"`. The `training-log.md` Actual
   column fills itself from Garmin — don't hand-write it.
4. If today was a fixed strength day, confirm it now rather than leaving it
   for tomorrow's `/daily`:
   `mc strength <week_num> --week-start DD-MM --confirm "<DD-MM>:done|missed"`
   (with `--reschedule-candidates` on a miss, as in `/daily`).
5. If what I did deviated from the plan, log it with a reason code from the
   closed set (§6 E1). "I felt tired" is not a reason code.

## 2. Preview tomorrow

Run `mc plan --days 2` (today + tomorrow) and read tomorrow's row, plus
`plan/plan.lock.json`, this week's layout, and `mc weather --date <tomorrow>`.

`mc weather` is what makes "The call" below an answer rather than a hedge: it
gives tomorrow's feels-like and dew point per training window, worst hour
first, with the coolest window marked. Quote the actual number — "early
(05:00-08:00) is 75°F feels-like at a 64°F dew point, evening is 85°F at 73°F"
— never "it'll be warm". If the forecast is missing or stale, say that plainly
and make the call on the reason it doesn't matter (an indoor session, a rest
day), rather than inventing a temperature.

Write `out/tomorrow.md`. It **must** carry:

- a `# DD-MM` header with **tomorrow's** date — `mc render` uses that to skip
  the file once it goes stale, and refuses to render a provisional file that
  won't say which day it's for;
- the word **Provisional** near the top, above any lookahead section — this
  is what makes `mc push` refuse it;
- the assumptions line from `mc plan`, verbatim.

```markdown
# DD-MM · Week N/14 · **Provisional** — confirmed by tomorrow's /daily

## Tomorrow — <session>
Assumes: normal sleep, full compliance with today, no new injury or shin
escalation, readiness unchanged from today.

## The call
Outdoor + early alarm, or indoor any time? <one plain answer, with the
forecast number or the reason it doesn't matter>

## Why
- <2-3 bullets from real data — today's actual session, the week's remaining
  miles, tomorrow's forecast>

## What would change this
- <the specific things that would make tomorrow's /daily differ: bad sleep,
  shins at 2+, heat above X>
```

`/preview` writes `out/tomorrow.md` only — no HTML rendering (run `mc render
--all` yourself if you ever want the HTML twin). Then `mc state --save
"preview DD-MM"`.

## Hard rules

- **Do not** `mc propose` tomorrow's session. It is a projection, not a
  proposal — putting it in `training-log.md` would have tomorrow's digest
  measure real life against an assumption.
- **Do not** push it. `mc push` refuses provisional files; that refusal is the
  safety mechanism, not an obstacle.
- **Do not** ask the `/daily` questions. Tomorrow's feel, sleep and shin score
  don't exist yet. Asking for them tonight produces stale answers that would
  then look authoritative.
- If tomorrow is the long run, say so prominently — and remember A3: the
  20-miler on Sun 11-10 and the 18 on Sun 06-09 are immovable.
- If a D-rule stop applies from today (shins at 3, gait change, hamstring
  symptoms, fever), tomorrow's preview is "no running plan — see how it is in
  the morning, and see a professional if it persists." Don't project through
  an injury.
