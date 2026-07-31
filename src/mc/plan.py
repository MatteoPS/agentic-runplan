from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from mc import config as cfg


class PlanImmutableError(Exception):
    """plan.lock.json is immutable — use OVERRIDE."""


class PlanBlock(BaseModel):
    weeks: tuple[int, int]
    compliance_floor: float
    long_run_opportunistic: bool = False
    no_quality: bool = False
    no_gym: bool = False
    frozen: bool = False

    def contains(self, week: int) -> bool:
        return self.weeks[0] <= week <= self.weeks[1]


class PlanWeek(BaseModel):
    week: int
    wc: date
    source_week: int | None = None
    long_run_mi: float
    run_miles: float
    run_days: int
    cross_minutes: float
    quality_sessions: int
    long_run_ratio_max: float
    is_stepback: bool = False
    is_taper: bool = False
    is_twenty: bool = False
    block: str
    notes: str = ""


class PlanLock(BaseModel):
    race_date: date
    plan: str
    units: str
    locked_at: datetime
    design_decisions: list[str] = []
    weeks: list[PlanWeek]
    blocks: dict[str, PlanBlock]

    def week_by_number(self, n: int) -> PlanWeek:
        for w in self.weeks:
            if w.week == n:
                return w
        raise KeyError(f"No week {n} in plan")

    def week_for_date(self, d: date) -> PlanWeek:
        for w in self.weeks:
            if w.wc <= d < w.wc.fromordinal(w.wc.toordinal() + 7):
                return w
        raise KeyError(f"No plan week covers {d}")

    def block_for(self, week: PlanWeek) -> PlanBlock:
        if week.block not in self.blocks:
            raise KeyError(f"Week {week.week} references unknown block {week.block!r}")
        return self.blocks[week.block]

    def adjacent_week(self, n: int, offset: int) -> PlanWeek | None:
        try:
            return self.week_by_number(n + offset)
        except KeyError:
            return None


def load_plan(path=cfg.PLAN_LOCK_PATH) -> PlanLock:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist — plan.lock.json hasn't been frozen yet "
            f"(build-order step 6)."
        )
    return PlanLock.model_validate_json(path.read_text())


def write_plan_lock(plan: PlanLock, path=cfg.PLAN_LOCK_PATH, *, force: bool = False) -> None:
    """Writes plan.lock.json exactly once. Any subsequent call refuses,
    per the spec's own design: 'plan.lock.json is immutable — use OVERRIDE.'
    `force` exists only for the initial freeze / deliberate, explicit
    re-freezes done by a human, never for programmatic use."""
    if path.exists() and not force:
        raise PlanImmutableError(
            "plan.lock.json is immutable — use OVERRIDE. "
            "If you genuinely need to change the frozen plan, that's a human "
            "decision, not something any command should do silently."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2) + "\n")
