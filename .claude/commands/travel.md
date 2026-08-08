I will paste travel dates (unplanned trip, not the known Italy block —
that's `/italy`). Re-lay-out the affected week(s) under §6B, the long-run
shuffling machinery, and show a clear before/after.

This rewrites the persisted day layout and can touch `log/`, so take the
writer lease first — `mc state --claim "travel reshuffle"` — and
`mc state --save "travel reshuffle DD-MM"` once the new layout is agreed.
Refusals mean the same three things as in `/daily` step 0.

For each affected week:

1. Load `plan/plan.lock.json` for the week(s) in question and the adjacent
   weeks (their long-run placement matters for B3/B4).
2. Apply B5's **strict priority order** — never skip ahead:
   1. Move the long run within its own week (B1: any day, preferably
      Sat/Sun; B2: ≥48h from any quality session; B3: consecutive long runs
      must stay 5-10 calendar days apart — this is exactly where the
      Sunday→Monday stacking trap happens, check it explicitly).
   2. Split 60/40, same day, ≤6h apart — max twice in the whole plan, never
      for the 18mi or 20mi weeks.
   3. Swap with an adjacent week's *shorter* long run — never carry the
      longer one forward into a peak week.
   4. Reduce, max 25%, requires a reason code, forbidden for the 18mi/20mi
      weeks.
3. Check B6 (no long run within 24h of a flight over 4h) and B8 (max 5
   consecutive running days, at most once per 4-week block) against the new
   dates.
4. Run `mc check` against the resulting week(s) — if it still fails, do not
   present it with a caveat. Go back and try the next priority tier.

**Show a before/after table** (planned vs. shuffled) and **state which rule
drove each decision** — e.g. "moved Sunday's long run to Wednesday: B2 (48h
from Saturday's pace run) plus B6 (24h from Thursday's flight)."

This requires an explicit reason code (closed set: `TRAVEL RACE ILLNESS
INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS OVERRIDE`) logged for any
day that ends up different from the locked plan — `TRAVEL` almost certainly,
unless something else is really going on. A2 (compliance floor) still binds
even during ad-hoc travel; this isn't a free pass, it's a shuffle.
