"""Executable validation: gaps + ledger conservation + invalid-state checks over a test run.

    python -m citysim.validate cities/demo_ford [--years 20]
Prints a JSON report; exit code 1 if there are errors.
"""
from __future__ import annotations
import argparse, json, sys, traceback
from pathlib import Path

from .analysis import find_gaps
from .simulation import Simulation
from .spec import CitySpec, EconomySpec


def load_city(path: str | Path) -> tuple[CitySpec, EconomySpec]:
    p = Path(path)
    return (CitySpec.model_validate_json((p / "city.json").read_text()),
            EconomySpec.model_validate_json((p / "economy.json").read_text()))


def run_validation(path: str | Path, years: int = 20) -> dict:
    report: dict = {"errors": [], "warnings": [], "gaps": []}
    try:
        city, econ = load_city(path)
    except Exception as e:                      # schema problems
        report["errors"].append(f"spec failed to load: {e}")
        return report
    gaps = find_gaps(econ)
    report["gaps"] = gaps
    report["errors"] += [g["message"] for g in gaps if g["severity"] == "error"]
    report["warnings"] += [g["message"] for g in gaps if g["severity"] == "warning"]
    try:
        sim = Simulation(city, econ, strict=True)
        first = sim.tick()
        cover = first.food_available / first.population_open
        if cover < 0.5:
            weak = [f"{sid} at {st['utilization']:.0%} limited by {st['limiting']}"
                    for sid, st in first.step.sector_status.items() if st["utilization"] < 0.5]
            report["errors"].append(
                f"the economy is not viable at the start: in month 1 food covers only {cover:.0%} of the population. "
                f"Sectors below half capacity: {'; '.join(weak[:8]) or 'none (food sectors simply produce too little)'}")
        sim.skip_years(years)
        report["simulated_months"] = sim.months
        report["population_after"] = sim.population
        report["outcome"] = sim.outcome
        if sim.outcome == "collapse" and sim.final_date[0] - city.start_year < years:
            report["errors"].append(f"the city collapsed in year {sim.final_date[0]}, within the {years}-year test run; "
                                    "the economy is not coherent enough to sustain it")
        report["last_utilization"] = {k: round(v["utilization"], 3) for k, v in sim.last.step.sector_status.items()} if sim.last else {}
    except Exception as e:
        report["errors"].append(f"simulation run failed: {e}")
        report["traceback"] = traceback.format_exc(limit=4)
    report["ok"] = not report["errors"]
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("city_dir")
    ap.add_argument("--years", type=int, default=20)
    a = ap.parse_args()
    r = run_validation(a.city_dir, a.years)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["ok"] else 1)
