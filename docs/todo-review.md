# TODO review — feasibility vs. importance

Assessed 02-08-2026 against the code as it stands (`src/mc/*.py`,
`.claude/commands/*.md`). Effort figures are lines-of-real-work + tests, not
calendar time.

## Verdict table

| # | Item | Effort | Importance | Do it? |
|---|---|---|---|---|
| 1 | Single HR slot (drop warmup/cooldown when target is constant) | XS (~15 lines) | Medium | **Yes, now** |
| 2 | Persist the week's day layout (*not currently on the list*) | S–M (~80 lines) | **High** | **Yes, first** |
| 3 | `/tomorrow` (or `/plan`) | M (~150 lines, on top of #2) | High | **Yes, after #2** |
| 4 | Auto-send `out/` to phone | S (~30 lines + one-time setup) | Medium-high | Yes — iCloud folder, not Keep/Notes |
| 5 | Push elliptical as "elliptical" | — | Low | **No — not possible.** See below |
| 6 | PC GUI | L (weeks) | Low-medium | Not yet — #3+#4 removes most of the pain |
| 7 | Run on phone (iOS app + sync) | XL | Low | No. Wrong shape for the problem |
| 8 | Apple Health integration | M | Low | Agree — skip |

---

## 1. Single HR slot when the target is constant — *do it*

**Where:** `src/mc/push.py:140` (`build_workout`, steps at 146-152). It unconditionally emits
warmup(300s) + interval + cooldown(300s), and passes the *same* `_hr_zone_target`
to all three. So the watch nags you through three phases that are identical.

**Fix:** if the three steps would share one target, emit a single
`StepType.INTERVAL` step of the full duration. Ten to fifteen lines, one branch.
Keep the split for `pace` sessions, where warmup/cooldown genuinely differ — and
that's the one design question worth deciding: today *nothing* differentiates
them, so the honest fix is "always one step until pace sessions get real
warmup/cooldown targets."

**Risk:** near zero. `--dry-run` prints the payload; `tests/test_push.py`
already asserts on step structure, so expect to update a couple of assertions.

**Importance:** medium. It's cosmetic-on-the-watch, but it's cosmetic on the
thing you look at mid-run, and it's the cheapest item on the list.

## 2. Persist the week's day layout — *the missing keystone, add this to the list*

Not in your TODO, but it blocks two things that are.

`plan.lock.json` holds weekly aggregates only — day-of-week is decided
conversationally in `/week` step 5 and then **thrown away**. The one place it
almost survives is `strength.set_fixed_days(week_start, day_miles, long_run_day)`
(`src/mc/strength.py:59`), which receives the full `day_miles` layout and
persists only the two strength days from it. `data/strength_schedule.json` today:

```json
{ "27-07": { "moved": {"30-07": "01-08"}, "status": {"01-08": "done", "29-07": "done"} } }
```

The layout that produced those picks is gone.

**Consequence:** the system structurally cannot answer "what is Thursday?"
That's why #3 doesn't exist, and why multi-day push doesn't actually work:
`mc push --date` parses `out/today.md` and `_check_today_md_date`
(`push.py:419`) hard-fails unless the file's header date matches the requested
day. So `.claude/commands/push.md` advertising "I will say how many days ahead"
is, in practice, always a refusal for any day but today. Worth knowing
independently of the rest of this.

**Fix:** `data/week_layout.json`, keyed by `week_start` like the strength state
— `{day: {miles, session_type}}` plus `long_run_day` — written by `/week` step 5
(natural fit: extend the existing `mc strength --set-days` call, or a sibling
`mc layout --set`), read by everything else. Rewritable within the week under
C1 with a reason code, same as any other reshuffle.

**Importance: high**, because it converts three separate features into one
small shared dependency.

## 3. `/tomorrow` / `/plan` — *yes, once #2 exists*

**Effort:** medium, and mostly writing, not code. With #2 in place: a
`mc tomorrow`-ish read of the layout + `plan.lock.json` + the latest digest, an
`out/tomorrow.md` from the same renderer, and a slash command that is a
deliberately thinner `/daily` — no questions, no logging, no `mc propose`.

**The one real design decision:** tomorrow's session must be **provisional**.
`/daily` exists because the prescription depends on feel, sleep, shins and the
forecast, none of which you have yet. If `/tomorrow` writes anything that looks
final it will quietly become the plan and hollow out the daily check. Concretely:
mark it "provisional — confirmed by tomorrow's `/daily`", do **not** append to
`log/training-log.md`, and don't let `mc push` consume `out/tomorrow.md` without
you saying so.

**Importance:** high, and higher than its position in your list suggests — a
one-day horizon is the system's biggest practical gap. Knowing Thursday is 10mi
is what lets you move a dinner, not just react to it. A 7-day read-only view
(`/week` already computes it) may be worth more than a 1-day one; consider
`/plan [n]` defaulting to 3.

## 4. Auto-send `out/` to the phone — *yes, and simpler than you think*

Don't use Google Keep or Apple Notes. Both mean an API/automation layer for
what is fundamentally file sync, and both mangle HTML.

**Cheapest path that works:** write `out/` (or a copy of `today.html` +
`dashboard.html`) into `~/Library/Mobile Documents/com~apple~CloudDocs/marathon/`
at the end of `mc render --all`. iCloud Drive syncs it; the Files app opens the
HTML; a Shortcut or a home-screen bookmark gets you one tap. ~30 lines and a
config path, zero credentials, no new dependency. `render.write_dashboard`
(`render.py:294`) and `render_all` are the single choke point to hook.

**Importance:** medium-high — small, daily, removes friction from the one
artifact you actually consume away from the laptop. Do it right after #1.

## 5. Push elliptical as "elliptical" — *not possible; close it*

I checked the library's sport-type enum directly:

```
RUNNING=1  CYCLING=2  OTHER=3  SWIMMING=4  STRENGTH_TRAINING=5
CARDIO_TRAINING=6  YOGA=7  PILATES=8  HIIT=9  MULTI_SPORT=10  MOBILITY=11
```

These come from Garmin's own `/workout-service/workout/types`. **There is no
elliptical workout sport type.** Elliptical exists on Garmin as an *activity*
type (what the watch records when you start an Elliptical profile), not as a
workout type you can create. `push.py:113` already picks the only correct
option — `FitnessEquipmentWorkout` / `cardio_training` — and the comment there
says exactly this.

So the code isn't wrong; the request isn't available. Two consolation prizes,
both trivial: the workout name already carries `elliptical` (`push.py:165`), and
you can add it to the description so the watch shows it. On most Garmin watches
you can also start the Elliptical activity and pull up the Cardio workout —
worth testing once on your device before spending anything here.

**Recommendation:** move to "Maybe not" with the reason recorded, so it doesn't
get re-investigated in three months.

## 6. PC GUI — *not yet*

**Effort:** large, and it's not the code volume — it's that a GUI has to
re-express §6 in a second place. The rule engine's value is that it's the *only*
gate (`rules.check_week`, and `push.check_before_push` deliberately narrowing to
`_BLOCKING_RULE_IDS`). A GUI that lets you click "10mi instead of 8" needs the
same refusal logic, the same `OVERRIDE:` typing ceremony, the same reason-code
set — or it becomes the drift-shaped hole in an anti-drift system.

**Also:** the conversation *is* the interface here. The questions in `/daily` are
the input mechanism; a form with four fields loses the "weigh it, don't
auto-stop" judgement that C2 explicitly asks for.

**Importance:** low-medium. My read is that most of what you want from a GUI is
actually #3 (see ahead) and #4 (read it on the phone). Do those, then re-ask —
you may find the GUI want evaporates. If it doesn't, a *read-only* dashboard
(extend `render.build_dashboard_html`) is 90% of the value at 10% of the risk.

## 7. Run on phone / standalone iOS app — *no*

**Effort:** extra-large, and worse, it's the wrong shape. A native app calling
the Claude API would have to reimplement `mc` (sync, digest, rules, strength,
push, render — ~4,200 lines) or shell out to something that can't run on iOS.
The iCloud/Drive sync you mention is the easy half; the hard half is that the
repo *is* the state — `log/`, `context/overrides.md`, `data/`,
`plan.lock.json` — and two writers over a sync folder is a merge-conflict
generator on files whose whole purpose is being an audit trail.

**If the underlying want is "do `/daily` from the couch/hotel":** run Claude
Code against this repo from your phone via claude.ai/code or an SSH session to
the laptop. Same code, same state, no second implementation. That's a
configuration afternoon, not a project.

**Importance:** low as specified. High if reframed as remote access — which is
already solved.

## 8. Apple Health — *agree, skip*

Your own reasoning is right, and there's a second argument for skipping: the
digest and rule engine are built on Garmin's HRV/sleep/RHR shape. Mixing a
second source with different sampling would weaken exactly the readiness signals
C2 and D4 depend on, in exchange for step counts. Note that `READINESS` as a
reason code (§6 E1) *requires cited data* — a noisier second source makes that
harder to satisfy honestly, not easier.

---

## Suggested order

1. **#1 single HR slot** — an hour, immediate daily benefit.
2. **#4 iCloud auto-send** — an hour, immediate daily benefit.
3. **#2 persist week layout** — the keystone; also fixes multi-day push.
4. **#3 `/plan [n]`** — the actual feature you want, cheap once #2 lands.
5. Close **#5** as not-possible and **#7** as solved-by-remote-access.
6. Re-ask **#6** after #3 and #4 have been live for two weeks.

## One suggestion of my own

Nothing currently tells you *which of these rules keeps binding*. You have a
closed reason-code set, an override log, and a training log — but no
`mc drift`-style summary of "SHIN was cited 4 times in 3 weeks; A9 blocked 2
proposals." That's the report that would tell you whether the plan needs a
structural revision (E5) *before* you hit the 2-override tripwire. It's small
(the data is all in `log/` and `context/`), and it's more in the spirit of this
system than any GUI.
