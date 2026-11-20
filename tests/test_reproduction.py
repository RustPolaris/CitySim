import copy
import pytest
from citysim.economy import EconomyModel
from citysim.reproduction import balances, calibrate, reproduction_problems
from citysim.seeding import seed_initial_stocks
from citysim.simulation import Simulation
from citysim.spec import CitySpec, EconomySpec, Good, Sector
from citysim.validate import load_city, run_validation


def city(pop=1000.0):
    return CitySpec(name="t", technology_level="x", geography="x", history="x", population=pop,
                    labour_force_fraction=0.6, unemployed_share=0.1)


def tool_city(tool_out=0.3, capital=2.0, wear=0.01, food_out=3.0, pop=1000.0):
    """Farm + toolmaker; both need tools in place. Tools replace themselves iff 0.2 * tool_out >= wear * capital."""
    goods = [Good(id="food", name="food", kind="food"),
             Good(id="tools", name="tools", kind="capital", depreciation_rate=wear)]
    sectors = [Sector(id="farm", name="farm", order=1, labour_share=0.8, outputs={"food": food_out}, capital={"tools": capital}),
               Sector(id="smith", name="smith", order=2, labour_share=0.2, outputs={"tools": tool_out}, capital={"tools": capital})]
    c, e = city(pop), EconomySpec(goods=goods, sectors=sectors)
    seed_initial_stocks(e, c)
    return c, e


def test_scarce_capital_is_shared_not_counted_twice():
    goods = [Good(id="food", name="food", kind="food"), Good(id="tools", name="tools", kind="capital", initial_stock=100)]
    sectors = [Sector(id="a", name="a", order=1, labour_share=0.5, outputs={"food": 1.0}, capital={"tools": 1.0}),
               Sector(id="b", name="b", order=2, labour_share=0.5, outputs={"food": 1.0}, capital={"tools": 1.0})]
    step = EconomyModel(EconomySpec(goods=goods, sectors=sectors), city(200)).step(200, 200)   # 100 workers each, 200 tools needed
    assert step.sector_status["a"]["utilization"] == pytest.approx(0.5)
    assert step.sector_status["b"]["utilization"] == pytest.approx(0.5)


def test_demo_city_reproduces_itself():
    c, e = load_city("cities/demo_ford")
    assert [p for p in reproduction_problems(e, c) if p["severity"] == "error"] == []
    assert all(b.supply >= b.demand for b in balances(e, c))


def test_tools_that_wear_faster_than_they_are_made_are_flagged():
    c, e = tool_city(tool_out=0.05)
    probs = reproduction_problems(e, c)
    assert [p["good"] for p in probs if p["severity"] == "error"] == ["tools"]
    assert "wears out faster" in probs[0]["message"]


def test_calibration_makes_a_small_imbalance_reproducible_without_touching_labour_shares():
    c, e = tool_city(tool_out=0.05)                       # supply is half of the wear
    original = copy.deepcopy(e)
    fixed, notes, remaining = calibrate(e, c)
    assert remaining == [] and notes and any("tools" in n for n in notes)
    assert [s.labour_share for s in fixed.sectors] == [s.labour_share for s in original.sectors]
    assert e == original                                  # the input spec is never modified: calibration works on a copy
    seed_initial_stocks(fixed, c)
    sim = Simulation(c, fixed, strict=True)
    sim.skip_years(40)
    assert sim.outcome is None and sim.population >= 0.99 * c.population


def test_calibration_gives_up_when_the_gap_is_too_large():
    c, e = tool_city(tool_out=0.005)                      # needs about a tenfold correction
    fixed, notes, remaining = calibrate(e, c)
    assert [p["good"] for p in remaining] == ["tools"]


def test_food_shortfall_is_calibrated_through_the_food_sectors():
    c, e = tool_city(food_out=2.0)                        # food covers about 86% of the population
    assert any(p["good"] == "food" for p in reproduction_problems(e, c))
    fixed, notes, remaining = calibrate(e, c)
    assert remaining == [] and any("farm" in n for n in notes)


def test_validation_rejects_a_decaying_economy_even_if_a_few_pops_survive(tmp_path):
    c, e = tool_city(tool_out=0.01)
    (tmp_path / "city.json").write_text(c.model_dump_json())
    (tmp_path / "economy.json").write_text(e.model_dump_json())
    report = run_validation(tmp_path, years=30)
    assert not report["ok"]
    assert any("not self-reproducing" in m for m in report["errors"])
    assert any("fell to" in m for m in report["errors"])      # the behavioural guard catches it independently


def test_validation_passes_a_reproducible_economy(tmp_path):
    c, e = tool_city()
    (tmp_path / "city.json").write_text(c.model_dump_json())
    (tmp_path / "economy.json").write_text(e.model_dump_json())
    assert run_validation(tmp_path, years=10)["ok"]


def test_regeneration_is_only_for_natural_reserves():
    with pytest.raises(ValueError, match="regen_per_month"):
        EconomySpec(goods=[Good(id="food", name="f", kind="food"), Good(id="tools", name="t", kind="capital", regen_per_month=50)],
                    sectors=[Sector(id="a", name="a", order=1, labour_share=1, outputs={"food": 1})])


def test_food_in_population_consumption_is_dropped():
    e = EconomySpec(goods=[Good(id="food", name="f", kind="food")],
                    sectors=[Sector(id="a", name="a", order=1, labour_share=1, outputs={"food": 1})],
                    population_consumption={"food": 1000})
    assert e.population_consumption == {}


def test_per_worker_numbers_mistaken_for_totals_are_flagged_as_surplus():
    c, e = tool_city(food_out=500.0)                       # the mistake seen in a generated city: 500 food per farmer
    probs = reproduction_problems(e, c)
    assert any(p["good"] == "food" and "per ONE worker" in p["message"] for p in probs)
    assert calibrate(e, c)[2]                              # the tool does not "fix" this itself: it goes back to the model


def test_scale_anchors_give_the_model_per_worker_numbers():
    from devtool.prompts import scale_anchors, concept_prompt
    c = city(1000)                                          # 540 employed workers
    a = scale_anchors(c)
    assert "540" in a and "ONE worker" in a and "3.7 food" in a
    assert a in concept_prompt(1, 15, "{}", "null", "", "", a)


def test_report_digest_is_computed_by_code():
    from citysim.report import digest
    c, e = load_city("cities/demo_ford")
    sim = Simulation(c, e)
    sim.skip_years(30)
    d = digest(sim.records)
    k = d["key_figures"]
    assert k["years_simulated"] == 30 and k["population_start"] == pytest.approx(12000, rel=0.02)
    assert k["growth_factor_over_run"] > 1 and k["total_starvation_deaths"] == 0
    assert len(d["sampled_years"]) <= 14 and d["sampled_years"][-1]["year"] == k["last_year"]
