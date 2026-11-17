"""Builds the hand-authored demo city (city.json + economy.json) with a self-consistent starting economy.

Output coefficients are solved so that every good starts with ~2% more production than demand. This is only the
demo seed: cities produced by the development tool come from the conceptual-model/coder rounds instead.
"""
import json
from pathlib import Path

POP, LF, UNEMP = 12000, 0.62, 0.06
EMPLOYED = POP * LF * (1 - UNEMP)
MARGIN = 1.02
DEP = {"tools": 0.012, "buildings": 0.004, "grain": 0.01, "fuel": 0.005, "timber": 0.003}

shares = dict(maintenance=.04, transport=.05, forestry=.05, mining=.04, energy=.04, metallurgy=.04, tools=.05,
              crops=.38, livestock=.10, processing=.10, textiles=.06, construction=.05)
order = list(shares)
W = {s: EMPLOYED * v for s, v in shares.items()}

# capital stock required per worker, fixed material inputs per worker, technical ratios per unit of output
cap = dict(maintenance=dict(tools=.3, buildings=.1), transport=dict(tools=.3, buildings=.1),
           forestry=dict(tools=.5, buildings=.1), mining=dict(tools=.6, buildings=.1),
           energy=dict(tools=.3, buildings=.1), metallurgy=dict(tools=.4, buildings=.1),
           tools=dict(tools=.4, buildings=.1), crops=dict(tools=.6, buildings=.1),
           livestock=dict(tools=.3, buildings=.15), processing=dict(tools=.4, buildings=.15),
           textiles=dict(tools=.3, buildings=.1), construction=dict(tools=.4, buildings=.05))
fixed = dict(maintenance=dict(fuel=.05, timber=.05), transport=dict(fuel=.10, repair_work=.02),
             forestry=dict(repair_work=.03, haulage=.05), mining=dict(repair_work=.05, haulage=.10),
             energy=dict(repair_work=.03, haulage=.10), metallurgy=dict(repair_work=.03),
             tools=dict(repair_work=.03), crops=dict(repair_work=.02, haulage=.05, soil_fertility=1.0),
             livestock=dict(grain=.8, haulage=.05), processing=dict(fuel=.25, repair_work=.03, haulage=.10),
             textiles=dict(repair_work=.02, fuel=.05), construction=dict(repair_work=.03, haulage=.10))
# per unit of the sector's main output: {input: ratio}; main output good per sector
main_out = dict(maintenance="repair_work", transport="haulage", forestry="timber", mining="ore", energy="fuel",
                metallurgy="iron", tools="tools", crops="grain", livestock="fibre", processing="food",
                textiles="clothing", construction="buildings")
ratio = dict(forestry=dict(standing_timber=1.0), mining=dict(ore_reserve=1.0), energy=dict(timber=2.0),
             metallurgy=dict(ore=2.0, fuel=1.5), tools=dict(iron=1.0, fuel=.8, timber=.3),
             processing=dict(grain=1 / 0.9), construction=dict(stone=.6, timber=.4))
extra_out = dict(mining=dict(stone=None), livestock=dict(food=1.6))   # joint products
ratio_extra = dict(mining=dict(stone_reserve=("stone", 1.0)))
POP_CONS = dict(clothing=0.02)

# ---------------- solve outputs by fixed point
x = {g: 0.0 for g in set(main_out.values()) | {"stone"}}
food_target = 1.07 * POP
livestock_food = extra_out["livestock"]["food"] * W["livestock"]
for _ in range(500):
    use = {g: 0.0 for g in x}
    use["food"] = 0
    def add(g, v):
        use[g] = use.get(g, 0.0) + v
    for s in order:
        for g, c in fixed[s].items():
            add(g, c * W[s])
        for g, r in ratio.get(s, {}).items():
            out = x[main_out[s]]
            add(g, r * out)
        if s in ratio_extra:
            for g, (og, r) in ratio_extra[s].items():
                add(g, r * x[og])
        for g, c in cap[s].items():
            pass
    req = {}                                   # capital requirement
    for s in order:
        for g, c in cap[s].items():
            req[g] = req.get(g, 0) + c * W[s]
    for g, stock in req.items():
        add(g, DEP[g] * stock + 0.0006 * stock)   # replacement + growth of labour force
    add("clothing", POP_CONS["clothing"] * POP)
    new = {}
    for g in x:
        new[g] = MARGIN * use.get(g, 0.0)
    new["grain"] = MARGIN * (use.get("grain", 0.0))
    x_food = max(0.0, food_target - livestock_food)
    x["food_from_processing"] = x_food
    if max(abs(new[g] - x[g]) for g in new) < 1e-9:
        x.update(new); break
    x.update(new)
x["food"] = max(0.0, food_target - livestock_food)   # processing food
x_proc_grain = x["food"] / 0.9
# recompute grain use with processing derived from food target
use_grain = x_proc_grain + fixed["livestock"]["grain"] * W["livestock"]
x["grain"] = MARGIN * use_grain

stocks_req = {}
for s in order:
    for g, c in cap[s].items():
        stocks_req[g] = stocks_req.get(g, 0) + c * W[s]

def pw(s, good):   # per worker
    return x[good] / W[s]

sector_specs = []
for i, s in enumerate(order, 1):
    out = {}
    inp = dict(fixed[s])
    g = main_out[s]
    if s == "processing":
        out["food"] = x["food"] / W[s]
        inp["grain"] = x["food"] / 0.9 / W[s]
    else:
        out[g] = pw(s, g)
    if s == "livestock":
        out["food"] = extra_out["livestock"]["food"]
    if s == "mining":
        out["stone"] = pw(s, "stone")
        inp["stone_reserve"] = pw(s, "stone")
    for ig, r in ratio.get(s, {}).items():
        if s == "processing":
            continue
        inp[ig] = r * pw(s, g)
    if s == "forestry":
        inp["standing_timber"] = pw(s, "timber")
    sector_specs.append(dict(id=s, name=s.replace("_", " ").title(), order=i, labour_share=shares[s],
                             outputs={k: round(v, 5) for k, v in out.items()},
                             inputs={k: round(v, 5) for k, v in inp.items()},
                             capital=cap[s]))

total_use_ore = x["ore"]
goods = [
 dict(id="repair_work", name="Repair work", kind="service", unit="work-units"),
 dict(id="haulage", name="Haulage", kind="service", unit="load-units"),
 dict(id="standing_timber", name="Standing timber", kind="reserve", unit="m3", initial_stock=round(x["timber"] * 12 * 25), regen_per_month=round(x["timber"] * 1.04, 2), regen_cap=round(x["timber"] * 12 * 25)),
 dict(id="timber", name="Timber", kind="intermediate", unit="m3", initial_stock=round(1.5 * x["timber"]), depreciation_rate=DEP["timber"]),
 dict(id="ore_reserve", name="Iron ore in the ground", kind="reserve", unit="t", initial_stock=round(total_use_ore * 12 * 110)),
 dict(id="ore", name="Iron ore", kind="intermediate", unit="t", initial_stock=round(1.5 * total_use_ore)),
 dict(id="stone_reserve", name="Quarry stone in the ground", kind="reserve", unit="m3", initial_stock=round(x["stone"] * 12 * 500)),
 dict(id="stone", name="Cut stone", kind="intermediate", unit="m3", initial_stock=round(1.5 * x["stone"])),
 dict(id="fuel", name="Charcoal", kind="intermediate", unit="t", initial_stock=round(2 * x["fuel"]), depreciation_rate=DEP["fuel"]),
 dict(id="iron", name="Iron", kind="intermediate", unit="t", initial_stock=round(1.5 * x["iron"])),
 dict(id="tools", name="Tools and machinery", kind="capital", unit="sets", initial_stock=round(stocks_req["tools"]), depreciation_rate=DEP["tools"]),
 dict(id="buildings", name="Workshops, barns and mills", kind="capital", unit="units", initial_stock=round(stocks_req["buildings"]), depreciation_rate=DEP["buildings"]),
 dict(id="soil_fertility", name="Soil fertility", kind="reserve", unit="fertility-units", initial_stock=300000, regen_per_month=round(W["crops"] * 0.93), regen_cap=300000),
 dict(id="grain", name="Grain and root crops", kind="intermediate", unit="t", initial_stock=round(1.5 * x["grain"]), depreciation_rate=DEP["grain"]),
 dict(id="fibre", name="Wool, hides and flax", kind="intermediate", unit="t", initial_stock=round(1.5 * x["fibre"])),
 dict(id="food", name="Food", kind="food", unit="pop-months"),
 dict(id="clothing", name="Clothing", kind="consumer", unit="garments", initial_stock=round(x["clothing"] * 3)),
]
# textiles consume fibre in proportion to clothing output
for s in sector_specs:
    if s["id"] == "textiles":
        s["inputs"]["fibre"] = round(0.9 * pw("textiles", "clothing"), 5)
# fibre demand drives livestock fibre output
for s in sector_specs:
    if s["id"] == "livestock":
        s["outputs"]["fibre"] = round(MARGIN * 0.9 * x["clothing"] / W["livestock"], 5)

economy = dict(goods=goods, sectors=sector_specs, population_consumption=POP_CONS,
               assumptions=["Demo seed economy: coefficients are per worker-month at full capacity.",
                            "Food and services cannot be stored; everything else wears or spoils at the stated rates.",
                            "Labour shares are fixed over time."])
city = dict(name="Ford of Valdemar", technology_level="Late medieval: charcoal, water mills, hand tools, no electricity or steam",
            geography="A river-ford town in a fertile temperate valley with forested hills and an iron-bearing ridge",
            history="Founded generations ago at a river crossing; grew around a market and the nearby ironworks",
            population=POP, labour_force_fraction=LF, unemployed_share=UNEMP, start_year=1,
            climate_and_resources="Temperate, reliable rain; one iron ore deposit of finite size; renewable woodland",
            assumptions=["Demo city written by hand for testing; not generated by the conceptual model."])
here = Path(__file__).parent
(here / "city.json").write_text(json.dumps(city, indent=1))
(here / "economy.json").write_text(json.dumps(economy, indent=1))
print("workers", {k: round(v) for k, v in W.items()})
print("outputs", {k: round(v, 1) for k, v in x.items()})
