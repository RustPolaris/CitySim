"""Structured specifications: the stable interface between conceptual model, coder model and engine."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator

GoodKind = Literal["food", "raw", "reserve", "intermediate", "capital", "consumer", "service"]


class CitySpec(BaseModel):
    name: str
    technology_level: str
    geography: str
    history: str
    population: float = Field(gt=0)
    labour_force_fraction: float = Field(gt=0, le=1)   # share of population that can work
    unemployed_share: float = Field(ge=0, lt=1)        # share of the labour force without work
    start_year: int = 1
    climate_and_resources: str = ""
    assumptions: list[str] = []


class Good(BaseModel):
    id: str
    name: str
    unit: str = "unit"
    kind: GoodKind
    initial_stock: float = Field(default=0.0, ge=0)
    regen_per_month: float = Field(default=0.0, ge=0)   # natural regeneration (units/month)
    regen_cap: float | None = None                       # stock ceiling for regeneration
    depreciation_rate: float = Field(default=0.0, ge=0, le=1)  # fraction of stock lost per month
    food_units: float = Field(default=1.0, gt=0)         # food goods: pop-months of food per unit
    notes: str = ""

    @property
    def stockable(self) -> bool:
        """Food and services cannot be carried over to the next month."""
        return self.kind not in ("food", "service")


class Sector(BaseModel):
    id: str
    name: str
    order: int                                           # processing order within a month
    labour_share: float = Field(ge=0, le=1)              # share of employed labour
    outputs: dict[str, float] = {}                       # good -> units per worker-month at full capacity
    inputs: dict[str, float] = {}                        # good -> units consumed per worker-month
    capital: dict[str, float] = {}                       # good -> units of stock required per worker
    notes: str = ""


class EconomySpec(BaseModel):
    goods: list[Good]
    sectors: list[Sector]
    population_consumption: dict[str, float] = {}        # non-food goods per pop per month (shortage never kills)
    assumptions: list[str] = []

    @model_validator(mode="after")
    def _check(self):
        gids = [g.id for g in self.goods]
        if len(set(gids)) != len(gids):
            raise ValueError("duplicate good ids")
        sids = [s.id for s in self.sectors]
        if len(set(sids)) != len(sids):
            raise ValueError("duplicate sector ids")
        known = set(gids)
        for s in self.sectors:
            for fld in (s.outputs, s.inputs, s.capital):
                for g in fld:
                    if g not in known:
                        raise ValueError(f"sector {s.id} references unknown good {g}")
        for g in self.population_consumption:
            if g not in known:
                raise ValueError(f"population_consumption references unknown good {g}")
        if self.sectors and abs(sum(s.labour_share for s in self.sectors) - 1.0) > 0.005:
            raise ValueError("sector labour shares must sum to 1.0")
        food = {g.id for g in self.goods if g.kind == "food"}
        if not food:
            raise ValueError("the economy needs at least one food good")
        if not any(set(s.outputs) & food for s in self.sectors):
            raise ValueError("no sector produces food")
        return self
