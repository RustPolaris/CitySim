"""Population dynamics: natural births/deaths and the three-month starvation rule (brief v0.5, 11.7).

No individual pops are tracked. Only the starvation figures of the last three months are kept.
"""
from __future__ import annotations
from dataclasses import dataclass, field

BIRTH_RATE_YEAR = 0.01      # 1% per year
DEATH_RATE_YEAR = 0.0015    # 0.15% per year (natural deaths only)
EXTINCTION_THRESHOLD = 1.0  # a population below one pop is treated as zero


@dataclass
class DemographyResult:
    starving: float
    starvation_deaths: float
    births: float
    natural_deaths: float
    new_population: float
    extinct: bool


@dataclass
class Demography:
    birth_rate_year: float = BIRTH_RATE_YEAR
    death_rate_year: float = DEATH_RATE_YEAR
    extinction_threshold: float = EXTINCTION_THRESHOLD
    history: list[float] = field(default_factory=list)  # starvation figures, at most 3

    def step(self, population: float, food: float) -> DemographyResult:
        """Advance one month. `population` is the opening population, `food` the food available."""
        starving = max(0.0, population - food)
        if starving <= 0:
            self.history = []                       # shortage ended: nothing keeps accumulating
        else:
            self.history = (self.history + [starving])[-3:]
        deaths = min(self.history) if len(self.history) == 3 else 0.0
        deaths = min(deaths, population)
        self.history = [h - deaths for h in self.history]   # never count the same deaths twice
        births = population * self.birth_rate_year / 12
        natural = population * self.death_rate_year / 12     # both on the same opening population
        new_pop = max(0.0, population + births - natural - deaths)
        extinct = new_pop < self.extinction_threshold
        if extinct:
            new_pop = 0.0
        return DemographyResult(starving, deaths, births, natural, new_pop, extinct)
