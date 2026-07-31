# data/

This directory is where `mc sync` writes everything it pulls from Garmin
Connect and intervals.icu: raw API responses under `raw/garmin/` and
`raw/intervals/`, the reconciled `sync_report.json`, cached auth tokens
under `.garmin_tokens/`, the markdown digests under `digest/`, and small
state files (`pushed.json`, `strength_schedule.json`).

All of it is real personal training and health data once you run this
against your own account — heart rate, sleep, body weight, precise
activity timestamps — so this whole directory (aside from this file) is
gitignored and never committed.

See `examples/data/` for a small fabricated sample showing the shape of
these files without any real data in them.
