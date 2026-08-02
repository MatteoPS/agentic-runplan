Show the next N days — today from real data, the rest projected. Default 3.

I may say `/plan`, `/plan 3`, `/plan 5`. Without a number, use 3.

`/daily` already runs this for days 2-3 and appends the result to
`out/today.md`. Use this command standalone when I ask for the horizon
directly, or for a longer one.

## What this is, and what it is not

**Day 1 is real.** It is exactly what `/daily` produced: my answers, actual
sleep/HRV/RHR from the digest, yesterday's actual session.

**Days 2+ are projections**, computed under assumptions that have not
happened yet. Run `mc plan --days N` and print its assumption line verbatim
above them, every time — never paraphrase it away, never let a projected day
appear without it:

> Assumes: normal sleep, full compliance with the days before it, no new
> injury or shin escalation, readiness unchanged from today.

The single failure this command must not produce is a projection quietly
becoming a commitment. So, for projected days:

- **Never** `mc propose` them. They get no `log/training-log.md` row — that
  table is proposed-vs-actual, and a projection is neither.
- **Never** push them. `mc push` refuses anything marked provisional; don't
  work around it.
- **No substitution table.** Whether to swap a run for the elliptical is a
  same-day judgement needing that day's shins, sleep and forecast. Offering
  one for Thursday invites deciding Thursday on Tuesday's information.
- **Ask nothing.** `/daily`'s four-question limit is unchanged; projections
  add zero questions.

## Steps

1. Run `mc plan --days N`. It reads the persisted week layout, the plan lock,
   and this week's fixed strength days, and reports the week's §6 status.
2. If it says no layout is set for a week, say so plainly — the projection is
   then a weekly *average*, not a real day-of-week placement. Don't dress it
   up. Offer to run `/week` if the current week is the one missing.
3. If it reports §6 violations for this week's layout, lead with that. Do not
   show days as if they were fine.
4. Present as a table: day (DD-MM), planned miles, session, and for projected
   days anything that would change my morning — long run, fixed strength day.

## Format

```markdown
## Next N days (provisional beyond DD-MM)
Assumes: normal sleep, full compliance with the days before it, no new injury
or shin escalation, readiness unchanged from today.

| Day | Planned | Notes |
|---|---|---|
| 03-08 | 5 mi easy | fixed strength after |
| 04-08 | rest | — |
```

Terse. Miles and min/mile. Days are `DD-MM`. No motivational filler.
