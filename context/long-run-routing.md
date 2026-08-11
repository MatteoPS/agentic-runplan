# Long-run routing, 15-08 → 11-10

Agreed 11-08-2026. Read by `/daily` and `/week` alongside the rest of
`context/`. This file exists because `out/today.md` is deleted by `mc tidy`
once its day passes and `log/sessions/` falls out of `/daily`'s 14-day read
window long before September — neither survives to the day it is needed.

**Scope: this fixes long-run *days*, not distances.** Distances stay frozen in
`plan/plan.lock.json`. Placement is **B1 (long run may move within its week)**
and **C1 (reorder easy runs)**, neither of which needs approval. Nothing here
overrides §6; every date below was verified against `rules.check_week` and
`rules.check_schedule`.

---

## The chain

| Date | Miles | Gap | Where |
|---|---|---|---|
| Sat 15-08 | 9 | 10 d | NY |
| Fri 21-08 | 13 | 6 d | NY — travel weekend follows |
| Fri 28-08 | 16 | 7 d | NY — travel weekend follows |
| **Thu 03-09** | **18** | 6 d | NY — **A3 (protected long runs)**, moved off Sun 06-09 |
| **Wed 09-09** | **15** | 6 d | NY — last run before the 10-09 flight |
| **Thu 17-09** | ≤12.8 | 8 d | Italy |
| **Thu 24-09** | ≤14.9 | 7 d | Italy |
| **Sat 03-10** | ≤14.6 | 9 d | NY |
| Sun 11-10 | 20 | 8 d | NY — A3 |

Every gap sits inside **B3 (long runs 5–10 days apart)**.

### Three decisions that are easy to undo by accident

**The 18 does not go back to Sunday 06-09.** A3 keeps it at 18 mi inside week 6,
but it may move day-of-week. Left on Sunday it is **3 days** from the 15 on Wed
09-09 — a hard B3 rejection. Thu 03-09 balances both gaps at 6 days. This is the
price of running the 15 in New York before the flight, and it was paid
deliberately.

**24-09, not 23-09.** 23-09 → 04-10 is 11 days, a B3 violation, so picking the
23rd would pin the return long run to Sat 03-10 with no fallback. The 24th keeps
both 03-10 and 04-10 open — worth having after a transatlantic flight.

**There is no 16-miler anywhere in Italy.** **A6 (no increases, 105% ceiling)**
caps week 8 at 19.95 mi; **A9 (long-run share of the week)** caps the long run at
64% of the week's aerobic load. That is **12.8 mi**, and a 16 would need a 25 mi
week. Week 9's ceiling is 14.9 mi, week 10's is 14.6 mi. Reaching 16 requires a
typed `OVERRIDE:` (**E4, typed OVERRIDE only**) or a structural revision to
`plan.lock.json` — never a quiet bend.

**B6 (no long run near a long flight)** clears at exactly its limit on 09-09:
one full day before the 10-09 flight. Run it in the morning.

---

## Italy: the easy runs buy the long run

In the travel block the long run is **not a fixed distance**. A9 makes it a
fraction of whatever the week actually delivers, so short easy runs earlier in
the week are what make Thursday's long run legal. A9 says so explicitly:
cross-training cannot paper over the ratio.

Two rules are switched **off** here, which is what makes a thin week survivable:

- **A1 (long run can't shrink)** — the `travel_italy` block is
  `long_run_opportunistic`, so the long run may shrink freely.
- **A10 (minimum 3 running days)** — skipped wherever the block carries
  `no_gym`, which weeks 8 and 9 do. **Two running days a week is legal in
  Italy.** (Week 10 is `return`, not `travel_italy` — A10 **is** enforced there,
  minimum 3 running days.)

### Minimum to hit the planned long runs

| Week | Long run | Minimum easy runs | Week total |
|---|---|---|---|
| 8 · w/c 14-09 | 12 mi | **2 × 3.5 mi** | 19 mi |
| 9 · w/c 21-09 | 14 mi | **2 × 5 mi** | 24 mi |
| 10 · w/c 28-09 | 14 mi | **2 × 3.5 mi** + the 60 min cross | 21 mi |

So: **three runs a week — the long one plus two easy.** Nothing more is needed.
Note week 8 has no headroom above this: 12 + 4 + 4 = 20 mi trips A6's 19.95 mi
ceiling. Keep the easy runs at 3.5 mi, not 4.

### If you can only run twice a week

Legal in weeks 8 and 9, and the long run simply shrinks:

| | 2 runs (one easy) | 3 runs (two easy) | 4 runs (three easy) |
|---|---|---|---|
| **Wk 8** easy 3 mi each | long ≤ 5.3 | ≤ 10.7 | ≤ 12.8 |
| **Wk 8** easy 4 mi each | ≤ 7.1 | ≤ 12.8 | ≤ 12.8 |
| **Wk 9** easy 4 mi each | ≤ 5.8 | ≤ 11.5 | ≤ 14.9 |
| **Wk 9** easy 5 mi each | ≤ 7.2 | ≤ 14.4 | ≤ 14.9 |
| **Wk 10** easy 3 mi each | ≤ 9.6 | ≤ 13.0 | ≤ 14.6 |
| **Wk 10** easy 4 mi each | ≤ 10.8 | ≤ 14.6 | ≤ 14.6 |

Watch one floor: week 9 with only 2 × 3 mi easy lands the week at 7.3 mi, under
its **A2 (compliance floor)** of 9.6 mi. Everything else above clears.

### What must not happen: skipping a long run

The long run may shrink to 5 miles. It may **not disappear**. B3 needs a longest
run of the week every 5–10 days, and dropping either Italy one breaks the chain
outright:

- skip week 8's → 09-09 to 24-09 is **15 days** — B3 violation
- skip week 9's → 17-09 to 03-10 is **16 days** — B3 violation

B3 does not care how far it is, only that it happened. **A 6 mi "long run" on
Thu 17-09 keeps the chain intact; nothing at all breaks it.** If a week is
collapsing, shorten the long run — never cancel it.

### Week 10's cross-training is load-bearing

The 14 on Sat 03-10 sits at 52.8% against A9's 53% cap **only because** that
week's 60 min of cross counts toward total aerobic load. Drop the cross and the
same run is **66.7% — a clear A9 failure**. It is a jetlag week, which makes the
cross session the most likely thing to be skipped. It is not optional.

---

## Downhill routing

`context/downhill.md` carries the week-by-week route plan and is unaffected by
these date moves — it changes routes, never mileage. The Italy weeks are
"opportunistic, whatever the terrain gives"; week 11's 20 on Sun 11-10 remains
the only full course-profile rehearsal, since **A4 (taper frozen)** closes the
door after it.
