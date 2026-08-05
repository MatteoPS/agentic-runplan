Monday review for marathon-2026. Run `mc state --check` first — if the
private state repo is behind, pull before doing anything else, or this
review is written against history that's missing another machine's days.
Then `mc sync` and `mc digest`, so everything below reflects real data, not
stale cache.

Produce a review covering:

1. **Last week: plan vs actual.** Use `mc week --week N` for the week that
   just ended (or `mc status` if it's still technically the current week
   number). Show long run, weekly volume, run days — planned vs actual —
   and whether it passed `mc check`.

2. **Rolling compliance.** Compute rolling 3-week actual vs. each week's
   block compliance floor. If it's below floor, that's an E2 trigger — say
   so plainly, don't bury it.

   Run `mc drift` too. It reports the trailing 4 weeks in plain language:
   shortfall in miles, which days deviated, which reason codes keep
   recurring, and the override count against E5's limit of 2. Quote its first
   line verbatim if it reports a shortfall. Treat recurring codes as a signal
   about the *plan*, not about me — three SHIN days in four weeks is a plan
   that needs revising, whether or not anyone typed OVERRIDE. It reports
   counts, never a diagnosis; don't turn its numbers into one (§6 D6).

3. **Long-run ratio trend.** Last 3-4 weeks' actual long-run ratio against
   each week's `long_run_ratio_max` from `plan.lock.json` — is it trending
   toward or away from the cap?

4. **Run-days trend.** Actual running days/week over the last 3-4 weeks
   against the shin-adaptation budget (4 most weeks, 5 in peak weeks).

   Also run `mc fuel "<next week's long run>"` and state this week's carb
   target in one line, so there's time to buy what it needs before the day.
   `/daily` prints the full plan; here it's a shopping note. The target ramps
   week to week on purpose — say the number, not "keep fuelling".

5. **Next week's layout.** Pull next week's targets from `plan.lock.json`
   (`mc week --week N+1`) and lay out a sensible day-of-week structure,
   respecting B1-B9 (Saturday-pace/Sunday-long pairing where it fits, ≥48h
   quality-session spacing, etc.) — day-of-week isn't frozen in the lock
   file, this is where it actually gets decided for the week.

   Once that layout is fixed, **persist it** — otherwise it exists only in
   this conversation and nothing can answer "what is Thursday?" later in the
   week:

   `mc layout <week_num> --week-start DD-MM --set "DD-MM:mi:type,..."`

   every day of the week, `type` one of `rest easy pace long cross` (omit it
   and it's inferred: 0 mi → rest, otherwise easy). Exactly one day must be
   `:long`. It prints the week and says whether the layout passes §6 — if it
   reports violations, fix the layout before moving on, don't note it and
   continue. First write per week wins; a mid-week C1 reshuffle uses
   `--revise` and gets a reason code in `log/sessions/`.

   Then call
   `mc strength <week_num> --week-start DD-MM --set-days "DD-MM:mi,DD-MM:mi,..." --long-run-day DD-MM`
   (every day of the week, mileage as planned) so the week's two fixed
   strength days get chosen deterministically — shortest non-long-run
   running days, done after that day's run — and persist for every `/daily`
   call that week. This only needs to run once per week; it's a no-op
   (returns the already-chosen days) if called again.

6. **Deviations table.** Every day last week that didn't match the plan
   exactly, with its reason code (closed set: `TRAVEL RACE ILLNESS INJURY
   SHIN HAMSTRING HEAT WEATHER LIFE READINESS OVERRIDE`) pulled from
   `log/sessions/` and `context/overrides.md`. Count overrides in the
   trailing 4-week block — if it's over 2, say the plan isn't matching real
   life and propose a structural revision for approval, per E5. Don't just
   suggest another override.

Units are miles and min/mile. Weeks are `Week N · w/c DD-MM`. Days are
`DD-MM`. Terse — this is a working review, not a narrative.

Finish with `mc state --save "week review w/c DD-MM"` so the layout, strength
days and review are committed and pushed.
