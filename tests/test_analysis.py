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
