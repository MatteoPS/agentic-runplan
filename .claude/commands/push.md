Preview and push upcoming days' workouts to Garmin Connect. `mc push` is
opt-in and never runs as part of `/daily`, `mc sync`, or anything automatic —
this command exists precisely because pushing is a separate, deliberate step.

**The day comes from `mc today`, never from your own sense of the date.** This
runs from a container on UTC, so after 20:00 Eastern both `date` and the date
you were handed at the top of the session are already tomorrow. Every `DD-MM`
you write — headers, lease purposes, log rows — comes from that one command.
It names the timezone it used; if that is not where I actually am, say so
(the fix is `MC_TZ`).

I will say how many days ahead (default: just today, if unstated), and
may specify which of the day's suggested options to push (e.g. "push the
bike one") — pass that via `--option <name>` (matches against today.md's
substitution table, e.g. "elliptical", "bike"). Since 17-08-2026 that table is
only in `out/today.md` on days it was asked for, so `--option` will report no
matching row on a day I never asked for substitutions — that refusal is
accurate, not a bug. The fix is to decide the swap in `/daily` (which writes
the table) rather than to invent an option here. Without `--option`, it pushes
whatever's on the "## Today —" line. Elliptical/bike push as their own
Garmin workout type (cardio_training / cycling), not disguised as a run.

`mc push` writes `data/pushed.json`, which is one of the whole-file rewrites —
and the one whose loss is worst, because a missing key makes the next push
create a **duplicate** Garmin workout instead of updating in place. So take
the writer lease first: `mc state --claim "push DD-MM"`, and
`mc state --save "push DD-MM"` after (or `mc state --release` if you end up
pushing nothing). Refusals mean the same three things as in `/daily` step 1.

For each day in range:

1. Confirm `out/today.md` exists and is dated for that day — if it isn't
   (e.g. pushing tomorrow before /daily has run for tomorrow), say so plainly
   rather than guessing at what the session should be. `mc push` itself will
   refuse with a clear message if the dates don't match.

   **Never push a provisional projection.** `out/tomorrow.md` from `/preview`,
   and the "Next 2 days (provisional)" section of `out/today.md`, are computed
   under assumed conditions — normal sleep, no new injury, full compliance —
   none of which have happened. `mc push` refuses anything marked provisional;
   that refusal is the safety mechanism, not an obstacle to route around. If I
   ask you to push tomorrow, the answer is "run /daily tomorrow morning first."
2. Run `mc push --date DD-MM --dry-run [--option <name>]` and show the
   **full text preview** (workout name `MC W{week} {DD-MM} {type}`, HR
   targets, and for long runs the pace ceiling note — never a hard pace
   target on the long run).
3. If `check_before_push` reports it would currently be refused (§6
   violation), say so clearly and **do not proceed to a real push** —
   explain which rule and why, same as `mc check` would.
4. Only after I have seen the preview and explicitly say to proceed,
   run `mc push --date DD-MM --yes`. Never assume `--yes` — that flag is the
   whole safety mechanism here, same spirit as `OVERRIDE:` in §6 E4.
5. Confirm the result (created vs. updated — `data/pushed.json` makes
   re-pushing idempotent, so pushing the same day twice updates in place
   rather than creating a duplicate).

`mc unpush --date DD-MM` removes a previously pushed workout — use this if
I say a day's plan changed after it was already pushed, rather than
leaving a stale workout on the calendar.

This command writes to my real Garmin Connect account. Treat it with
the same care as any action that's hard to reverse cleanly — when in doubt,
show the dry-run preview and ask, don't assume.
