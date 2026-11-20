"""Structured specifications: the stable interface between conceptual model, coder model and engine."""
from __future__ import annotations
from typing import Literal
import json
from pydantic import BaseModel, Field, field_validator, model_validator

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

    @field_validator("technology_level", "geography", "history", "climate_and_resources", mode="before")
    @classmethod
    def _text(cls, v):
        # small models sometimes return an object or list instead of a string
        return v if isinstance(v, str) or v is None else json.dumps(v, ensure_ascii=False)

    @field_validator("assumptions", mode="before")
    @classmethod
    def _assumptions(cls, v):
        if isinstance(v, str):
            return [v]
        return [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in (v or [])]


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

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v):
        allowed = ("food", "raw", "reserve", "intermediate", "capital", "consumer", "service")
        v = str(v).strip().lower()
        return v if v in allowed else "intermediate"     # unknown labels from small models become plain goods

    @field_validator("food_units", mode="before")
    @classmethod
    def _food_units(cls, v):
        # models fill every field; 0 or null means "not applicable", so fall back to the default of 1
        return 1.0 if v is None or v <= 0 else v

    @field_validator("regen_cap", mode="before")
    @classmethod
    def _regen_cap(cls, v):
        return None if v is None or v <= 0 else v     # 0 would silently block regeneration; treat as "no ceiling"

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
        for g in self.goods:
            if g.regen_per_month > 0 and g.kind != "reserve":
                raise ValueError(f"good {g.id}: regen_per_month is only for natural reserves (kind 'reserve'); a produced "
                                 "good such as tools or food must come from a sector's outputs, never from nothing")
        for g in self.goods:                            # food is eaten under the fixed food rule, not as consumption
            if g.kind == "food":
                self.population_consumption.pop(g.id, None)
        total = sum(s.labour_share for s in self.sectors)
        if self.sectors:
            if total <= 0:
                raise ValueError("sector labour shares must be positive")
            if abs(total - 1.0) > 1e-9:                 # models are poor at arithmetic: renormalise to exactly 1.0
                for s in self.sectors:
                    s.labour_share = s.labour_share / total
        food = {g.id for g in self.goods if g.kind == "food"}
        if not food:
            raise ValueError("the economy needs at least one food good")
        if not any(set(s.outputs) & food for s in self.sectors):
            raise ValueError("no sector produces food")
        return self
