"""Monthly simulation loop: economy -> demography -> records -> collapse / horizon checks."""
from __future__ import annotations
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .demography import Demography
from .economy import EconomyModel
from .ledger import EconomyStep, check_conservation, check_state
from .spec import CitySpec, EconomySpec

HORIZON_YEARS = 1000


@dataclass
class MonthResult:
    year: int
    month: int
    population_open: float
    population_close: float
    food_available: float
    starving: float
    starvation_deaths: float
    births: float
    natural_deaths: float
    step: EconomyStep
    outcome: str | None = None      # "collapse" | "horizon" | None


class Simulation:
    def __init__(self, city: CitySpec, economy: EconomySpec, horizon_years: int = HORIZON_YEARS,
                 strict: bool = False):
        self.city, self.spec = city, economy
        self.horizon_years = horizon_years
        self.strict = strict                  # raise on ledger/state problems (used by validation)
        self.economy = EconomyModel(economy, city)
        self.demography = Demography()
        self.population = float(city.population)
        self.months = 0                       # months processed so far
        self.outcome: str | None = None
        self.final_date: tuple[int, int] | None = None
        self.last: MonthResult | None = None
        self.records: list[dict] = []         # one structured record per year
        self._reset_year()

    # ---- calendar -------------------------------------------------
    def date_of(self, months_done: int) -> tuple[int, int]:
        """(year, month) of the month with index months_done-1."""
        i = max(0, months_done - 1)
        return self.city.start_year + i // 12, i % 12 + 1

    @property
    def next_date(self) -> tuple[int, int]:
        return self.city.start_year + self.months // 12, self.months % 12 + 1

    # ---- yearly accumulation --------------------------------------
    def _reset_year(self):
        self._acc = {"pop_start": self.population, "births": 0.0, "natural_deaths": 0.0, "starvation_deaths": 0.0,
                     "food_produced": 0.0, "food_needed": 0.0, "shortage_months": 0, "months": 0,
                     "flows": defaultdict(lambda: defaultdict(float)), "util": defaultdict(float), "employed": 0.0,
                     "shortfalls": defaultdict(float)}

    def _close_year(self, year: int, partial: bool = False):
        a = self._acc
        n = max(1, a["months"])
        self.records.append({
            "year": year, "partial": partial, "months_simulated": a["months"],
            "population_start": a["pop_start"], "population_end": self.population,
            "births": a["births"], "natural_deaths": a["natural_deaths"], "starvation_deaths": a["starvation_deaths"],
            "food_produced": a["food_produced"], "food_needed": a["food_needed"],
            "food_balance": a["food_produced"] - a["food_needed"], "shortage_months": a["shortage_months"],
            "average_employed_labour": a["employed"] / n,
            "production": dict(a["flows"]["production"]), "input_use": dict(a["flows"]["input_use"]),
            "consumption": dict(a["flows"]["consumption"]), "depreciation": dict(a["flows"]["depreciation"]),
            "regeneration": dict(a["flows"]["regeneration"]), "spoilage": dict(a["flows"]["spoilage"]),
            "average_utilization": {k: v / n for k, v in a["util"].items()},
            "unmet_population_consumption": dict(a["shortfalls"]),
            "stocks_end": dict(self.economy.stocks),
        })
        self._reset_year()

    # ---- ticking --------------------------------------------------
    def tick(self) -> MonthResult:
        if self.outcome:
            raise RuntimeError("the simulation has ended")
        employed = self.population * self.city.labour_force_fraction * (1 - self.city.unemployed_share)
        pop_open = self.population
        step = self.economy.step(pop_open, employed)
        if self.strict:
            problems = check_conservation(step) + check_state(self.economy.stocks, pop_open)
            if problems:
                raise AssertionError(f"month {self.months + 1}: " + "; ".join(problems))
        d = self.demography.step(pop_open, step.food_available)
        self.population = d.new_population
        self.months += 1
        year, month = self.date_of(self.months)

        a = self._acc
        a["months"] += 1
        a["births"] += d.births
        a["natural_deaths"] += d.natural_deaths
        a["starvation_deaths"] += d.starvation_deaths
        a["food_produced"] += step.food_available
        a["food_needed"] += pop_open
        a["employed"] += employed
        a["shortage_months"] += 1 if d.starving > 0 else 0
        for f in step.ledger:
            a["flows"][f.kind][f.good] += f.amount
        for sid, st in step.sector_status.items():
            a["util"][sid] += st["utilization"]
        for g, v in step.shortfalls.items():
            a["shortfalls"][g] += v

        outcome = None
        if d.extinct:
            outcome = "collapse"
        elif self.months >= 12 * self.horizon_years:
            outcome = "horizon"
        if outcome:
            self.outcome, self.final_date = outcome, (year, month)
        if month == 12 or outcome:
            self._close_year(year, partial=(month != 12))
        res = MonthResult(year, month, pop_open, self.population, step.food_available, d.starving,
                          d.starvation_deaths, d.births, d.natural_deaths, step, outcome)
        self.last = res
        return res

    def skip_years(self, years: int) -> list[MonthResult]:
        """Process every month in sequence; stops at the actual point of collapse/horizon."""
        results = []
        for _ in range(int(years * 12)):
            results.append(self.tick())
            if self.outcome:
                break
        return results

    # ---- output ---------------------------------------------------
    def collapse_message(self) -> str | None:
        if self.outcome == "collapse":
            y, m = self.final_date
            return f"Society has collapsed! Life became unsustainable in the year {y} (month {m})."
        if self.outcome == "horizon":
            return (f"No collapse within the {self.horizon_years}-year horizon: the city was still "
                    f"sustaining {self.population:,.0f} pops.")
        return None

    def save_history(self, path: str | Path):
        Path(path).write_text(json.dumps({
            "city": self.city.name, "outcome": self.outcome,
            "final_date": self.final_date, "records": self.records}, indent=1))
