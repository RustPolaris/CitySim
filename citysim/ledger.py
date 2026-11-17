"""Flow ledger: every change of a stock must be explained by an explicit flow."""
from __future__ import annotations
from dataclasses import dataclass, field

FLOW_KINDS = ("production", "input_use", "regeneration", "consumption", "depreciation", "spoilage", "transfer")


@dataclass
class Flow:
    kind: str
    good: str
    amount: float          # signed change of the stock
    sector: str | None = None


@dataclass
class EconomyStep:
    food_available: float
    ledger: list[Flow]
    before: dict[str, float]
    after: dict[str, float]
    sector_status: dict[str, dict] = field(default_factory=dict)   # workers, utilization, limiting factor
    shortfalls: dict[str, float] = field(default_factory=dict)     # unmet population consumption


def check_conservation(step: EconomyStep, tol: float = 1e-6) -> list[str]:
    """Return a list of problems; empty means every stock change is explained by flows."""
    problems = []
    net: dict[str, float] = {}
    for f in step.ledger:
        net[f.good] = net.get(f.good, 0.0) + f.amount
    for good in set(step.before) | set(step.after) | set(net):
        delta = step.after.get(good, 0.0) - step.before.get(good, 0.0)
        explained = net.get(good, 0.0)
        scale = max(1.0, abs(step.before.get(good, 0.0)), abs(step.after.get(good, 0.0)))
        if abs(delta - explained) > tol * scale:
            problems.append(f"unexplained change of {good}: stock moved {delta:.6g}, flows explain {explained:.6g}")
    return problems


def check_state(stocks: dict[str, float], population: float) -> list[str]:
    problems = []
    for g, v in stocks.items():
        if v != v or v in (float("inf"), float("-inf")):
            problems.append(f"invalid stock value for {g}: {v}")
        elif v < -1e-9:
            problems.append(f"negative stock for {g}: {v}")
    if population != population or population < 0:
        problems.append(f"invalid population: {population}")
    return problems
