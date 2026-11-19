"""Reference economy engine (the code the coder model extends).

Contract used by the rest of the program:
    EconomyModel(spec: EconomySpec, city: CitySpec)
    .stocks: dict[str, float]
    .step(population, employed_labour) -> EconomyStep   # one month; every stock change appears in the ledger
Only files under citysim/economy/ are meant to be modified by generated code.
"""
from __future__ import annotations
import math
from ..spec import CitySpec, EconomySpec
from ..ledger import Flow, EconomyStep


class EconomyModel:
    def __init__(self, spec: EconomySpec, city: CitySpec):
        self.spec = spec
        self.city = city
        self.goods = {g.id: g for g in spec.goods}
        self.sectors = sorted(spec.sectors, key=lambda s: s.order)
        self.stocks: dict[str, float] = {g.id: g.initial_stock for g in spec.goods}

    def _flow(self, ledger: list[Flow], kind: str, good: str, amount: float, sector: str | None = None) -> float:
        if amount < 0:
            amount = max(amount, -self.stocks[good])    # never draw more than exists
        if amount == 0:
            return 0.0
        self.stocks[good] += amount
        ledger.append(Flow(kind, good, amount, sector))
        return amount

    def step(self, population: float, employed_labour: float) -> EconomyStep:
        before = dict(self.stocks)
        ledger: list[Flow] = []
        status: dict[str, dict] = {}

        # 1. natural regeneration of renewable resources
        for g in self.goods.values():
            if g.regen_per_month > 0:
                room = math.inf if g.regen_cap is None else max(0.0, g.regen_cap - self.stocks[g.id])
                self._flow(ledger, "regeneration", g.id, min(g.regen_per_month, room))

        # 2a. means of production in place are a SHARED stock: when a capital good is scarce, every sector that uses it
        #     gets the same fraction of what it needs (proportional rationing). Capital is not consumed by use; it only
        #     wears out (step 5). Without this, each sector would count the whole stock as its own.
        capital_need: dict[str, float] = {}
        for s in self.sectors:
            workers = employed_labour * s.labour_share
            for good, per_worker in s.capital.items():
                capital_need[good] = capital_need.get(good, 0.0) + per_worker * workers
        capital_available = {good: (min(1.0, self.stocks[good] / need) if need > 0 else 1.0)
                             for good, need in capital_need.items()}

        # 2b. production, sector by sector in processing order
        for s in self.sectors:
            workers = employed_labour * s.labour_share
            util, limiting = 1.0, None
            if workers > 0:
                for good, per_worker in s.capital.items():       # means of production in place (shared, rationed)
                    if per_worker * workers > 0 and capital_available[good] < util:
                        util, limiting = capital_available[good], f"capital:{good}"
                for good, per_worker in s.inputs.items():        # material inputs on hand
                    need = per_worker * workers
                    if need > 0 and self.stocks[good] / need < util:
                        util, limiting = self.stocks[good] / need, f"input:{good}"
            else:
                util = 0.0
            util = max(0.0, min(1.0, util))
            for good, per_worker in s.inputs.items():
                self._flow(ledger, "input_use", good, -util * per_worker * workers, s.id)
            for good, per_worker in s.outputs.items():
                self._flow(ledger, "production", good, util * per_worker * workers, s.id)
            status[s.id] = {"workers": workers, "utilization": util, "limiting": limiting if util < 0.9999 else None}

        # 3. food: what was produced this month is all there is
        food_goods = [g for g in self.goods.values() if g.kind == "food"]
        food_available = sum(self.stocks[g.id] * g.food_units for g in food_goods)
        eaten = min(population, food_available)
        if food_available > 0 and eaten > 0:
            frac = eaten / food_available
            for g in food_goods:
                self._flow(ledger, "consumption", g.id, -self.stocks[g.id] * frac)

        # 4. non-food population consumption (a shortage is recorded, never lethal)
        shortfalls: dict[str, float] = {}
        for good, per_pop in self.spec.population_consumption.items():
            want = per_pop * population
            got = -self._flow(ledger, "consumption", good, -want)
            if want - got > 1e-9:
                shortfalls[good] = want - got

        # 5. wear and decay of stocks
        for g in self.goods.values():
            if g.depreciation_rate > 0 and g.stockable:
                self._flow(ledger, "depreciation", g.id, -self.stocks[g.id] * g.depreciation_rate)

        # 6. anything that cannot be stored is lost at month end (unstored food, unused services)
        for g in self.goods.values():
            if not g.stockable and self.stocks[g.id] > 0:
                self._flow(ledger, "spoilage", g.id, -self.stocks[g.id])

        return EconomyStep(food_available, ledger, before, dict(self.stocks), status, shortfalls)
