"""Starting stocks: a city begins with its tools and working stocks already in place.

Models often forget initial stocks, which deadlocks the economy (every sector needs 'machinery', nobody has any, the
machinery sector needs machinery too) and kills the city in months. This module raises initial stocks to what the
starting workforce needs for full-capacity operation. It never lowers a stock the model chose.

    python -m citysim.seeding cities/my_city      # repairs an existing economy.json in place
"""
from __future__ import annotations
import sys
from pathlib import Path
from .spec import CitySpec, EconomySpec


def seed_initial_stocks(spec: EconomySpec, city: CitySpec, input_months: float = 1.0) -> list[str]:
    employed = city.population * city.labour_force_fraction * (1 - city.unemployed_share)
    goods = {g.id: g for g in spec.goods}
    produced = {g for s in spec.sectors for g, v in s.outputs.items() if v > 0}
    need_capital: dict[str, float] = {}
    need_input: dict[str, float] = {}
    for s in spec.sectors:
        workers = employed * s.labour_share
        for g, per in s.capital.items():
            need_capital[g] = need_capital.get(g, 0.0) + per * workers
        for g, per in s.inputs.items():
            need_input[g] = need_input.get(g, 0.0) + per * workers * input_months
    notes = []
    for g, need in need_capital.items():
        good = goods[g]
        if good.stockable and good.initial_stock < need:
            notes.append(f"seeded {g}: initial stock {good.initial_stock:g} -> {need:.0f} (tools/capital the starting workforce needs)")
            good.initial_stock = round(need, 2)
    for g, need in need_input.items():
        good = goods[g]
        if good.stockable and good.kind in ("intermediate", "raw") and g in produced and good.initial_stock < need:
            notes.append(f"seeded {g}: initial stock {good.initial_stock:g} -> {need:.0f} (one month of inputs)")
            good.initial_stock = round(need, 2)
    return notes


if __name__ == "__main__":
    d = Path(sys.argv[1])
    city = CitySpec.model_validate_json((d / "city.json").read_text())
    spec = EconomySpec.model_validate_json((d / "economy.json").read_text())
    notes = seed_initial_stocks(spec, city)
    (d / "economy.json").write_text(spec.model_dump_json(indent=1))
    print("\n".join(notes) or "nothing to seed")
