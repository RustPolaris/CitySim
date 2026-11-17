import copy
import pytest
from citysim.simulation import Simulation
from citysim.spec import CitySpec, EconomySpec
from citysim.validate import load_city
from citysim.ledger import check_conservation

CITY, ECON = load_city("cities/demo_ford")


def make(econ=None, **kw):
    return Simulation(CITY, econ or ECON, **kw)


def test_conservation_and_valid_state_every_month():
    sim = make(strict=True)                    # raises on any unexplained stock change or invalid state
    sim.skip_years(25)
    assert sim.months == 300 and sim.outcome is None


def test_timeskip_processes_every_month_and_records_each_year():
    sim = make()
    results = sim.skip_years(3)
    assert len(results) == 36 and sim.months == 36
    assert [r["year"] for r in sim.records] == [1, 2, 3]


def test_food_is_not_stocked():
    sim = make()
    sim.tick()
    assert sim.economy.stocks["food"] == 0


def test_collapse_stops_at_exact_month_and_records_partial_year():
    dead = copy.deepcopy(ECON)
    for s in dead.sectors:
        if "food" in s.outputs:
            s.outputs["food"] = 0.0
    sim = Simulation(CITY, dead, strict=True)
    results = sim.skip_years(100)
    assert sim.outcome == "collapse"
    assert results[-1].outcome == "collapse" and len(results) == sim.months < 1200
    assert sim.population == 0
    assert sim.records[-1]["partial"] in (True, False)
    assert "Society has collapsed" in sim.collapse_message()
    with pytest.raises(RuntimeError):
        sim.tick()


def test_horizon_ends_run_without_collapse():
    sim = make(horizon_years=2)
    sim.skip_years(10)
    assert sim.outcome == "horizon" and sim.months == 24
    assert "No collapse" in sim.collapse_message()


def test_demo_city_eventually_collapses_through_material_depletion():
    sim = make(strict=True)
    sim.skip_years(1000)
    assert sim.outcome == "collapse"
    assert sim.final_date[0] > 50              # not instant: the iron deposit/soil run down over decades
