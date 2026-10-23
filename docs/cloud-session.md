# Running `/daily` from the phone

A runbook for the cloud environment. The goal is running the daily ritual from
an iPhone with the Mac powered off for days at a time — the Italy block
(arrival **10-09**) is what this exists for.

## Why this works at all

Everything except `mc sync` is pure computation over files already in this
repo. `digest`, `check`, `weather`, `strength`, `fuel`, `layout`, `render`,
`drift` and the whole `/daily` conversation need no network. So the only real
question was ever *where sync runs*, and the answer is: **in the session**,
against intervals.icu.

That is possible because intervals.icu is a complete substitute for Garmin
here (see `CLAUDE.md` § "Two sources, one shape"), and its credential is an
API key designed to be handed to third-party tools — scoped, revocable on its
own, unable to reach back into Garmin. The Garmin password never leaves the
laptop.

## Environment configuration

Create a cloud environment at claude.ai pointed at **this repo**
(`marathon-2026-state`).

### Network access: Custom

| Host | Why |
|---|---|
| `intervals.icu` | activities, wellness, per-sample streams — the whole data layer |
| `api.open-meteo.com` | `mc weather` |
| `github.com` | clone, fetch, push |
| `pypi.org`, `files.pythonhosted.org` | `uv sync` |
| `astral.sh` | the `uv` installer in the setup script |

**No Garmin hosts.** This is deliberate and worth keeping: the session is then
*structurally* incapable of reaching Garmin, so the credential question cannot
be reopened by accident. `mc sync` will report the Garmin source as failed and
carry on with intervals — which is the designed behaviour, not a degradation
to work around.

### Environment variables

```
INTERVALS_API_KEY=<from intervals.icu Settings>
INTERVALS_ATHLETE_ID=iXXXXXX
```

There is **no Environments page and no direct URL** — the environment selector
is the cloud icon showing the environment's name, in the row *above the message
box* at claude.ai/code. Editing an existing environment means hovering it and
taking the gear that appears, which is a hover target and therefore awkward from
a phone; **Add cloud environment** is a plain button if the gear won't reveal on
touch. Written down because the obvious places to look for it are all wrong.

Values are copied into the session **once, at startup**. Editing them leaves
running sessions on the values they began with, so a change takes effect on the
next session, not this one.

`MC_DEVICE` is deliberately **not** in that list — it is set by the second
`SessionStart` hook instead. It is stamped on every state commit and written
into the writer lease, so "which machine wrote this day?" stays answerable from
the history alone; without it the lease reports a container hostname (`vm`) that
means nothing a week later. The hook is the better home for it because
`.claude/settings.json` is committed and the **Mac loads the same file** — so it
guards on `CLAUDE_CODE_REMOTE`, which only cloud sessions set, and the laptop
keeps its own identity. Setting `MC_DEVICE=phone` in the environment variables
would work too; putting it in the settings file *unguarded* would rename the Mac
as well, which defeats the entire point.

It is written as an `if` rather than the shorter `[ -n "$X" ] && echo ...`
because the `&&` form **exits 1 when the guard is false** — i.e. on every Mac
session — and this hook has no `|| true` by design (see below). A hook that
reports failure every local session is a warning you learn to ignore.

Do **not** set `GARMIN_EMAIL` / `GARMIN_PASSWORD` here. Do **not** set
`MC_STATE_DIR` — since the merge, `STATE_ROOT == PROJECT_ROOT` and setting it
would point at the directory it already is.

Optional: `MC_TEMP_UNIT=celsius` for the Italy block.

### Setup script

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh || true
```

`|| true` because a non-zero exit stops the session starting, and this script
is cached for roughly a week — nothing that must be fresh belongs in it.

Dependency installation is **not** here. It lives in a `SessionStart` hook
(`.claude/settings.json`) running `uv sync`, because hooks run every session
while the setup script only runs on a cache miss. That hook deliberately has
no `|| true`: if `uv sync` fails, nothing works, and it should say so loudly
rather than leaving you to discover it three commands later.

A further `SessionStart` hook sets `MC_DEVICE=phone`, by appending it to
`$CLAUDE_ENV_FILE` (the documented way to persist an environment variable into
the rest of the session). Each hook is its own entry rather than another clause
on the `uv sync` line, so none can affect another's exit status. It also guards
on `CLAUDE_ENV_FILE` being set: absent it, the redirect would be the thing that
fails, and the cost of doing nothing is only that the lease falls back to the
hostname — visible in `mc state` output, not silent.

### Git identity

The same hook sets `user.name` / `user.email`. It is in the repo rather than
in the environment's UI so it travels — any new machine or rebuilt
environment gets it with no manual step, and there is one place to change it.

The email has nothing to do with permission to push (that is the GitHub
integration's token). It decides **attribution**: commits are linked to the
GitHub account only when the address is one registered there. The first
verification run, before this hook existed, produced commits authored by
`test <test@test.com>` and `mc verification` — harmless for a probe, wrong for
a training record you will read back in October.

Note the limit: this sets the *author*. A cloud session may still stamp its
own **committer** identity, which is not something the repo can override. The
attribution that actually matters here is `mc state --save`'s `Device: <id>`
trailer, which is why `MC_DEVICE` is set — see above.

## First run

1. Start a session and confirm the hooks ran: `uv run mc --help` should work,
   and `mc state` should name the device `phone` rather than a container
   hostname.
2. `git push -u origin <branch>` once, so the lease in the next step can
   actually push. See the lease notes below for why this is not optional.
3. `uv run mc state --claim "daily DD-MM"`.
4. `uv run mc sync` — expect Garmin `ok: false` (no network route, by design)
   and intervals `ok: true`.
5. `/daily`.
6. Confirm from the Mac afterwards that the committed log row matches what the
   phone wrote.

## Two things verified 13-08-2026, before relying on it

**Can the session push to `main`? Yes.** Tested by committing to `main`,
pushing, then reverting and pushing the revert. Nothing refused it — the branch
is unprotected and carries only my own commits. So `/daily` from the phone does
**not** gain a "merge the branch from GitHub mobile" step, which was the thing
worth knowing before Italy rather than during.

**Does the writer lease push? Not on a fresh branch — and the failure is
git-local, not the proxy.** `mc state --claim` commits `writer.json` and then
runs `git push --quiet`, which aborts on a branch with no upstream:

```
Lease claimed locally but NOT pushed — the other device cannot see it, so it is
not protecting you right now (upstream, see 'push.autoSetupRemote' ...).
```

The warning is doing its job — it says so out loud, and an unpushed lease is
invisible to the other device and protecting nothing. But the cause is
cosmetic: one `git push -u origin <branch>` sets the tracking and every later
push works, network and proxy being fine throughout. **Do that once at the top
of a session**, before the first `--claim`, or the day's first lease is a
no-op. The behind-check and git's refusal to merge remain the real backstop.

## What the phone cannot do

- **`mc push`** — needs Garmin `workoutId` / `workoutScheduleId`. Mac only,
  and still opt-in there.
- **Body Battery, training status, VO2max, race predictions, lactate
  threshold** — Garmin-only. They appear when the Mac has synced recently and
  are absent otherwise. **No §6 rule reads any of them**; C2 uses
  HRV/sleep/RHR/self-report directly, all of which intervals supplies.
- **A stale-data rescue.** If intervals.icu is down or its own Garmin
  integration has broken, the digest goes stale and `stale_gt_36h` fires. That
  warning is the safety net, and `/daily` step 1 already requires it in bold.
  Do not present an adaptation as data-driven when the data did not arrive.
- **Run at the same time as the Mac.** See below — this is unresolved, not
  merely discouraged.

## Concurrency is UNRESOLVED — one device per day until it isn't

**Operating rule today: the phone only when the Mac is off.** Not a
preference. The writer lease narrows the window between two devices; it does
not close it, and on a fresh branch the day's *first* `mc state --claim` does
not push at all, so it protects nothing until `git push -u origin <branch>`
has run.

The once-per-day gate added 14-08-2026 (`mc state --claim "daily …"` refuses
when `out/today.md` already names today) fixes the **sequential** half of this:
phone runs `/daily`, saves, Mac pulls, Mac's `/daily` stops. It does nothing for
the simultaneous half — both devices claiming before either has written today.md
see no output to refuse against, exactly like the lease. Same limit, same
backstop, so the operating rule above is unchanged.

The failure that matters is silent. `log/training-log.md`,
`data/strength_schedule.json` and `data/pushed.json` are rewritten whole, so
two devices writing the same day yields a clean-looking file with one side
gone rather than a conflict git can refuse — and a lost key in `pushed.json`
makes the next `mc push` create a **duplicate** Garmin workout. On 13-08 a
cloud session overwrote `data/sync_report.json` from an unleased `mc sync`,
caught only by reading the diff before committing.

The rules to replace this are the urgent item at the top of `TODO.md`.

## Usage

On **Pro**, a daily cloud session competes with development work for the same
limits. If `/daily` starts getting squeezed, the cheapest relief is a routine
doing the sync half early so the interactive session does less — not a second
subscription.
