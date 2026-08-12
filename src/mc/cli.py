from __future__ import annotations

from datetime import date, datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

from mc import config as cfg
from mc import digest as digest_mod
from mc import drift as drift_mod
from mc import equivalence as eq
from mc import export as export_mod
from mc import fuel as fuel_mod
from mc import layout as layout_mod
from mc import plan as plan_mod
from mc import planning as planning_mod
from mc import push as push_mod
from mc import render as render_mod
from mc import rules as rules_mod
from mc import strength as strength_mod
from mc import state as state_mod
from mc import sync as sync_mod
from mc import tidy as tidy_mod
from mc import traininglog as tlog_mod
from mc import weather as weather_mod

app = typer.Typer(add_completion=False, help="mc — adaptive marathon training system")
console = Console()


def _parse_ddmm(s: str, year: int = 2026) -> date:
    day, month = s.split("-")
    return date(year, int(month), int(day))


def _current_week(p: plan_mod.PlanLock, as_of: date | None = None) -> plan_mod.PlanWeek:
    return p.week_for_date(as_of or date.today())


def _actuals_for(p: plan_mod.PlanLock, week: plan_mod.PlanWeek) -> digest_mod.WeekActuals:
    activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
    return digest_mod.actuals_for_plan_week(activities, week.wc, week.wc + timedelta(days=6))


@app.command()
def sync(
    since: int = typer.Option(None, "--since", help="Days to look back (default 60)"),
    source: str = typer.Option("both", "--source", help="garmin|intervals|both"),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Fail fast instead of prompting for a Garmin MFA code. Auto-detected when there's no terminal; this forces it.",
    ),
):
    """Pull fresh data from Garmin and/or intervals.icu.

    Whether an MFA prompt is possible is detected from the terminal, so a
    cron job or cloud session gets a clear error instead of blocking on
    input() — no flag needed. --non-interactive forces that behaviour.
    """
    if source not in ("garmin", "intervals", "both"):
        raise typer.BadParameter("source must be garmin|intervals|both")
    report = sync_mod.run_sync(
        since_days=since, source=source, interactive=False if non_interactive else None
    )
    table = Table(title="mc sync — data health")
    for col in ("source", "ok", "staleness (h)", "activities", "error"):
        table.add_column(col)
    for name, s in report.sources.items():
        table.add_row(
            name,
            str(s.ok),
            f"{s.staleness_hours:.1f}" if s.staleness_hours is not None else "—",
            str(s.activities_pulled),
            s.error or "—",
        )
    console.print(table)
    raise typer.Exit(0 if report.all_ok else 1)


@app.command()
def digest(date_: str = typer.Option(None, "--date", help="DD-MM, defaults to today")):
    """Regenerate today's markdown digest from cached data. Also backfills
    any pending Actual entries in log/training-log.md from freshly-synced
    data — this is the natural point to do it, since digest always runs
    right after mc sync in the daily ritual."""
    as_of = _parse_ddmm(date_) if date_ else date.today()
    path = digest_mod.write_digest(as_of)
    console.print(f"Digest written to {path}")
    console.print(path.read_text())

    activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
    filled = tlog_mod.fill_pending_actuals(activities, up_to=as_of - timedelta(days=1))
    if filled:
        console.print(f"[dim]Backfilled {filled} pending entr{'y' if filled == 1 else 'ies'} in {cfg.TRAINING_LOG_PATH}[/dim]")


@app.command()
def weather(
    date_: str = typer.Option(None, "--date", help="DD-MM, defaults to today"),
    days: int = typer.Option(2, "--days", "-n", help="How many days to show, including --date"),
    refresh: bool = typer.Option(False, "--refresh", help="Fetch now instead of reading the cache"),
):
    """Ambient conditions by training window — the numbers behind "outdoor and
    early, or indoors any time?".

    Normally reads the cache written by `mc sync`. Each window is summarised by
    its *worst* hour, because a window is a commitment to be outside for all of
    it — right for a long run, misleading for a short one that is *placed*
    inside a window rather than occupying it. So a `↳` line names the coolest
    hour within any window whose own hours differ enough to change the answer.

    Heat levels are none/noticeable/hard/extreme — input you cite when
    exercising §6 C2, never a trigger that fires by itself.
    """
    as_of = _parse_ddmm(date_) if date_ else date.today()

    if refresh:
        activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
        location = weather_mod.resolve_location(activities)
        if location is None:
            console.print(
                "[yellow]No location: no GPS activity in the last "
                f"{weather_mod.LOCATION_MAX_AGE_DAYS} days, and MC_WEATHER_LAT/LON "
                "isn't set in .env.[/yellow]"
            )
            raise typer.Exit(1)
        try:
            weather_mod.fetch(location)
        except weather_mod.WeatherError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e

    envelope = weather_mod.load_cached()
    if envelope is None:
        console.print("[yellow]No weather cached — run `mc sync`, or `mc weather --refresh`.[/yellow]")
        raise typer.Exit(1)

    age = weather_mod.cache_age_hours(envelope)
    loc = envelope.get("location") or {}
    console.print(
        f"[dim]{loc.get('lat')}, {loc.get('lon')} (from {loc.get('source', 'unknown')}) · "
        f"fetched {f'{age:.0f}h ago' if age is not None else 'unknown'}[/dim]"
    )
    if age is not None and age > weather_mod.STALE_HOURS:
        console.print(
            f"[yellow]Forecast is {age:.0f}h old (>{weather_mod.STALE_HOURS}h) — "
            f"re-run `mc sync` before trusting it.[/yellow]"
        )

    hours = weather_mod.hours_from_payload(envelope.get("data") or {})
    if not hours:
        console.print("[yellow]Cached payload has no hourly data.[/yellow]")
        raise typer.Exit(1)

    for offset in range(max(1, days)):
        day = as_of + timedelta(days=offset)
        windows = weather_mod.windows_for_day(hours, day)
        if not windows:
            console.print(f"[yellow]{day.strftime('%d-%m')}: no forecast hours cached.[/yellow]")
            continue
        best = weather_mod.best_window(windows)
        table = Table(title=day.strftime("%d-%m"))
        for col in ("Window", "Feels like", "Dew point", "Precip", "Wind", "Heat"):
            table.add_column(col)
        findings: list[tuple[weather_mod.Window, weather_mod.SubWindow]] = []
        for w in windows:
            coolest = best is not None and w.name == best.name
            table.add_row(
                f"[green]{w.label} ←[/green]" if coolest else w.label,
                weather_mod.fmt_temp(w.feels_like_f),
                weather_mod.fmt_temp(w.dew_point_f),
                f"{w.precip_prob:.0f}%" if w.precip_prob is not None else "—",
                f"{w.wind_mph:.0f} mph" if w.wind_mph is not None else "—",
                w.heat.value,
            )
            finding = weather_mod.sub_window_finding(hours, w)
            if finding is not None:
                findings.append((w, finding))
        console.print(table)
        for w, s in findings:
            console.print(
                f"[cyan]↳ {w.name}: a short session fits in {s.label} — "
                f"{weather_mod.fmt_temp(s.feels_like_f)} feels-like, dew point "
                f"{weather_mod.fmt_temp(s.dew_point_f)} ({s.heat.value}), against "
                f"{weather_mod.fmt_temp(w.feels_like_f)} for the window.[/cyan]"
            )

    console.print(
        "[dim]Worst hour in each window — right for a long run, which commits you to "
        "all of it. For a short run, place it: ↳ lines give the coolest hour inside a "
        "window whose own hours differ enough to matter. Heat level is a reporting "
        "label, not a §4 verdict and not a §6 trigger — cite the numbers for C2.[/dim]"
    )


@app.command()
def status():
    """Week N of 14, plan vs actual, compliance, ratios."""
    p = plan_mod.load_plan()
    week = _current_week(p)
    block = p.block_for(week)
    actuals = _actuals_for(p, week)

    days_to_race = (p.race_date - date.today()).days
    console.print(
        f"[bold]Week {week.week}/{len(p.weeks)} · w/c {week.wc.strftime('%d-%m')} · "
        f"block {week.block}[/bold] · {days_to_race} days to race"
    )

    table = Table()
    table.add_column("metric")
    table.add_column("planned")
    table.add_column("actual")
    table.add_row("Long run", f"{week.long_run_mi:g}mi", f"{actuals.long_run_mi:g}mi")
    table.add_row("Weekly volume", f"{week.run_miles:g}mi", f"{actuals.run_miles:g}mi")
    table.add_row("Run days", str(week.run_days), str(actuals.run_days))
    table.add_row("Cross minutes", f"{week.cross_minutes:g}", f"{actuals.cross_minutes:g}")
    console.print(table)

    console.print(f"Compliance floor: {block.compliance_floor:.0%}")
    if week.run_miles:
        console.print(f"Actual/planned volume so far: {actuals.run_miles / week.run_miles:.0%}")
    console.print(f"Long-run ratio cap this week: {week.long_run_ratio_max:.0%}")


@app.command()
def check(
    as_of_s: str = typer.Option(None, "--as-of", help="DD-MM to check as of (default today)"),
    actuals_only: bool = typer.Option(
        False, "--actuals-only", help="Judge only what has happened, ignoring the rest of the week"
    ),
):
    """Run §6 on the week as proposed: actuals for the days already elapsed,
    the persisted layout for the days still ahead.

    §6's A-rules are whole-week metrics. Judging actuals-so-far against them
    made every mid-week run report violations that were arithmetic rather
    than findings — a build week's 95% floor cannot be met on a Tuesday. The
    blend asks the question that is actually decidable today: finish the week
    as laid out, and does it pass? A skipped session still drags the
    projection under the floor, so real findings survive.
    """
    p = plan_mod.load_plan()
    as_of = _parse_ddmm(as_of_s) if as_of_s else date.today()
    week = _current_week(p, as_of)
    week_end = week.wc + timedelta(days=6)
    activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
    layout = layout_mod.get_layout(layout_mod.week_start_for(as_of))

    if layout is not None and not actuals_only:
        by_day = digest_mod.actuals_by_day(activities, week.wc, week_end)
        projection = planning_mod.project_week(week, layout, by_day, as_of)
        block = p.block_for(week)
        floor_mi = block.compliance_floor * week.run_miles
        console.print(f"[bold]Week {week.week} · w/c {week.wc.strftime('%d-%m')}[/bold] — projected")
        console.print(
            f"  actual    {projection.banked_miles:g} mi over "
            f"{len(projection.elapsed_days)} day(s) already settled"
        )
        console.print(
            f"  remaining {projection.remaining_miles:g} mi over "
            f"{len(projection.remaining_days)} day(s) still to run, per layout"
            + (f" ({', '.join(projection.remaining_days)})" if projection.remaining_days else "")
        )
        console.print(
            f"  projected {projection.proposed.run_miles:g} mi vs plan {week.run_miles:g} mi "
            f"· floor {floor_mi:.1f} mi ({block.compliance_floor:.0%})"
        )
        result = rules_mod.check_week(projection.proposed, p)
        if result.allowed:
            console.print("[green]No violations.[/green]")
        else:
            for v in result.violations:
                console.print(f"[red]{v.rule_id}[/red] ({v.category}): {v.message}")
            # The week as laid out does not pass. That is a layout problem,
            # and reordering/resizing easy runs is C1 — free, no approval.
            console.print(
                f"[dim]The week as laid out does not pass. Revise it: "
                f"mc layout {week.week} --week-start {layout.week_start} --revise "
                f'--set "DD-MM:mi:type,..." — not an override.[/dim]'
            )
        raise typer.Exit(0 if result.allowed else 1)

    # Degraded tier: no layout to project the rest of the week from, so the
    # cumulative end-of-week rules can only produce noise. Suppress them and
    # say so — a quieter check that doesn't admit what it stopped checking is
    # worse than the noisy one it replaced.
    actuals = digest_mod.actuals_for_plan_week(activities, week.wc, week_end, as_of=as_of)
    reason = (
        "--actuals-only"
        if actuals_only
        else f"no layout set for w/c {layout_mod.week_start_for(as_of)}"
    )
    console.print(f"[yellow]Degraded check — {reason}.[/yellow]")
    proposed = rules_mod.ProposedWeek(
        week=week.week,
        long_run_mi=actuals.long_run_mi,
        run_miles=actuals.run_miles,
        run_days=actuals.run_days,
        cross_minutes=actuals.cross_minutes,
    )
    full = rules_mod.check_week(proposed, p)
    long_run_day_passed = as_of >= week_end
    blocking_ids = rules_mod.PARTIAL_WEEK_BLOCKING_RULE_IDS
    if not long_run_day_passed:
        blocking_ids = blocking_ids - rules_mod.LONG_RUN_EVENT_RULE_IDS
    suppressed = [v for v in full.violations if v.rule_id not in blocking_ids]
    result = rules_mod.RuleResult.from_violations(
        [v for v in full.violations if v.rule_id in blocking_ids]
    )
    console.print(
        f"[dim]Cumulative rules ({', '.join(sorted(rules_mod.ALL_A_RULE_IDS - blocking_ids))}) "
        f"are not being judged — they need a full week. "
        f"Run mc layout in /week for the projected check.[/dim]"
    )
    if suppressed:
        console.print(f"[dim]Suppressed here: {', '.join(sorted({v.rule_id for v in suppressed}))}.[/dim]")
    if result.allowed:
        console.print("[green]No violations.[/green]")
    else:
        for v in result.violations:
            console.print(f"[red]{v.rule_id}[/red] ({v.category}): {v.message}")
    raise typer.Exit(0 if result.allowed else 1)


@app.command()
def week(
    week_num: int = typer.Option(None, "--week", help="Week number 1-14"),
    wc: str = typer.Option(None, "--wc", help="DD-MM of any day in the target week"),
):
    """Show a specific week's plan and actuals (defaults to the current week)."""
    p = plan_mod.load_plan()
    if week_num is not None:
        w = p.week_by_number(week_num)
    elif wc is not None:
        w = p.week_for_date(_parse_ddmm(wc))
    else:
        w = _current_week(p)
    block = p.block_for(w)
    actuals = _actuals_for(p, w)

    console.print(f"[bold]Week {w.week} · w/c {w.wc.strftime('%d-%m')} · block {w.block}[/bold]")
    if w.notes:
        console.print(f"[dim]{w.notes}[/dim]")
    table = Table()
    table.add_column("metric")
    table.add_column("planned")
    table.add_column("actual")
    table.add_row("Long run", f"{w.long_run_mi:g}mi", f"{actuals.long_run_mi:g}mi" if actuals.has_started else "—")
    table.add_row("Weekly volume", f"{w.run_miles:g}mi", f"{actuals.run_miles:g}mi" if actuals.has_started else "—")
    table.add_row("Run days", str(w.run_days), str(actuals.run_days) if actuals.has_started else "—")
    console.print(table)
    console.print(
        f"Block compliance floor: {block.compliance_floor:.0%}"
        + (" (frozen)" if block.frozen else "")
        + (" (opportunistic long run)" if block.long_run_opportunistic else "")
    )


@app.command()
def equiv(session: str = typer.Argument(..., help='e.g. "8 mi easy"')):
    """Substitution table for a prescribed session."""
    parsed = eq.parse_session(session)
    options = eq.build_substitution_table(parsed)
    table = Table(title=f"Substitution options: {session}")
    table.add_column("Option")
    table.add_column("Duration")
    table.add_column("Est. equivalent")
    table.add_column("Verdict")
    for o in options:
        pct = f"~{o.equivalent_pct:.0%}" if o.equivalent_pct is not None else "—"
        table.add_row(o.option, o.duration, pct, o.verdict)
    console.print(table)
    for o in options:
        console.print(f"  {o.option}: lost — {o.lost}")


@app.command()
def fuel(
    session: str = typer.Argument(..., help='e.g. "16 mi long"'),
    week_num: int = typer.Option(None, "--week", help="Plan week, defaults to today's"),
):
    """In-run carbohydrate plan for a long session. Silent for short ones."""
    parsed = eq.parse_session(session)
    if week_num is None:
        week_num = _current_week(plan_mod.load_plan()).week

    plan = fuel_mod.build_plan(parsed.distance_mi, week_num)
    if plan is None:
        console.print(
            f"{parsed.distance_mi:g} mi is under "
            f"{fuel_mod.MIN_FUEL_DURATION_MIN:.0f} min — no in-run fuelling needed."
        )
        return

    console.print(f"[bold]Fuelling — {session}, week {week_num}[/bold]")
    console.print(plan.summary)
    for line in fuel_mod.plan_lines(plan):
        console.print(f"  {line}")
    console.print(
        "  [dim]Descriptive, not a §6 rule (D6). The gut adapts to this the way "
        "legs adapt to mileage — ramp it.[/dim]"
    )


def _parse_day_miles(spec: str) -> dict[str, float]:
    day_miles = {}
    for pair in spec.split(","):
        d, mi = pair.split(":")
        day_miles[d.strip()] = float(mi)
    return day_miles


@app.command(name="state")
def state_cmd(
    check_: bool = typer.Option(False, "--check", help="Refuse to proceed if state is stale (run before /daily)"),
    save: str = typer.Option(None, "--save", help="Commit and push state with this message (run after /daily)"),
    claim: str = typer.Option(
        None, "--claim", help="Take the writer lease for this purpose, e.g. 'daily 05-08' (run before /daily writes)"
    ),
    release_: bool = typer.Option(False, "--release", help="Drop the writer lease without saving (abandoned ritual)"),
    force: bool = typer.Option(False, "--force", help="With --claim: take over a lease held by another device/session"),
):
    """Guard and sync the private state repo.

    Without flags, reports where state lives, whether it's in sync, and who
    holds the writer lease.
    """
    if claim:
        try:
            lease, warning = state_mod.claim(claim, force=force)
        except state_mod.StateError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        console.print(f"[green]writer lease held by[/green] {lease.device} — {lease.purpose}")
        if warning:
            console.print(f"[yellow]{warning}[/yellow]")
        return

    if release_:
        dropped = state_mod.release()
        console.print("[green]lease released[/green]" if dropped else "[dim]no lease held[/dim]")
        return

    if save:
        try:
            done = state_mod.save(save)
        except state_mod.StateError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        console.print(f"[green]state saved:[/green] {done}" if done else "[dim]nothing to save[/dim]")
        return

    try:
        st = state_mod.check() if check_ else state_mod.status()
    except state_mod.StateError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    console.print(f"state root: {st.root}")
    console.print(f"this device: {state_mod.device_id()}")
    held = state_mod.read_lease(st.root)
    if held is None:
        console.print("[dim]writer lease: free[/dim]")
    elif held.mine and not held.expired:
        console.print(f"[yellow]writer lease: held by this device — {held.describe()}[/yellow]")
    elif held.expired:
        console.print(f"[dim]writer lease: {held.describe()} — claimable[/dim]")
    else:
        console.print(f"[red]writer lease: {held.describe()} — do not write here[/red]")
    if not st.is_split:
        console.print(
            "[dim]Not split — state lives in the code checkout. Set MC_STATE_DIR in .env "
            "to point at a private state repo.[/dim]"
        )
        return
    if not st.is_git_repo:
        console.print("[yellow]MC_STATE_DIR is set but isn't a git repo — nothing guards two-machine writes.[/yellow]")
        return

    console.print(f"behind {st.behind} · ahead {st.ahead} · {'clean' if st.clean else f'{len(st.dirty)} uncommitted'}")
    if st.behind:
        console.print(f"[red]Behind — pull before writing: git -C {st.root} pull[/red]")
    elif st.ahead:
        console.print("[yellow]Unpushed state — run `mc state --save \"...\"` or push manually.[/yellow]")


@app.command()
def drift(weeks: int = typer.Option(4, "--weeks", help="Trailing window, default 4 (one block)")):
    """Is the plan still matching real life? Counts and dates, in sentences.

    Surfaces the trend *before* the override count forces the question (§6
    E5). Reports facts only — it never diagnoses a symptom and never proposes
    a plan change; that's the agent's job, with §6 in hand.
    """
    report = drift_mod.build_report(weeks=weeks)
    for line in drift_mod.format_report(report):
        if line.startswith("["):
            console.print(f"[dim]{line}[/dim]")
        elif "over the limit" in line or "short." in line:
            console.print(f"[red]{line}[/red]")
        else:
            console.print(line)


@app.command()
def override(
    reason: str = typer.Argument(..., help="Why — cited, specific. Not 'I feel tired'."),
    code: str = typer.Option(..., "--code", help=f"One of: {' '.join(drift_mod.REASON_CODES)}"),
    day: str = typer.Option(None, "--date", help="DD-MM, defaults to today"),
):
    """Append an override to context/overrides.md (§6 E4).

    Only ever run this after I have typed a literal `OVERRIDE: <reason>` —
    never inferred from a paraphrase, however close.
    """
    try:
        entry = drift_mod.append_override(code, reason, day=_parse_ddmm(day) if day else None)
    except drift_mod.OverrideError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]recorded:[/green]{entry}")

    report = drift_mod.build_report()
    if report.overrides and len(report.overrides) > drift_mod.OVERRIDE_LIMIT_PER_BLOCK:
        console.print(
            f"[red]That's {len(report.overrides)} overrides in the last 4 weeks, over the limit of "
            f"{drift_mod.OVERRIDE_LIMIT_PER_BLOCK}. §6 E5: propose a structural revision, not another "
            f"override.[/red]"
        )


@app.command(name="plan")
def plan_cmd(
    days: int = typer.Option(3, "--days", "-n", help="How many days ahead, including today (default 3)"),
    start: str = typer.Option(None, "--start", help="DD-MM, defaults to today"),
):
    """The next N days: today from real data, the rest projected.

    Emits the deterministic skeleton only — dates, planned miles, session
    types, strength days, rule status. The day's judgement calls belong to
    /daily and /preview, which have the answers this can't know.
    """
    start_date = _parse_ddmm(start) if start else date.today()
    p = plan_mod.load_plan()
    look = planning_mod.lookahead(p, start_date, days=days)

    if not look.days:
        console.print("[yellow]No plan weeks cover that range.[/yellow]")
        raise typer.Exit(1)

    table = Table(title=f"{days} days from {start_date.strftime('%d-%m')}")
    table.add_column("Day")
    table.add_column("Basis")
    table.add_column("Miles", justify="right")
    table.add_column("Session")
    table.add_column("Notes")
    for d_ in look.days:
        notes = []
        if d_.is_long_run:
            notes.append("LONG RUN")
        if d_.is_fixed_strength:
            notes.append("fixed strength")
        if not d_.layout_known:
            notes.append("layout not set — weekly average")
        table.add_row(
            d_.ddmm,
            "actual" if d_.basis is planning_mod.Basis.ACTUAL else "[yellow]projected[/yellow]",
            f"{d_.miles:g}",
            d_.session,
            " · ".join(notes),
        )
    console.print(table)

    if look.provisional_days:
        console.print(f"[yellow]{planning_mod.format_assumptions()}[/yellow]")
        console.print("[dim]Projected days are provisional — not pushed, not logged as proposals.[/dim]")
    for ws in look.missing_layout_weeks:
        console.print(f"[yellow]No layout set for w/c {ws} — run /week, or `mc layout ... --set`.[/yellow]")

    if look.week_check and not look.week_check.allowed:
        console.print("[red]This week's layout violates §6:[/red]")
        for v in look.week_check.violations:
            console.print(f"  [red]{v.rule_id}[/red]: {v.message}")


@app.command(name="layout")
def layout_cmd(
    week_num: int = typer.Argument(..., help="Plan week number (1-14)"),
    week_start: str = typer.Option(..., "--week-start", help="DD-MM Monday of this plan week"),
    set_days: str = typer.Option(
        None,
        "--set",
        help='Day layout: "28-07:4:easy,29-07:0:rest,02-08:11:long" (DD-MM:miles[:type]). '
        "Type defaults to easy/rest by mileage. First write per week wins — use --revise to change a live week.",
    ),
    revise: bool = typer.Option(False, "--revise", help="Overwrite an existing week's layout (C1 reshuffle)"),
    long_run_day: str = typer.Option(None, "--long-run-day", help="DD-MM; inferred when one day is typed ':long'"),
):
    """Show or set this week's day-of-week layout.

    plan.lock.json freezes weekly totals, not day placement — that's decided
    each Monday in /week. This is where it gets remembered, so the rest of the
    system can answer "what is Thursday?".
    """
    if set_days:
        try:
            days, inferred = layout_mod.parse_day_spec(set_days)
            long_day = long_run_day or inferred
            if not long_day:
                console.print("[red]No long run day — mark one day ':long' or pass --long-run-day.[/red]")
                raise typer.Exit(1)
            already_set = layout_mod.get_layout(week_start) is not None
            fn = layout_mod.revise if revise else layout_mod.set_layout
            wl = fn(week_start, days, long_day)
        except layout_mod.LayoutError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1) from e
        if already_set and not revise:
            console.print("[yellow]Week already had a layout — returned unchanged. Use --revise to overwrite.[/yellow]")
    else:
        wl = layout_mod.get_layout(week_start)
        if not wl:
            console.print(f"[yellow]No layout set for week starting {week_start} — set one with --set.[/yellow]")
            raise typer.Exit(1)

    fixed = set(strength_mod.get_fixed_days(week_start) or [])
    table = Table(title=f"Week {week_num} · w/c {week_start}" + (f" · revised {wl.revised}x" if wl.revised else ""))
    table.add_column("Day")
    table.add_column("Miles", justify="right")
    table.add_column("Session")
    table.add_column("Strength")
    for d in wl.days:
        marker = "long" if d.day == wl.long_run_day else d.session
        table.add_row(d.day, f"{d.miles:g}", marker, "fixed" if d.day in fixed else "")
    console.print(table)
    console.print(f"total {wl.total_miles:g} mi · run days {wl.run_days} · long run {wl.long_run_day}")

    # Say up front whether the week as laid out would pass §6, rather than
    # letting it surface days later in a `mc check`.
    try:
        p = plan_mod.load_plan()
        result = rules_mod.check_week(layout_mod.as_proposed_week(wl, week_num), p)
    except FileNotFoundError:
        return
    if result.allowed:
        console.print("[green]layout passes §6[/green]")
    else:
        console.print("[red]layout violates §6:[/red]")
        for v in result.violations:
            console.print(f"  [red]{v.rule_id}[/red]: {v.message}")


@app.command()
def strength(
    week_num: int = typer.Argument(..., help="Plan week number (1-14)"),
    week_start: str = typer.Option(..., "--week-start", help="DD-MM Monday of this plan week"),
    set_days: str = typer.Option(
        None,
        "--set-days",
        help='First call per week only: e.g. "29-07:2,31-07:2,02-08:10,03-08:0" '
        "(DD-MM:planned_miles for every day) plus --long-run-day",
    ),
    long_run_day: str = typer.Option(None, "--long-run-day", help="DD-MM of this week's long run"),
    pending: str = typer.Option(
        None, "--pending", help="Check for an unconfirmed fixed day before this DD-MM (yesterday, normally)"
    ),
    confirm: str = typer.Option(
        None, "--confirm", help='"DD-MM:done" or "DD-MM:missed" -- record whether a fixed day happened'
    ),
    reschedule_candidates: str = typer.Option(
        None,
        "--reschedule-candidates",
        help='With "--confirm DD-MM:missed": remaining days to reschedule into, '
        'e.g. "31-07:0,01-08:2,02-08:10" (DD-MM:planned_miles)',
    ),
    bodyweight: bool = typer.Option(
        False,
        "--bodyweight",
        help="No weights available today — swap to the hardest equipment-free variant",
    ),
):
    """Fixed strength day(s), this week's progression tier, and day-after
    confirm/reschedule. Days are chosen once per week and persisted --
    call with --set-days/--long-run-day on the week's first call, plain on
    every call after that. Use --pending to check whether yesterday's fixed
    day still needs a done/missed confirmation, then --confirm to record it
    (missed sessions auto-reschedule onto the best remaining day this week
    if --reschedule-candidates is given)."""
    if pending:
        day = strength_mod.pending_confirmation(week_start, pending)
        console.print(day if day else "none")
        return

    if confirm:
        day, status = confirm.split(":")
        done = status.strip().lower() == "done"
        strength_mod.confirm_day(week_start, day.strip(), done)
        console.print(f"{day.strip()}: recorded as {'done' if done else 'missed'}")
        if not done and reschedule_candidates:
            if not long_run_day:
                console.print("[red]--long-run-day is required alongside --reschedule-candidates[/]")
                raise typer.Exit(1)
            new_day = strength_mod.reschedule_missed(
                week_start, day.strip(), _parse_day_miles(reschedule_candidates), long_run_day
            )
            if new_day:
                console.print(f"Rescheduled to {new_day} (after that day's run)")
            else:
                console.print("No suitable day left this week — missed, not rescheduled")
        return

    if set_days:
        if not long_run_day:
            console.print("[red]--long-run-day is required alongside --set-days[/]")
            raise typer.Exit(1)
        days = strength_mod.set_fixed_days(week_start, _parse_day_miles(set_days), long_run_day)
    else:
        days = strength_mod.get_fixed_days(week_start)

    tier = strength_mod.tier_for_week(week_num)
    items = strength_mod.items_for_week(week_num, bodyweight_only=bodyweight)

    console.print(f"Week {week_num} (w/c {week_start}) — tier {tier + 1}/3")
    if bodyweight:
        console.print(
            "[yellow]Bodyweight only — hardest equipment-free variant of each. "
            "A step down in stimulus, not a rest day.[/yellow]"
        )
    if days:
        console.print(f"Fixed strength days: {', '.join(days)} (after that day's run)")
    else:
        console.print("Fixed strength days: not yet set for this week — pass --set-days")

    table = Table(title="This week's fixed session")
    table.add_column("Exercise")
    table.add_column("Protocol")
    table.add_column("Min")
    table.add_column("Source")
    for it in items:
        table.add_row(it.name, it.protocol, str(it.minutes), it.source)
    console.print(table)


def _report_export() -> None:
    """Never silent success — an export you can't see is one you can't trust."""
    try:
        result = export_mod.export()
    except export_mod.ExportError as e:
        console.print(f"[red]export failed:[/red] {e}")
        return
    if not result.enabled:
        return
    if result.copied:
        console.print(f"exported {len(result.copied)} file(s) to {result.destination}")
    else:
        console.print(f"[yellow]nothing to export to {result.destination}[/yellow]")


@app.command(name="export")
def export_cmd():
    """Copy out/*.md and out/*.html into MC_EXPORT_DIR (a plain local folder —
    typically one your cloud client already syncs to your phone). Runs
    automatically as part of `mc render --all`; this is the manual re-copy.
    No credentials, no network, nothing read back."""
    if export_mod.export_dir() is None:
        console.print(
            "[yellow]MC_EXPORT_DIR is not set in .env — export is off.[/yellow]\n"
            "[dim]e.g. MC_EXPORT_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/marathon[/dim]"
        )
        raise typer.Exit(1)
    _report_export()


def _report_tidy(as_of: date | None = None, dry_run: bool = False) -> None:
    """Never silent — a file deleted without saying so is indistinguishable
    from one that was never written."""
    result = tidy_mod.tidy(as_of=as_of, dry_run=dry_run)
    verb = "would remove" if dry_run else "removed"
    for removal in result.removed:
        console.print(f"[dim]{verb} {removal.name} — {removal.reason}[/dim]")
    for path in result.undated:
        console.print(
            f"[yellow]{path.name} declares no day (no `# DD-MM` header, no -DD-MM suffix) "
            f"— left in place, but nothing can tell whether it's current.[/yellow]"
        )
    if dry_run and not result.removed:
        console.print("[dim]out/ is already clean[/dim]")


@app.command(name="tidy")
def tidy_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would go, delete nothing"),
    as_of_s: str = typer.Option(None, "--as-of", help="DD-MM to treat as today"),
):
    """Delete out/ files whose declared day has passed.

    Runs automatically as part of `mc render --all`; this is the manual pass.
    """
    _report_tidy(as_of=_parse_ddmm(as_of_s) if as_of_s else None, dry_run=dry_run)


@app.command(name="render")
def render_cmd(
    all_: bool = typer.Option(False, "--all", help="Refresh dashboard.md, tidy out/, and export"),
    html: bool = typer.Option(False, "--html", help="Also write the standalone .html twins"),
):
    """Refresh out/'s generated files. Markdown only unless --html.

    HTML used to be produced on every run and read by nobody — /daily and
    /preview write markdown, and it gets read on GitHub. It stays one flag
    away rather than being deleted.
    """
    if all_:
        if html:
            paths, skipped = render_mod.render_all()
            for p_ in paths:
                console.print(f"rendered {p_}")
            for p_ in skipped:
                console.print(
                    f"[yellow]skipped {p_.name} — it's a provisional projection for another day. "
                    f"Re-run /preview to refresh it.[/yellow]"
                )
        try:
            plan = plan_mod.load_plan()
            activities = digest_mod._load_latest(cfg.RAW_GARMIN_DIR, "activities")
            dash_md = render_mod.write_dashboard_md(plan, activities)
            console.print(f"wrote {dash_md}")
            if html:
                console.print(f"rendered {render_mod.write_dashboard(plan, activities)}")
        except FileNotFoundError:
            console.print("[yellow]no plan.lock.json — skipping dashboard[/yellow]")
        # Tidy after writing, so it judges the mtimes this run just produced —
        # that is what retires the .html twins once --html stops being passed.
        _report_tidy()
        # Export rides on --all so the rituals cover it with no extra step.
        # Silent no-op when MC_EXPORT_DIR is unset; loud when it's set but wrong.
        _report_export()
    elif html:
        today_md = cfg.OUT_DIR / "today.md"
        if today_md.exists():
            console.print(f"rendered {render_mod.render_file(today_md)}")
        else:
            console.print("[yellow]out/today.md doesn't exist yet — run the daily workflow first, or use --all[/yellow]")
    else:
        console.print(
            "[yellow]Nothing to do — markdown is written by /daily and /preview directly.[/yellow]\n"
            "[dim]`mc render --all` refreshes the dashboard and tidies out/; add --html for the HTML twins.[/dim]"
        )


@app.command()
def log(text: str = typer.Argument(..., help="Free text to append to today's session log")):
    """Append free text to today's session log."""
    cfg.LOG_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    path = cfg.LOG_SESSIONS_DIR / f"{today.isoformat()}.md"
    is_new = not path.exists() or path.stat().st_size == 0
    timestamp = datetime.now().strftime("%H:%M")
    with path.open("a") as f:
        if is_new:
            f.write(f"# {today.strftime('%d-%m')}\n\n")
        f.write(f"- {timestamp} — {text}\n")
    console.print(f"Logged to {path}")


@app.command()
def propose(
    text: str = typer.Argument(..., help="Today's proposed session, e.g. 'Elliptical 60min @ HR135-145'"),
    date_: str = typer.Option(None, "--date", help="DD-MM, defaults to today"),
):
    """Record today's proposed session into log/training-log.md (Proposed
    column). The Actual column gets filled in automatically by `mc digest`
    once real data for that date is available — see the file itself for
    the running proposed-vs-actual table."""
    as_of = _parse_ddmm(date_) if date_ else date.today()
    tlog_mod.record_proposed(as_of, text)
    console.print(f"Recorded in {cfg.TRAINING_LOG_PATH}")


@app.command()
def push(
    date_: str = typer.Option(..., "--date", help="DD-MM — must match out/today.md's own date"),
    option: str = typer.Option(None, "--option", help='Push a specific substitution-table option (e.g. "bike") instead of the primary Today prescription'),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the JSON payload, no network call"),
    yes: bool = typer.Option(False, "--yes", help="Actually push — required for any real network call"),
):
    """Preview or push today's workout to Garmin Connect. Never run as part
    of sync or the daily ritual — always explicit, always opt-in."""
    target_date = _parse_ddmm(date_)
    p = plan_mod.load_plan()
    week = _current_week(p, target_date)

    today_md_path = cfg.OUT_DIR / "today.md"
    if not today_md_path.exists():
        console.print("[red]out/today.md doesn't exist — run /daily first.[/red]")
        raise typer.Exit(1)

    try:
        if option:
            session = push_mod.parse_option_from_today_md(today_md_path.read_text(), target_date, option)
        else:
            session = push_mod.parse_session_from_today_md(today_md_path.read_text(), target_date)
    except push_mod.SessionParseError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    amount = f"{session.distance_mi:g}mi" if session.modality == "run" else f"{session.duration_min:g}min"
    console.print(f"[bold]{session.modality} · {session.session_type} · {amount} · HR {session.hr_low}-{session.hr_high}[/bold]")

    actuals = _actuals_for(p, week)
    proposed_actuals = rules_mod.ProposedWeek(
        week=week.week, long_run_mi=actuals.long_run_mi, run_miles=actuals.run_miles,
        run_days=actuals.run_days, cross_minutes=actuals.cross_minutes,
    )
    check = push_mod.check_before_push(session, week, proposed_actuals, p)
    if not check.allowed and yes:
        console.print("[red]Refusing to push — this would violate §6:[/red]")
        for v in check.violations:
            console.print(f"  [red]{v.rule_id}[/red]: {v.message}")
        raise typer.Exit(1)
    elif not check.allowed:
        console.print("[yellow]Note: pushing this for real (--yes) would currently be refused —[/yellow]")
        for v in check.violations:
            console.print(f"  [yellow]{v.rule_id}[/yellow]: {v.message}")

    result = push_mod.push_workout(
        target_date, week, session, eq.EASY_PACE_MIN_PER_MI, dry_run=dry_run or not yes, yes=yes,
    )

    if result.action == "dry_run":
        note = "--dry-run requested, no network call made." if dry_run else "pass --yes to actually push."
        console.print(f"[dim]{note}[/dim]")
        console.print_json(data=result.payload)
    else:
        console.print(f"[green]{result.action}[/green]: {result.name} (workout_id={result.workout_id})")


@app.command()
def unpush(date_: str = typer.Option(..., "--date", help="DD-MM of the pushed workout to remove")):
    """Remove a previously pushed workout from Garmin Connect."""
    target_date = _parse_ddmm(date_)
    removed = push_mod.unpush_workout(target_date)
    if removed:
        console.print(f"[green]Removed workout for {date_}.[/green]")
    else:
        console.print(f"[yellow]No pushed workout found for {date_}.[/yellow]")


if __name__ == "__main__":
    app()
