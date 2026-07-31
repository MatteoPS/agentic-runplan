# Cross-training equivalence — research notes

Researched 28-07-2026, build-order step 5 (§4). Written before `equivalence.py`
exists (that's step 8) — this is the evidence base that engine will implement
against. Every claim below is tagged:

- **[EVIDENCE]** — directly supported by a cited study or meta-analysis.
- **[CONVENTION]** — established coaching/practitioner practice, not a specific
  controlled study measuring this exact number.
- **[INFERENCE]** — my own reasoning, extending established physiology to this
  specific question. Flagged because §0 of the spec explicitly requires this:
  *"When you're unsure about training science, say so and cite a source or
  ask. Do not invent physiology."*

Bottom line up front: **the spec's starting-position numbers hold up well.**
Nothing in the research contradicts them. The main correction is to the *35%
non-running cap* — it's more defensible as a conservative inference than as an
evidence-based number, which matters for how confidently `equivalence.py`
should present it later.

---

## 1. Matching method: time at matched effort/HR, never machine distance

**[EVIDENCE]** Every controlled study found below defines cross-training
equivalence by matched physiological markers (VO2, heart rate, perceived
exertion) — never by the machine's own distance readout. That's not a
convention layered on top of the research; it's the only way the research
itself defines "equivalent." Elliptical/bike distance counters use
manufacturer-specific, uncalibrated formulas with no standardized relationship
to ground-truth running distance — the spec's instruction to ignore them
entirely is correct and is really just restating how the underlying studies
work.

## 2. Elliptical

**[EVIDENCE]** [Melton, Wodicka & Bassett, "Comparison of Physiological
Variables Between the Elliptical Bicycle and Run Training in Experienced
Runners"](https://pubmed.ncbi.nlm.nih.gov/26950347/) — 12 experienced runners,
randomized crossover, two 4-week training blocks (elliptical-only vs.
run-only). Result: **no statistically significant difference** between the two
training methods for VO2max, ventilatory threshold, respiratory compensation
point, running economy, or 5,000m time-trial performance (all p > 0.05). Their
conclusion: elliptical training "can be an effective cross-training method to
maintain and improve certain physiological and performance variables in
experienced runners over a 4-week period."

This is a genuinely strong result — a *null difference* between elliptical-only
and run-only training in trained runners — but it's important to be precise
about what it does and doesn't establish: it's a 12-person, 4-week study
measuring whether swapping training methods entirely changes outcomes, not a
study that produces a specific "X% aerobic transfer per minute" number. It
doesn't measure a percentage at all.

**[CONVENTION]** The spec's **85–95% aerobic transfer per minute at matched
HR** figure isn't something I found stated as a precise number in any single
study — it's a commonly-used coaching heuristic, and it's *consistent with*
(not contradicted by) the null-difference finding above. I'm endorsing the
range as-is: I found nothing suggesting it should move up or down, and the
strongest available evidence (the null-difference study) is at least as
favorable to elliptical as this range implies.

**[INFERENCE]** Near-zero transfer for impact tolerance, tendon stiffness, and
eccentric loading — see §5 (Impact/tendon specificity) below. This is
physiologically well-grounded but not elliptical-specific research; it follows
from the general specificity principle, not a study measuring elliptical
impact transfer directly (unsurprising — there's no meaningful impact to
measure on a machine with continuous ground contact).

## 3. Stationary bike

**[EVIDENCE]** [Cross-training between running and cycling: effects on VO2max
and running performance — a systematic review and meta-analysis (Frontiers in
Sports and Active Living,
2026)](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2026.1843803/full)
— 7 randomized controlled trials (1974–2003). No statistically significant
difference in VO2max (treadmill-measured, Hedges' g = −0.32, 95% CI [−0.76,
0.13]) or running race performance (1 mile/3,000m/5,000m, Hedges' g = 0.02,
95% CI [−0.62, 0.66]) between running-only and cycling-only training. Across
the included studies, **20–50% of weekly running sessions were replaced by
cycling** with no detected decline. The authors are appropriately careful in
their own framing: this is "an absence of detected performance decline," not
proof of true equivalence — small, dated study pool, wide confidence
intervals.

**[CONVENTION]** A separate load-quantification convention (TSS/Critical
Power framing, not a peer-reviewed study — see [Fellrnr's TRIMP/TSS
reference](https://fellrnr.com/wiki/TRIMP)) holds that **45 minutes of running
at threshold effort scores the same training load (100 points) as 60 minutes
of cycling at the equivalent relative intensity** — i.e. cycling is credited
at roughly 75% of running's load per minute at matched effort, specifically
because running carries greater eccentric/impact demand than cycling.

These two sources are answering different questions and shouldn't be
conflated: the meta-analysis says cycling can replace a large share of
*weekly volume* without measurably hurting aerobic fitness; the TSS convention
says cycling still costs meaningfully less *per minute* at matched effort. The
spec's **70–85% aerobic transfer per minute** sits comfortably between what
these two framings would each suggest, and I'm endorsing it.

**[EVIDENCE]** [RunningPhysio (Tom Goom, physiotherapist), "Cross-training
during injury"](https://www.running-physio.com/cross-training-2/) —
specifically recommends cycling as a substitute for tendinopathy, plantar
fasciitis, and MTSS (shin splint) rehab, precisely *because* it's low-impact.
Also flags a specific caution not in the spec: **cycling can aggravate ITBS**
(iliotibial band syndrome) — "a common complaint in cyclists." Worth carrying
into `equivalence.py`'s substitution logic as a caveat, not a blanket
endorsement, if ITB symptoms are ever reported.

## 4. Treadmill

100% — it is running, same movement pattern, same impact, same eccentric
loading. This doesn't need a citation; it's not a transfer question. The
45-minute limit is my own logistical/comfort constraint from the
athlete profile, not a research finding — noted here only so it isn't mistaken
for one later.

## 5. Long runs — no substitute exists

**[INFERENCE]** No single study directly tests "is there a substitute for the
long run" — this is a reasoned extension of two things that *are* established:
(1) Higdon's own stated physiological rationale, which the spec already
quotes almost verbatim — benefit "kicks in around 90–120 minutes, no matter
how fast you run" — implies the stimulus is inherently about *sustained
duration under real running mechanics*, not an aerobic dose that could be
delivered another way; (2) the impact/tendon specificity argument in §6 below
means even a duration-matched cross-training session wouldn't replicate the
musculoskeletal fatigue-resistance and fueling-practice components that are
specifically what long runs train. Endorsing the spec's position as-is — I
found nothing in the literature suggesting otherwise, and nothing that would.

## 6. Impact/tendon/bone specificity — why cross-training can't replace durability work

**[EVIDENCE]** Wolff's Law and mechanotransduction are well-established,
uncontroversial physiology (see
[Physiopedia](https://www.physio-pedia.com/Wolff's_Law) for an accessible
summary): bone adapts to the *cyclic mechanical loading* it actually
experiences, and "only cyclic loading can induce bone formation." Tibial peak
stress during running is more than 3x that of walking, and non-impact
modalities (cycling, elliptical) don't reproduce that loading pattern at all.

**[EVIDENCE]** [ScienceForSport, "Stretch-Shortening Cycle
(SSC)"](https://www.scienceforsport.com/stretch-shortening-cycle/) and
associated tendon-stiffness literature: SSC-specific training (plyometrics,
running's own footstrike-and-toe-off cycle) produces tendon stiffness
adaptations tied specifically to that loading pattern. A key limitation noted
across this literature: "it is very difficult to match different training
regimes to make them comparable" — meaning researchers themselves haven't
cleanly quantified *how much* SSC-specific adaptation is lost under
cross-training substitution. The direction of the effect (impact-specific
training produces impact-specific adaptation) is well-supported; a precise
transfer percentage for elliptical/bike specifically is not available and I
did not find one.

**Net:** "near-zero transfer for impact tolerance, tendon stiffness, and
eccentric loading" is a well-grounded **[INFERENCE]** from solid underlying
physiology, correctly stated as near-zero rather than a specific measured
number — because no study measures that number directly. This is exactly the
kind of claim §0 asks to be flagged rather than presented as settled evidence.

## 7. The 35% non-running aerobic load cap (rule A8)

**[INFERENCE / CONVENTION]**, not **[EVIDENCE]** — this is the one place I'd
adjust the *label*, not the number itself. I could not find a study
establishing 35% (or any specific percentage) as the threshold beyond which
durability-specific adaptation degrades. The closest data point is the
opposite direction: the cycling meta-analysis (§3) found no *aerobic fitness*
decline up to 50% substitution — but that study measures VO2max/race
performance, not durability/injury-resistance, which is the actual stated
rationale for A8. Those are different outcomes, and nothing I found measures
the second one directly.

**I'm not challenging the 35% cap** — durability preservation is a real,
physiologically-grounded concern (§6) even where I can't cite a study pinning
the exact number, and given the athlete's actual injury history (shin
splints, hamstring tendinopathy), a protective, somewhat conservative cap is
the right default in the absence of precise data. But `equivalence.py` and any
future documentation should present 35% as *"a reasoned, conservative
convention given the injury history — not a number derived from a specific
study,"* not as a settled research finding. Overstating its evidentiary basis
would violate §0's "do not invent physiology" instruction just as much as
picking the wrong number would.

## 8. Load quantification: TRIMP, rTSS, session-RPE

Relevant to how `equivalence.py` (step 8) should actually *compute* the
substitution percentages shown in `mc equiv`, rather than using one fixed
universal number per modality.

**[EVIDENCE]** Three established methods, all matching effort/duration rather
than distance (consistent with §1):

- **Session-RPE** — [Foster, "Monitoring training in athletes with reference
  to overtraining syndrome," *Medicine & Science in Sports & Exercise* 30
  (1998): 1164–1168](https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/); Foster
  et al., "A new approach to monitoring exercise training" (2001). Formula:
  `session RPE (0–10 Borg CR10) × duration in minutes`. No equipment needed,
  introduces subjectivity, but Foster's work established it correlates well
  with HR-based TRIMP.
- **TRIMP (Banister)** — HR-based, exponentially weights higher intensity:
  `TRIMPexp = duration × HRR-fraction × 0.64^(HRR-fraction × 1.92)` (men;
  1.67 for women), where HRR = heart rate reserve fraction. See [Fellrnr's
  worked example](https://fellrnr.com/wiki/TRIMP).
- **rTSS (running Training Stress Score)** — pace/power-based equivalent,
  calibrated so "100 points = one hour at lactate threshold."

**[EVIDENCE]** A comparison study ([PubMed
24104194](https://pubmed.ncbi.nlm.nih.gov/24104194/)) found modelled vs.
actual training-response correlations of r = 0.70 (rTSS), r = 0.60
(session-RPE), r = 0.65 (TRIMP) — moderate, method-dependent, and explicitly
**not interchangeable**: "differences in TL quantification between original
and alternative methods underline that they are not interchangeable."

**Design implication for `equivalence.py`** (step 8, not built yet): rather
than a single fixed "elliptical = 88%" constant, the engine could compute a
session-specific TRIMP (or session-RPE) for the proposed cross-training
session and compare it against the TRIMP the *displaced run* would have
produced at the same duration and matched HR/effort — giving a number
grounded in the athlete's own actual physiology that day, with the fixed
modality ranges above (85–95% elliptical, 70–85% bike) as sanity-check bounds
rather than the sole source of truth. Flagging this now so it isn't lost by
step 8.

---

## Summary vs. the spec's starting position

| Claim | Spec's number | Verdict | Basis |
|---|---|---|---|
| Match by time/HR, not distance | — | **Endorsed** | [EVIDENCE] — how the underlying studies define equivalence |
| Elliptical aerobic transfer | 85–95%/min | **Endorsed** | [CONVENTION], consistent with [EVIDENCE] null-difference study |
| Elliptical impact/tendon transfer | ~0% | **Endorsed** | [INFERENCE] from established specificity physiology |
| Bike aerobic transfer | 70–85%/min | **Endorsed** | [CONVENTION], triangulated between two [EVIDENCE] sources |
| Bike ITBS caution | *(not in spec)* | **New addition** | [EVIDENCE], RunningPhysio |
| Treadmill | 100%, <45min | **Endorsed** | Definitional; 45min is my own constraint |
| Long run — no substitute | — | **Endorsed** | [INFERENCE] from Higdon's own stated rationale + §6 |
| 35% non-running cap | A8 | **Endorsed, relabeled** | [INFERENCE/CONVENTION], not [EVIDENCE] — no study found pinning this number |

Nothing here changes the numbers in §4 of the spec. The research task asked me
to challenge the starting position if evidence disagreed — it doesn't. The
value of this pass is knowing *which* numbers are load-bearing research
findings versus reasoned defaults, so `equivalence.py` and the daily digest can
represent that honestly rather than presenting everything with equal, false
confidence.

## Full source list

- Melton, Wodicka & Bassett. "Comparison of Physiological Variables Between
  the Elliptical Bicycle and Run Training in Experienced Runners."
  https://pubmed.ncbi.nlm.nih.gov/26950347/
- "Cross-training between running and cycling: effects on VO2max and running
  performance — a systematic review and meta-analysis." *Frontiers in Sports
  and Active Living*, 2026.
  https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2026.1843803/full
- Goom, T. "Cross-training during injury." RunningPhysio.
  https://www.running-physio.com/cross-training-2/
- "Wolff's Law." Physiopedia. https://www.physio-pedia.com/Wolff's_Law
- "Stretch-Shortening Cycle (SSC)." ScienceForSport.
  https://www.scienceforsport.com/stretch-shortening-cycle/
- Foster, C. "Monitoring training in athletes with reference to overtraining
  syndrome." *Med Sci Sports Exerc* 30 (1998): 1164–1168.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/
- Fellrnr.com. "TRIMP" (TRIMPexp, TSS worked examples).
  https://fellrnr.com/wiki/TRIMP
- "A comparison of methods for quantifying training load: relationships
  between modelled and actual training responses."
  https://pubmed.ncbi.nlm.nih.gov/24104194/

---

## 9. Strength & mobility protocols (researched 28-07-2026, step 8)

Per §4: on cross/rest days, and any day downgraded for shin or hamstring
reasons, propose a short (10-20min) bodyweight session. All exercises below
are bodyweight-only or have a stated bodyweight variant — satisfies "no gym
during Italy → bodyweight-only variants must exist for every prescription"
by construction, not as an afterthought.

### Shin resilience (calf + tibialis anterior)

**[EVIDENCE]** [Runners Connect, shin splint calf
strengthening](https://runnersconnect.net/shin-splint-treatment-calf-strengthening/),
citing Galbraith & Lavallee (2009): conservative MTSS treatment combines
daily calf stretching, eccentric calf work, and tibialis anterior
strengthening alongside hip/core work. Runners with shin splints show ~30%
less calf endurance than healthy controls (23 vs. 33 single-leg raises).

- **Single-leg calf raises** — bodyweight. 3×15, 2-second pause at top;
  progress toward 3×20-25 without pain. Maintenance: 3×20, 3x/week.
- **Eccentric heel drops** (off a step) — bodyweight, needs a step/curb.
  Only after 25 consecutive pain-free single-leg raises — a progression
  gate, not a day-one exercise.
- **Calf stretching** — gastrocnemius (knee straight) + soleus (knee bent),
  30s × 3 each, bodyweight.

**[EVIDENCE]** [PNEUX, tibialis anterior
exercises](https://pneux.io/tibialis-anterior-exercises-for-shin-splints):

- **Tibialis raises (wall-supported)** — bodyweight. Stand ~30cm from a
  wall, lean back, lift toes/forefoot as high as possible, lower under
  control. 3×15-20; progress to a slow 3-second lowering, then add light
  resistance (band or a loaded backpack) once bodyweight is easy.
- **Heel walks** — bodyweight. Walk forward on heels only, toes lifted
  throughout. Start 30s, progress to 60-90s.

### Hip / posterior chain, hamstring-tendinopathy-safe

**[EVIDENCE]** [E3 Rehab, proximal hamstring tendinopathy
rehab](https://e3rehab.com/proximal-hamstring-tendinopathy-rehab/): the
maintenance/return-to-running stage emphasizes hip-extension work with
*minimal* hip flexion, generating power from the glutes rather than loading
the hamstring at end-range — exactly the "avoid loaded deep hip flexion"
constraint from the athlete profile.

- **Double-leg glute bridge** — bodyweight. 3×15. Minimal hip flexion.
- **Single-leg glute bridge** — bodyweight. 3×15/side. Minimal hip flexion.
- **Single-leg balance** — bodyweight, 30-60s/side. General
  lumbopelvic/proprioceptive control, no hip-flexion loading at all.

**Deliberately excluded from this list**: RDL/deadlift variations, Roman
chair hip extensions, and long-lever bridges — E3 Rehab's own source
categorizes these as "moderate to significant" hip flexion, which the
athlete profile explicitly flags as the aggravator (deep RDLs, good
mornings at end range). Higher-hip-flexion work is real rehab territory
once symptomatic, not appropriate for an unsupervised daily-session
generator to prescribe. **[INFERENCE]**: given this is maintenance for a
*resolved* injury, not active rehab, staying conservative (bridges only,
skip anything E3 Rehab itself flags as higher hip-flexion) is the right
default — the durability upside of the excluded exercises isn't worth
second-guessing a physio's staging without one actually assessing me.

### Mobility

**[CONVENTION]** No single controlled study backs a specific mobility
routine here — this is standard practitioner practice (dynamic mobility
pre-run, static stretching separate from strength work), included for
completeness per §4's explicit ask, not because the evidence is as strong
as the strength protocols above.

- Hip circles / leg swings (dynamic, bodyweight)
- Calf stretch (see above — does double duty for shin resilience)
- Ankle circles / dorsiflexion rocks (bodyweight)

### Sources

- Runners Connect, shin splint calf strengthening (citing Galbraith &
  Lavallee 2009): https://runnersconnect.net/shin-splint-treatment-calf-strengthening/
- PNEUX, tibialis anterior exercises: https://pneux.io/tibialis-anterior-exercises-for-shin-splints
- E3 Rehab, proximal hamstring tendinopathy rehab: https://e3rehab.com/proximal-hamstring-tendinopathy-rehab/
