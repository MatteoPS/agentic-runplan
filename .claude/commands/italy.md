Dedicated command for the known Italy trip block (weeks 8-9 in
`plan.lock.json`, `travel_italy`, 14-09 → 27-09, arrival 10-09, return 30-09).
Rebuild weeks 7-10 given whatever actually happened — this block was
pre-planned with reduced targets precisely so it doesn't need 15 repeated
overrides; use this command to reconcile reality against that plan, not to
renegotiate it from scratch each time.

1. `mc sync` then `mc week --week 7`, `--week 8`, `--week 9`, `--week 10` to
   see planned vs. actual for the whole block so far.
2. Ask me (only what isn't already in the digest): what actually
   happened with training access, sleep, and how the opportunistic long runs
   went (10-14mi target, never scheduled to a fixed day — B5 first tier is
   "move within the week," but during travel even that may not be
   realistic).
3. Rebuild the remaining weeks in the block:
   - **No gym** → every prescription needs a bodyweight-only variant. Pull
     from `equivalence.py`'s `propose_strength_mobility()` — every item
     there is already bodyweight, so this should never require inventing
     something new.
   - **Opportunistic long runs** — A1's normal "must equal plan value,
     never shrink" is relaxed here by design (`long_run_opportunistic` on
     the block). Don't manufacture pressure to hit an exact number; note
     what's realistic and move on.
   - **No quality** — the block has `no_quality: true`. Don't propose pace
     work or the tune-up-adjacent sessions regardless of how good I
     feel (A6 spirit: stick to the plan).
   - **Arrival/return sleep windows (B7)** — first 3 days after 10-09 and
     first 3 days after 30-09 are easy-only, no quality, no long run. This
     is pre-declared, not something to renegotiate per §6 B7: "Poor sleep is
     expected and pre-declared — this is not an override, it is the plan."
4. Run `mc check` on the rebuilt weeks. `travel_italy`'s compliance floor is
   intentionally low (0.40, per my explicit call in step 6) — don't
   apply build-phase (0.95) expectations here.
5. Show the rebuilt weeks 7-10 as a table (planned vs. rebuilt vs. actual so
   far), state the reasoning per week, and confirm before writing anything
   back to `log/sessions/`.

Reason code for anything logged as a deviation: `TRAVEL` (closed set:
`TRAVEL RACE ILLNESS INJURY SHIN HAMSTRING HEAT WEATHER LIFE READINESS
OVERRIDE`) — this is pre-declared travel, not an ad-hoc override, so don't
count these toward the E5 override-drift threshold unless something genuinely
unplanned happens on top of the trip itself.
