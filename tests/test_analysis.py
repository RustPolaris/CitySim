import copy
from citysim.analysis import find_gaps
from citysim.spec import EconomySpec
from citysim.validate import load_city, run_validation

CITY, ECON = load_city("cities/demo_ford")


def kinds(spec):
    return {g["kind"] for g in find_gaps(spec)}


def test_demo_has_no_gaps():
    assert find_gaps(ECON) == []


def test_unsupplied_input_detected():
    spec = copy.deepcopy(ECON)
    spec.goods.append(type(spec.goods[0])(id="mystery", name="Mystery", kind="intermediate"))
    spec.sectors[0].inputs["mystery"] = 1.0
    assert "unsupplied_input" in kinds(spec)


def test_service_used_before_produced_detected():
    spec = copy.deepcopy(ECON)
    for s in spec.sectors:
        if s.id == "maintenance":
            s.order = 99
    assert "service_order" in kinds(spec)


def test_few_sectors_warning():
    spec = EconomySpec(goods=[ECON.goods[-3]] if False else [g for g in ECON.goods if g.id in ("food", "grain", "tools")],
                       sectors=[type(ECON.sectors[0])(id="farm", name="Farm", order=1, labour_share=1.0, outputs={"food": 1.0})])
    assert "few_sectors" in kinds(spec)


def test_validation_report_for_demo_is_ok():
    assert run_validation("cities/demo_ford", years=5)["ok"]


def test_lenient_parsing_of_small_model_output():
    import json
    from citysim.spec import CitySpec
    raw = json.loads(open("cities/demo_ford/economy.json").read())
    raw["goods"][0]["food_units"] = 0                      # not applicable
    raw["goods"][2]["regen_cap"] = 0
    for s in raw["sectors"]:
        s["labour_share"] *= 0.9                           # shares no longer sum to 1
    spec = EconomySpec.model_validate(raw)
    assert spec.goods[0].food_units == 1.0 and spec.goods[2].regen_cap is None
    assert abs(sum(s.labour_share for s in spec.sectors) - 1.0) < 1e-9
    c = json.loads(open("cities/demo_ford/city.json").read())
    c["climate_and_resources"] = {"climate": "temperate"}
    assert "temperate" in CitySpec.model_validate(c).climate_and_resources


def test_unknown_good_kind_becomes_intermediate():
    from citysim.spec import Good
    assert Good(id="x", name="X", kind="material").kind == "intermediate"


def test_dead_economy_is_flagged_and_seeding_repairs_it(tmp_path):
    import json, shutil
    from citysim.seeding import seed_initial_stocks
    d = tmp_path / "c"
    shutil.copytree("cities/demo_ford", d)
    econ = json.loads((d / "economy.json").read_text())
    for g in econ["goods"]:
        if g["id"] in ("tools", "buildings"):
            g["initial_stock"] = 0                      # the failure seen with small models: no machinery at start
    (d / "economy.json").write_text(json.dumps(econ))
    rep = run_validation(d, years=3)
    assert not rep["ok"] and any("not viable" in e for e in rep["errors"])
    spec = EconomySpec.model_validate(econ)
    assert seed_initial_stocks(spec, CITY)
    (d / "economy.json").write_text(spec.model_dump_json())
    assert run_validation(d, years=3)["ok"]
