"""Landscape sheet (brief 13.3 to 13.5, 14.9 step 1): the land the city was founded on, decided by code.

The sheet is the structured, random part of the environment. The LLM later writes prose inside it and cannot contradict it.
Everything here is deterministic: the same seed and tables always give the same sheet, and every draw is keyed by
(seed, attempt, purpose, id), so extending a table does not change the draws of the entries that were already there.

Two layers (13.4): the FULL layer is the JSON sheet (plus the LLM's `description`, filled in later); the CONDENSED layer
is a fixed-order text with a length cap, built by code, so nothing is lost by a small model's summarising.

Meaning of the numbers (the solver of 14.7 interprets them once the economy's scale is known):
  richness            0..1 within the whole range of the table, drives the tier
  reserve_years       finite resources: how many years the deposit lasts at the DESIGN extraction rate, i.e. the rate the
                      solved economy needs at the start. The solver sets stock = design rate x reserve_years.
  regeneration_ratio  renewable resources: natural renewal as a share of the design extraction rate; below 1 means that
                      the design level of use slowly wears the resource down.
Hazards are recorded only (kind, severity, return period); the simulation does not use them yet.

    python -m citysim.landscape SEED [--name NAME] [--climate ID] [--terrain ID] [--out DIR]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DATA_DIR = Path(__file__).parent / "data"
TIERS = ("scarce", "modest", "ample", "rich")
TIER_LIMITS = (0.25, 0.55, 0.80)        # richness below each limit gives the tier at the same index
MIN_FOOD_RICHNESS = 0.25                # a founding site needs at least one food source of this richness
MAX_ATTEMPTS = 200


def tier_of(richness: float) -> str:
    for limit, name in zip(TIER_LIMITS, TIERS):
        if richness < limit:
            return name
    return TIERS[-1]


# ---------------------------------------------------------------- tables (hand-written data files)
class Climate(BaseModel):
    id: str
    name: str
    temperature: str = ""
    rainfall: str = ""
    weight: float = Field(default=1.0, ge=0)


class Terrain(BaseModel):
    id: str
    name: str
    weight: float = Field(default=1.0, ge=0)
    climate_mult: dict[str, float] = {}


class WaterFeature(BaseModel):
    id: str
    name: str
    weight: float = Field(default=1.0, ge=0)
    climate_mult: dict[str, float] = {}
    terrain_mult: dict[str, float] = {}


class HazardType(BaseModel):
    id: str
    name: str
    base: float = Field(ge=0)
    climate_mult: dict[str, float] = {}
    terrain_mult: dict[str, float] = {}
    water_mult: dict[str, float] = {}
    return_years: tuple[float, float]            # typical return period; the more severe, the rarer


class ResourceType(BaseModel):
    id: str
    name: str
    kind: Literal["renewable", "finite"]
    base: float = Field(ge=0)                    # base chance of being present; products of the multipliers may exceed 1
    climate_mult: dict[str, float] = {}
    terrain_mult: dict[str, float] = {}
    water_mult: dict[str, float] = {}            # the best multiplier among the water features present applies
    requires_water: list[str] = []               # absent unless at least one of these water features is present
    tags: list[str] = []                         # later systems read these (e.g. "food_source", "ore", "fuel")
    reserve_years: tuple[float, float] | None = None
    regeneration_ratio: tuple[float, float] | None = None
    note: str = ""

    @model_validator(mode="after")
    def _ranges(self):
        rng = self.reserve_years if self.kind == "finite" else self.regeneration_ratio
        if rng is None:
            raise ValueError(f"resource {self.id}: a {self.kind} resource needs "
                             f"{'reserve_years' if self.kind == 'finite' else 'regeneration_ratio'}")
        if not (0 < rng[0] <= rng[1]):
            raise ValueError(f"resource {self.id}: range {rng} must be positive and ordered")
        return self


class Tables(BaseModel):
    climates: list[Climate]
    terrains: list[Terrain]
    water: list[WaterFeature]
    hazards: list[HazardType]
    resources: list[ResourceType]

    @model_validator(mode="after")
    def _cross_references(self):
        sets = {"climate": {c.id for c in self.climates}, "terrain": {t.id for t in self.terrains},
                "water": {w.id for w in self.water}}
        for label, items in (("climates", self.climates), ("terrains", self.terrains), ("water", self.water),
                             ("hazards", self.hazards), ("resources", self.resources)):
            ids = [i.id for i in items]
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate ids in {label}")
            if not items:
                raise ValueError(f"table {label} is empty")
        for label, items in (("terrain", self.terrains), ("water", self.water), ("hazard", self.hazards),
                             ("resource", self.resources)):
            for item in items:
                for field, kind in (("climate_mult", "climate"), ("terrain_mult", "terrain"), ("water_mult", "water")):
                    for key, val in getattr(item, field, {}).items():
                        if key not in sets[kind]:
                            raise ValueError(f"{label} {item.id}: {field} names unknown {kind} '{key}'")
                        if val < 0:
                            raise ValueError(f"{label} {item.id}: {field}[{key}] is negative")
        for r in self.resources:
            for key in r.requires_water:
                if key not in sets["water"]:
                    raise ValueError(f"resource {r.id}: requires_water names unknown water feature '{key}'")
        if not any("food_source" in r.tags for r in self.resources):
            raise ValueError("no resource is tagged 'food_source': no site could ever be viable")
        return self

    def resource(self, rid: str) -> ResourceType:
        return next(r for r in self.resources if r.id == rid)


@lru_cache(maxsize=1)
def _default_tables() -> Tables:
    return load_tables()


def load_tables(env_path: str | Path | None = None, resources_path: str | Path | None = None) -> Tables:
    """Read the hand-written tables (JSON). Add entries to the files to extend the world; a bad entry is rejected here."""
    env = json.loads(Path(env_path or DATA_DIR / "environment.json").read_text(encoding="utf-8"))
    res = json.loads(Path(resources_path or DATA_DIR / "resources.json").read_text(encoding="utf-8"))
    return Tables(climates=env["climates"], terrains=env["terrains"], water=env["water"], hazards=env["hazards"],
                  resources=res["resources"])


def default_tables() -> Tables:
    return _default_tables()


# ---------------------------------------------------------------- the sheet
class Deposit(BaseModel):
    id: str
    kind: Literal["renewable", "finite"]
    tier: str
    richness: float
    reserve_years: float | None = None
    regeneration_ratio: float | None = None


class HazardEvent(BaseModel):
    id: str
    severity: Literal["mild", "moderate", "severe"]
    return_years: int


class Landscape(BaseModel):
    name: str = ""
    seed: str
    attempt: int = 1                      # how many draws it took to get a viable site (1 = the first)
    climate: str
    terrain: str
    water: list[str]
    hazards: list[HazardEvent] = []
    resources: list[Deposit] = []         # only the resources that are present
    description: str = ""                 # prose, written by the LLM inside this sheet (later stage)

    def resource(self, rid: str) -> Deposit | None:
        return next((d for d in self.resources if d.id == rid), None)

    def has(self, rid: str, min_tier: str = "scarce") -> bool:
        d = self.resource(rid)
        return d is not None and TIERS.index(d.tier) >= TIERS.index(min_tier)

    def with_tag(self, tag: str, tables: Tables | None = None) -> list[Deposit]:
        t = tables or default_tables()
        return [d for d in self.resources if tag in t.resource(d.id).tags]

    def finite(self) -> list[Deposit]:
        return [d for d in self.resources if d.kind == "finite"]


# ---------------------------------------------------------------- generation
def _rng(seed: str, *parts) -> random.Random:
    digest = hashlib.sha256("|".join([seed, *map(str, parts)]).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("no option has a positive weight")
    x = rng.random() * total
    for key, w in weights.items():
        x -= w
        if x < 0:
            return key
    return next(reversed(weights))


def _lerp(lo: float, hi: float, t: float) -> float:
    return lo + (hi - lo) * t


def _draw(seed: str, attempt: int, tables: Tables, climate_id: str | None, terrain_id: str | None) -> Landscape:
    climate = climate_id or _pick(_rng(seed, attempt, "climate"), {c.id: c.weight for c in tables.climates})
    terrain = terrain_id or _pick(_rng(seed, attempt, "terrain"),
                                  {t.id: t.weight * t.climate_mult.get(climate, 1.0) for t in tables.terrains})
    # water features: one, sometimes two or three, without repetition; at least one so that the site has water
    rng = _rng(seed, attempt, "water")
    count = 1 + (rng.random() < 0.45) + (rng.random() < 0.15)
    pool = {w.id: w.weight * w.climate_mult.get(climate, 1.0) * w.terrain_mult.get(terrain, 1.0) for w in tables.water}
    water: list[str] = []
    for _ in range(count):
        live = {k: v for k, v in pool.items() if v > 0 and k not in water}
        if not live:
            break
        water.append(_pick(rng, live))
    if not water:
        raise ValueError("the tables leave this climate and terrain with no possible water feature")

    hazards = []
    for h in tables.hazards:
        r = _rng(seed, attempt, "hazard", h.id)
        score = h.base * h.climate_mult.get(climate, 1.0) * h.terrain_mult.get(terrain, 1.0) \
            * max(h.water_mult.get(w, 1.0) for w in water)
        if r.random() < min(1.0, score):
            u = r.random()                                # one draw gives both severity and rarity
            hazards.append(HazardEvent(id=h.id, severity="mild" if u < 0.5 else "moderate" if u < 0.85 else "severe",
                                       return_years=round(_lerp(h.return_years[0], h.return_years[1], u))))

    deposits = []
    for res in tables.resources:
        if res.requires_water and not set(res.requires_water) & set(water):
            continue
        r = _rng(seed, attempt, "resource", res.id)
        score = res.base * res.climate_mult.get(climate, 1.0) * res.terrain_mult.get(terrain, 1.0) \
            * max(res.water_mult.get(w, 1.0) for w in water)
        if r.random() >= min(1.0, score):
            continue
        richness = r.random() ** (1.0 / min(3.0, max(0.3, score)))      # a favourable setting pushes richness up
        if res.kind == "finite":
            d = Deposit(id=res.id, kind="finite", tier=tier_of(richness), richness=round(richness, 3),
                        reserve_years=round(_lerp(*res.reserve_years, richness)))
        else:
            d = Deposit(id=res.id, kind="renewable", tier=tier_of(richness), richness=round(richness, 3),
                        regeneration_ratio=round(_lerp(*res.regeneration_ratio, richness), 3))
        deposits.append(d)
    return Landscape(seed=seed, attempt=attempt, climate=climate, terrain=terrain, water=water,
                     hazards=hazards, resources=deposits)


def viable(sheet: Landscape, tables: Tables) -> bool:
    """A city can only be founded where somebody can eat: at least one food source of modest richness or better."""
    return any(d.richness >= MIN_FOOD_RICHNESS for d in sheet.with_tag("food_source", tables))


def generate_landscape(seed: int | str, name: str = "", tables: Tables | None = None,
                       climate: str | None = None, terrain: str | None = None) -> Landscape:
    """Random landscape for a city. Rejected draws (no food source) are redrawn with the next attempt number."""
    t = tables or default_tables()
    if climate and climate not in {c.id for c in t.climates}:
        raise ValueError(f"unknown climate '{climate}'")
    if terrain and terrain not in {x.id for x in t.terrains}:
        raise ValueError(f"unknown terrain '{terrain}'")
    key = str(seed)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        sheet = _draw(key, attempt, t, climate, terrain)
        if viable(sheet, t):
            sheet.name = name
            return sheet
    raise RuntimeError(f"no viable landscape in {MAX_ATTEMPTS} draws (climate={climate}, terrain={terrain}); "
                       "the forced settings leave no food source")


# ---------------------------------------------------------------- layers
def _hazard_text(h: HazardEvent, t: Tables) -> str:
    name = next(x.name for x in t.hazards if x.id == h.id)
    return f"{name} ({h.severity}, about 1 year in {h.return_years})"


def condensed(sheet: Landscape, tables: Tables | None = None, max_chars: int = 600) -> str:
    """Condensed layer: fixed order of fields, built by code, cut to max_chars by dropping the least important first."""
    t = tables or default_tables()
    cl = next(c for c in t.climates if c.id == sheet.climate)
    te = next(x for x in t.terrains if x.id == sheet.terrain)
    wn = {w.id: w.name for w in t.water}
    ren = sorted((d for d in sheet.resources if d.kind == "renewable"), key=lambda d: -d.richness)
    fin = sorted((d for d in sheet.finite()), key=lambda d: -d.richness)
    absent = [r.name for r in t.resources if sheet.resource(r.id) is None
              and not (r.requires_water and not set(r.requires_water) & set(sheet.water))]
    haz = sorted(sheet.hazards, key=lambda h: {"severe": 0, "moderate": 1, "mild": 2}[h.severity])

    def build(n_ren: int, n_fin: int, n_haz: int, show_absent: bool) -> str:
        nm = lambda rid: t.resource(rid).name
        parts = [f"Climate: {cl.name} ({', '.join(x for x in (cl.temperature, cl.rainfall) if x)}). Terrain: {te.name}. "
                 f"Water: {', '.join(wn[w] for w in sheet.water)}."]
        r = [f"{nm(d.id)} ({d.tier})" for d in ren[:n_ren]]
        if len(ren) > n_ren:
            r.append(f"+{len(ren) - n_ren} more")
        parts.append("Renewable: " + (", ".join(r) or "none") + ".")
        f = [f"{nm(d.id)} ({d.tier}, about {d.reserve_years:.0f} years)" for d in fin[:n_fin]]
        if len(fin) > n_fin:
            f.append(f"+{len(fin) - n_fin} more")
        parts.append("Finite: " + (", ".join(f) or "none") + ".")
        if haz:
            h = [_hazard_text(x, t) for x in haz[:n_haz]]
            if len(haz) > n_haz:
                h.append(f"+{len(haz) - n_haz} more")
            parts.append("Hazards: " + ", ".join(h) + ".")
        if show_absent and absent:
            parts.append("Absent: " + ", ".join(absent) + ".")
        return " ".join(parts)

    for n_ren, n_fin, n_haz, show_absent in ((99, 99, 99, True), (99, 99, 99, False), (99, 99, 3, False),
                                             (99, 6, 3, False), (5, 5, 2, False), (3, 3, 1, False), (2, 2, 1, False)):
        text = build(n_ren, n_fin, n_haz, show_absent)
        if len(text) <= max_chars:
            return text
    return build(1, 1, 0, False)[:max_chars]


def full_text(sheet: Landscape, tables: Tables | None = None) -> str:
    """Full layer as readable text: the whole sheet plus the LLM's prose, when it has been written."""
    t = tables or default_tables()
    lines = [f"Landscape sheet{' of ' + sheet.name if sheet.name else ''} (seed {sheet.seed}, draw {sheet.attempt})",
             condensed(sheet, t, max_chars=10_000), "", "Resources present:"]
    for d in sorted(sheet.resources, key=lambda d: -d.richness):
        extra = (f"lasts about {d.reserve_years:.0f} years at the design rate" if d.kind == "finite"
                 else f"renews at {d.regeneration_ratio:.2f} of the design rate")
        lines.append(f"- {t.resource(d.id).name}: {d.kind}, {d.tier} (richness {d.richness:.2f}); {extra}")
    if sheet.description:
        lines += ["", sheet.description]
    return "\n".join(lines)


def save_landscape(sheet: Landscape, directory: str | Path, tables: Tables | None = None) -> list[Path]:
    """landscape.json (full layer), landscape.md (readable full layer), landscape_condensed.txt (condensed layer)."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = [d / "landscape.json", d / "landscape.md", d / "landscape_condensed.txt"]
    out[0].write_text(sheet.model_dump_json(indent=1), encoding="utf-8")
    out[1].write_text(full_text(sheet, tables), encoding="utf-8")
    out[2].write_text(condensed(sheet, tables), encoding="utf-8")
    return out


def load_landscape(directory: str | Path) -> Landscape:
    return Landscape.model_validate_json((Path(directory) / "landscape.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate a landscape sheet")
    ap.add_argument("seed")
    ap.add_argument("--name", default="")
    ap.add_argument("--climate")
    ap.add_argument("--terrain")
    ap.add_argument("--out", help="directory to save landscape.json, landscape.md and landscape_condensed.txt")
    a = ap.parse_args()
    sheet = generate_landscape(a.seed, a.name, climate=a.climate, terrain=a.terrain)
    print(full_text(sheet))
    if a.out:
        save_landscape(sheet, a.out)
        print(f"\nsaved to {a.out}")
