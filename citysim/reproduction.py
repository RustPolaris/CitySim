"""Reproduction check: can the starting economy replace what it uses up?

A city is the product of a history, so at month 1 it must already be reproducing itself (simple reproduction): at full
utilization with the starting workforce, the production of every good must cover what is used up each month, namely
material inputs, the wear of the capital goods held in place, and (for food) what the population eats. If it does not,
stocks decay exponentially whatever the workforce, and the city dies of an inconsistent initial condition rather than of
anything the simulation is meant to show.

Finite natural reserves are excluded on purpose: their depletion is part of what the simulation tests.

    reproduction_problems(spec, city)   imbalances as dicts, severity "error" (breaks reproduction) or "warning"
    calibrate(spec, city)               Option B: small corrections by the tool, made on a COPY; the caller decides
Calibration only touches capacity (output per worker, with inputs scaled equally) and wear rates, each by at most
`max_factor`. It never touches labour shares, goods, sectors or capital requirements.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from .spec import CitySpec, EconomySpec

EPS = 1e-9
MAX_SURPLUS = 5.0      # production above this multiple of what the economy uses is a units mistake, not an economy
TARGET = 1.05          # calibration aims for a 5% margin so rounding cannot leave a good just below balance


@dataclass
class Balance:
    good: str              # a good id, or "food" for all food goods together (in pop-months)
    supply: float          # monthly production at full utilization
    inputs: float          # monthly use as a material input by the sectors
    wear: float            # monthly wear of the capital stock the sectors require
    eaten: float           # food only: what the population eats each month
    capital: float = 0.0   # capital stock the sectors require

    @property
    def demand(self) -> float:
        return self.inputs + self.wear + self.eaten

    @property
    def short(self) -> bool:
        return self.demand > 0 and self.supply < self.demand * (1 - EPS)

    @property
    def excessive(self) -> bool:
        return self.demand > 0 and self.supply > self.demand * MAX_SURPLUS

    def message(self) -> str:
        if self.excessive:
            return (f"{self.good}: full-capacity production is {self.supply / self.demand:.0f}x what the economy uses "
                    f"({self.supply:.1f} against {self.demand:.1f} per month). Coefficients are per ONE worker-month, not "
                    "totals for the sector; lower the output per worker (or raise what uses it)")
        if self.good == "food":
            return (f"food: full-capacity production is {self.supply:.1f} pop-months/month, minus {self.inputs:.1f} used as "
                    f"input by other sectors, but the population eats {self.eaten:.1f}")
        parts = []
        if self.inputs > 0:
            parts.append(f"inputs {self.inputs:.1f}")
        if self.wear > 0:
            parts.append(f"wear of the {self.capital:.0f} units held in place {self.wear:.1f}")
        text = (f"{self.good}: the economy uses up {self.demand:.1f}/month ({', '.join(parts)}) but full-capacity "
                f"production is only {self.supply:.1f}/month")
        if self.wear > 0:
            text += "; it wears out faster than it can be replaced, so its stock will decay"
        return text


def employed_labour(city: CitySpec) -> float:
    return city.population * city.labour_force_fraction * (1 - city.unemployed_share)


def _workers(spec: EconomySpec, city: CitySpec) -> dict[str, float]:
    e = employed_labour(city)
    return {s.id: e * s.labour_share for s in spec.sectors}


def balances(spec: EconomySpec, city: CitySpec) -> list[Balance]:
    """Balances that decide whether the economy can reproduce itself (food and every good that is used up)."""
    w = _workers(spec, city)
    produced = lambda gid: sum(s.outputs.get(gid, 0.0) * w[s.id] for s in spec.sectors)
    used = lambda gid: sum(s.inputs.get(gid, 0.0) * w[s.id] for s in spec.sectors)
    food = [g for g in spec.goods if g.kind == "food"]
    out = [Balance("food", sum(g.food_units * produced(g.id) for g in food),
                   sum(g.food_units * used(g.id) for g in food), 0.0, city.population)]
    for g in spec.goods:
        if g.kind in ("reserve", "food"):
            continue
        supply = produced(g.id) + g.regen_per_month
        cap = sum(s.capital.get(g.id, 0.0) * w[s.id] for s in spec.sectors)
        wear = g.depreciation_rate * cap if g.stockable else 0.0
        inputs = used(g.id)
        # a good nobody produces and that is only used as an input is a finite stock: the gap analysis warns about it
        if inputs + wear > 0 and (supply > 0 or wear > 0):
            out.append(Balance(g.id, supply, inputs, wear, 0.0, cap))
    return out


def reproduction_problems(spec: EconomySpec, city: CitySpec) -> list[dict]:
    problems = [{"severity": "error", "good": b.good, "supply": round(b.supply, 3), "demand": round(b.demand, 3),
                 "message": b.message()} for b in balances(spec, city) if b.short or b.excessive]
    w = _workers(spec, city)
    for g in spec.goods:                                  # unmet consumption of the population is never lethal: warning
        want = spec.population_consumption.get(g.id, 0.0) * city.population
        if want > 0 and g.kind not in ("reserve", "food"):
            supply = sum(s.outputs.get(g.id, 0.0) * w[s.id] for s in spec.sectors) + g.regen_per_month
            used = sum(s.inputs.get(g.id, 0.0) * w[s.id] for s in spec.sectors)
            if supply > 0 and supply < (used + want) * (1 - EPS):
                problems.append({"severity": "warning", "good": g.id, "supply": round(supply, 3),
                                 "demand": round(used + want, 3),
                                 "message": f"{g.id}: population consumption {want:.1f}/month cannot be fully met "
                                            f"(production {supply:.1f}, other uses {used:.1f})"})
    return problems


def format_feedback(problems: list[dict]) -> str:
    errs = [p["message"] for p in problems if p["severity"] == "error"]
    return ("The economy cannot reproduce itself at full employment with the starting workforce. Fix these imbalances by "
            "changing output per worker, inputs, wear rates or capital requirements (not labour shares):\n- "
            + "\n- ".join(errs))


# ---------------------------------------------------------------- Option B: calibration by the tool
def calibrate(spec: EconomySpec, city: CitySpec, target: float = TARGET, max_factor: float = 2.0,
              max_iter: int = 80) -> tuple[EconomySpec, list[str], list[dict]]:
    """Return (calibrated copy, notes, remaining problems). Use the copy only when no error remains."""
    work = copy.deepcopy(spec)
    factor = {s.id: 1.0 for s in work.sectors}      # cumulative output scaling per sector
    orig_rate: dict[str, float] = {}
    dead: set[str] = set()
    for _ in range(max_iter):
        todo = [b for b in balances(work, city) if b.short and b.good not in dead]
        if not todo:
            break
        b = min(todo, key=lambda x: x.supply / x.demand)
        if not _fix(work, city, b, factor, orig_rate, target, max_factor):
            dead.add(b.good)
    notes = []
    goods = {g.id: g for g in work.goods}
    for gid, rate in orig_rate.items():
        if abs(goods[gid].depreciation_rate - rate) > 1e-12:
            notes.append(f"wear rate of {gid} lowered from {rate:.4g} to {goods[gid].depreciation_rate:.4g} per month")
    for sid, f in factor.items():
        if abs(f - 1.0) > 1e-9:
            notes.append(f"output per worker of {sid} raised by {100 * (f - 1):.0f}% (its inputs scaled equally)")
    return work, notes, [p for p in reproduction_problems(work, city) if p["severity"] == "error"]


def _current(work, city, good) -> Balance:
    return next(x for x in balances(work, city) if x.good == good)


def _fix(work, city, b, factor, orig_rate, target, max_factor) -> bool:
    """One correction step for balance b; returns whether anything was changed."""
    progressed = False
    g = next((x for x in work.goods if x.id == b.good), None)
    # lever 1: durability of a capital good (a physical property; creates no wealth)
    if g is not None and b.wear > 0 and g.depreciation_rate > 0 and b.capital > 0:
        orig = orig_rate.setdefault(g.id, g.depreciation_rate)
        needed = (b.supply / target - b.inputs) / b.capital
        new = max(orig / max_factor, needed)
        if new < g.depreciation_rate - 1e-12:
            g.depreciation_rate = new
            progressed = True
        b = _current(work, city, b.good)
        if b.supply >= b.demand * target * (1 - EPS):
            return progressed
    # lever 2: capacity of the producing sectors (output per worker; inputs scaled by the same factor)
    gids = {x.id for x in work.goods if x.kind == "food"} if b.good == "food" else {b.good}
    producers = [s for s in work.sectors if any(s.outputs.get(x, 0.0) > 0 for x in gids)]
    if b.supply <= 0 or not producers:
        return progressed
    f = b.demand * target / b.supply
    for s in producers:
        fs = min(f, max_factor / factor[s.id])
        if fs > 1 + 1e-9:
            s.outputs = {k: v * fs for k, v in s.outputs.items()}
            s.inputs = {k: v * fs for k, v in s.inputs.items()}
            factor[s.id] *= fs
            progressed = True
    return progressed
