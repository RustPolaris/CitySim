"""Static gap detector: dead ends and unexplained inputs/outputs in an economy spec."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from .spec import EconomySpec

MIN_SECTORS = 12


@dataclass
class Gap:
    severity: str    # "error" | "warning"
    kind: str
    subject: str
    message: str


def find_gaps(spec: EconomySpec, min_sectors: int = MIN_SECTORS) -> list[dict]:
    gaps: list[Gap] = []
    produced, used = set(), set()
    for s in spec.sectors:
        produced |= {g for g, v in s.outputs.items() if v > 0}
        used |= {g for g, v in {**s.inputs, **s.capital}.items() if v > 0}
        if not s.outputs:
            gaps.append(Gap("error", "no_output", s.id, f"sector {s.id} produces nothing"))
    used |= {g for g, v in spec.population_consumption.items() if v > 0}
    order_of = {s.id: s.order for s in spec.sectors}
    for g in spec.goods:
        supplied = g.id in produced or g.initial_stock > 0 or g.regen_per_month > 0
        if g.id in used and not supplied:
            gaps.append(Gap("error", "unsupplied_input", g.id, f"{g.id} is required but never produced, regenerated or stocked"))
        if g.id in used and g.id not in produced and g.regen_per_month == 0 and g.kind != "reserve":
            gaps.append(Gap("warning", "finite_stock", g.id, f"{g.id} is consumed but only exists as an initial stock; it will run out"))
        if g.id in produced and g.id not in used and g.kind not in ("food", "consumer"):
            gaps.append(Gap("warning", "orphan_output", g.id, f"{g.id} is produced but nothing uses it"))
        if g.kind in ("capital",) and g.depreciation_rate == 0:
            gaps.append(Gap("warning", "no_wear", g.id, f"capital good {g.id} never wears out, so it never needs replacing"))
        if g.kind == "service":
            makers = [s for s in spec.sectors if g.id in s.outputs]
            for s in spec.sectors:
                if g.id in s.inputs and makers and all(order_of[m.id] > s.order for m in makers):
                    gaps.append(Gap("error", "service_order", g.id,
                                    f"service {g.id} is used by {s.id} before any sector that produces it runs this month"))
    if len(spec.sectors) < min_sectors:
        gaps.append(Gap("warning", "few_sectors", "economy", f"{len(spec.sectors)} sectors; the brief asks for at least {min_sectors}"))
    return [asdict(g) for g in gaps]
