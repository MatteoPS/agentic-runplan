# Marathon 2026 — compressed 14-week plan

**Race: NYC Marathon, Sun 01-11-2026. Base: Hal Higdon Intermediate 1,
compressed 18→14 weeks, shin-adapted, Italy travel block built in.**
Units: miles and min/mile throughout.

This is the human-readable plan. `plan.lock.json` (written only after
approval) is the immutable machine target this plan is built from — any
command that would change it must refuse and require an explicit `OVERRIDE:`.

## How this was built

- **§5 Step 1-2 (research + current fitness)**: Higdon's own long-run-to-volume
  ratio runs 33–50% across all 18 of his weeks (computed directly from his
  table) against a commonly-cited 25–30% coaching guideline — confirmed via
  real sources, not assumed. Current fitness computed from 60 days of real
  synced Garmin data, not estimated: best-demonstrated week 24.5mi (w/c
  13-07, including an 11.1mi long run), easy pace ~9:23-9:48/mi at HR 140-145
  (N=22 runs, R²=0.77).
- **§4 (cross-training equivalence)**: researched and written to
  `context/equivalence.md` — elliptical 85-95%, bike 70-85% aerobic transfer
  per minute at matched HR/effort (both consistent with real studies), near-
  zero impact/tendon transfer for either. The 35% non-running cap (A8) is a
  reasoned convention, not a number pinned by a specific study.
- **Speedwork**: this plan stays strictly speedwork-free, as Higdon's own
  Intermediate 1 design intends. Strides (short relaxed accelerations) are
  the one approved light addition — see the memory of that discussion for
  the reasoning if it needs revisiting.

## Key decisions made during compression (confirmed with me)

1. **Current-fitness gate reference: best-demonstrated week, not the noisy
   8-week average.** My organic training varies 8.6-29.7mi/week; the
   average understates real capacity. Week 1 (21mi total, 10mi long run) is
   -14% vs. the 24.5mi best week — safely under the ~15% gate.
2. **A9's ratio cap is per-week, set to what's realistically achieved, not a
   forced 0.32 everywhere.** Hitting 0.32 at an 18-20mi long run would need
   ~56-62mi/week total training — beyond safe volume for this base, and
   worse than what even Higdon's own uncompressed plan achieves (33-50%).
   Build/push weeks land at 0.35-0.42 here — a real improvement via realistic
   added cross-training, shown honestly rather than forced to an unrealistic
   number.
3. **Higdon's week-9 half marathon does not survive compression.** No slot
   fits it in the compressed structure, and the 08-08 Percy Sutton 5K already
   serves as the plan's benchmark/tune-up race per the athlete profile. Also,
   research surfaced a specific critique of that half marathon's original
   placement (immediately after a rest day, into hard running) as a minor
   recovery-principle issue — another reason to drop it, not preserve it.
4. **One 20-miler (week 11), not two.** No defensible way was found to add a
   second 20 within ~7 weeks of true build+push time (after the Italy block
   and a non-negotiable 3-week taper) without either cutting the taper or
   spacing long runs unsafely close together. Net: one 20 and one 18, instead
   of Higdon's two 20s.
5. **Week 2 gets a 5th running day**, to accommodate the 08-08 Percy Sutton
   Harlem 5K alongside that week's long run — the long run must sit ≥48h from
   the race (B2), so it moves earlier in the week rather than landing on
   Sunday right after a hard effort.

## Revision 31-07-2026: build phase brought closer to Higdon's volume

I flagged, correctly, that the original compression cut running volume
in the one part of the plan with no excuse for caution — full-control build
weeks with no travel disruption. Checked against Higdon's actual published
table: our weeks 1-7 were running 10-15% *below* Higdon's comparable weeks,
driven by a 4-day/week running budget (shin-adaptation choice) that was
never actually validated against his expectation of compensating for the
travel-block cutback with more volume elsewhere.

Research pass (31-07-2026) found the aerobic-fitness case for cross-training
substitution is solid (elliptical ~85-95% transfer, null-difference RCT
vs. run-only training) but the *durability* case is not: eccentric-damage
resistance (the repeated-bout effect) is movement-specific and doesn't
transfer from non-impact modalities, and race-performance data (Boston
Marathon, 917 runners, PMC12441744) found running sessions/week and quality
sessions/week independently predict finish time. Bone-stress-injury
literature (Warden et al.) supports ~4-5 running days/week as the
*well-adapted* frequency, not a conservative compromise. Given my
shin/hamstring history is genuinely mild (never sharp, never gait-changing)
and is now logged daily so load adjusts reactively, the 4-day cap was
over-conservative relative to both the evidence and my actual history.

**Change**: weeks 1-7 restored to Higdon's 5-running-day structure (cross on
Monday as an addition, not a replacement) and long runs lengthened beyond
Higdon's comparable weeks throughout. The 18-miler (week 6) and 20-miler
(week 11) stay exactly as locked — A3-protected regardless. Build-phase
weekly running total: 183mi → ~206mi (+13%); full-plan total: 377mi → 400mi
(+6%).

**Full parity with Higdon's 588mi total was considered and rejected as
unsafe** — closing that gap entirely would require ~55mi/week averages in
early build weeks, more than double the current best-demonstrated organic
week (24.5mi), which is not a safe progression from this fitness base in a
14-week compressed plan. The remaining ~188mi shortfall is structural: 4
fewer weeks than Higdon's 18, one 20-miler instead of two, and real
Italy-travel volume loss that this plan deliberately doesn't claw back
elsewhere. Long-run length in build/pre_travel is flagged as an open item —
I want it reassessed further, but the plan revisits that with real
shin-log data from the first 2-3 weeks of the new 5-day structure rather
than front-loading more now.

## The plan

| Week | Long run | Run mi | Run days | Cross | LR ratio | Block |
|---|---|---|---|---|---|---|
| Week 1 · w/c 27-07 | 11 mi | 25 mi | 5 | 45 min | 0.38 | build |
| Week 2 · w/c 03-08 | 12 mi | 25 mi | 5 | 60 min | 0.39 | build — 5K race week |
| Week 3 · w/c 10-08 | 9 mi *(stepback)* | 22 mi | 5 | 45 min | 0.34 | build |
| Week 4 · w/c 17-08 | 13 mi | 30 mi | 5 | 45 min | 0.38 | build |
| Week 5 · w/c 24-08 | 16 mi | 34 mi | 5 | 60 min | 0.40 | build |
| Week 6 · w/c 31-08 | **18 mi (A3)** | 42 mi | 5 | 90 min | 0.36 | build — peak before travel |
| Week 7 · w/c 07-09 | 15 mi | 28 mi | 5 | 30 min | 0.49 | pre_travel — taper into flight (depart Thu 10-09) |
| Week 8 · w/c 14-09 | 12 mi *(opportunistic, 10-14 target)* | 19 mi | 3 | 0 min | 0.63 | travel_italy — first 3 days easy only |
| Week 9 · w/c 21-09 | 14 mi *(opportunistic, 10-14 target)* | 24 mi | 4 | 0 min | 0.58 | travel_italy |
| Week 10 · w/c 28-09 | 14 mi | 21 mi | 3 | 60 min | 0.53 | return — first 3 days easy (jetlag), return Wed 30-09 |
| Week 11 · w/c 05-10 | **20 mi (A3)** | 46 mi | 5 | 60 min | 0.39 | push — exactly 3 weeks out |
| Week 12 · w/c 12-10 | 12 mi | 28 mi | 4 | 0 min | 0.43 | taper — Higdon wk16 verbatim |
| Week 13 · w/c 19-10 | 8 mi | 21 mi | 4 | 0 min | 0.38 | taper — Higdon wk17 verbatim |
| Week 14 · w/c 26-10 | **Marathon** | 35.2 mi | 4 | 0 min | 0.74 | taper — race week, Higdon wk18 verbatim |

Cross-training is elliptical/bike (gym access every day in NYC per the
athlete profile), matched by time at effort/HR per §4 — never by machine
distance. Monday is always a cross/rest day per Higdon's own design; the
weekly cross-training minutes shown above are an *addition* on top of a
5-day running week in weeks 1-7 (revised 31-07-2026 — originally a 4-day
running budget with cross as a partial replacement; see the revision note
above for why that changed), not a substitute for running days.

Day-of-week placement above is illustrative, not frozen — B1 explicitly
allows the long run to move within its own week, and the full B-rule
shuffling machinery (step 7+) handles real week-to-week adaptation. Only the
weekly aggregates in this table (and in `plan.lock.json` once written) are
locked.

## Blocks

| Block | Weeks | Compliance floor | Notes |
|---|---|---|---|
| build | 1–6 | 0.95 | full control, no travel disruption — high bar (raised from 0.90 at my request) |
| pre_travel | 7 | 0.90 | full control minus the Thursday flight day itself (raised from 0.85) |
| travel_italy | 8–9 | 0.40 | opportunistic long run, no quality, no gym — explicitly not relying on the long run happening (lowered from 0.55 at my request) |
| return | 10 | 0.55 | jetlag/rebuild, gym access resumes (lowered from 0.70) |
| push | 11 | 0.95 | |
| taper | 12–14 | 1.00 (frozen) | no additions, no substitutions, no making up missed volume |

Compliance floors deliberately trade strictness for realism across the plan:
tight where I have full control (build, pre_travel), loose where travel
genuinely limits what's achievable (Italy, return) — rather than a uniform
standard that would either nag unrealistically during Italy or let slack
creep into the phases where there's no good excuse for it.

## What's still open

- Exact day-of-week layout for each week (B-rule territory, adapts to real
  conditions — not frozen).
- Pace/HR targets for specific sessions — the 08-08 5K result will anchor
  these per the athlete profile ("wait for the 08-08 5K result for
  estimation").
- Strides: added as short relaxed accelerations after easy runs per the
  research in step 4; exact frequency/placement is a daily-adaptation detail,
  not a locked weekly target.
