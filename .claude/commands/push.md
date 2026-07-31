Preview and push upcoming days' workouts to Garmin Connect. `mc push` is
opt-in and never runs as part of `/daily`, `mc sync`, or anything automatic —
this command exists precisely because pushing is a separate, deliberate step.

I will say how many days ahead (default: just today, if unstated), and
may specify which of the day's suggested options to push (e.g. "push the
bike one") — pass that via `--option <name>` (matches against today.md's
substitution table, e.g. "elliptical", "bike"). Without `--option`, it pushes
whatever's on the "## Today —" line. Elliptical/bike push as their own
Garmin workout type (cardio_training / cycling), not disguised as a run.

For each day in range:

1. Confirm `out/today.md` exists and is dated for that day — if it isn't
   (e.g. pushing tomorrow before /daily has run for tomorrow), say so plainly
   rather than guessing at what the session should be. `mc push` itself will
   refuse with a clear message if the dates don't match.
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
