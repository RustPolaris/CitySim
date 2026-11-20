"""Final analytical report written by a fresh LLM from the saved city data (brief 11.8)."""
from __future__ import annotations
import json
from pathlib import Path

REPORT_SYSTEM = """You write a concise analytical report on a simulated city, with a Marxist analysis grounded ONLY in the
information provided. Use exactly these three headings:
1. Modeled facts: the society, its economy and what happened, using ONLY numbers from "Key figures" and the sampled table.
2. Interpretation: a Marxist analysis of the material relations the model represents (production, means of production,
   labour, reproduction of the population, depletion of reserves).
3. Explanation: the material and economic processes that led to collapse, or, if the city survived, what kept it
   materially sustainable and the limits of that finding.
Rules: copy numbers exactly, never invent or recompute figures. Population growth and food are given; do not describe
food as stocked or wasted (food cannot be stored in this model). The simulation contains no social actors, institutions,
ideology, political organization or changing social relations: say so, and do not attribute outcomes to anything the
simulation never represented. Do not give recommendations."""


def digest(records: list[dict], rows: int = 12) -> dict:
    """Facts computed by code, so the model does not have to read or total long tables (a 7B model does this badly)."""
    if not records:
        return {"key_figures": {}, "sampled_years": []}
    pops = [r["population_end"] for r in records]
    first, last = records[0], records[-1]
    lo, hi = min(range(len(pops)), key=pops.__getitem__), max(range(len(pops)), key=pops.__getitem__)
    ratio = lambda r: round(r["food_produced"] / r["food_needed"], 3) if r["food_needed"] else None
    key = {
        "years_simulated": len(records), "first_year": first["year"], "last_year": last["year"],
        "population_start": round(first["population_start"], 1), "population_end": round(last["population_end"], 1),
        "population_lowest": [round(pops[lo], 1), records[lo]["year"]], "population_highest": [round(pops[hi], 1), records[hi]["year"]],
        "growth_factor_over_run": round(last["population_end"] / first["population_start"], 3) if first["population_start"] else None,
        "total_starvation_deaths": round(sum(r["starvation_deaths"] for r in records), 1),
        "years_with_a_food_shortage_month": sum(1 for r in records if r["shortage_months"] > 0),
        "food_produced_over_needed_first_year": ratio(first), "food_produced_over_needed_last_year": ratio(last),
    }
    step = max(1, -(-len(records) // rows))
    idx = sorted(set(range(0, len(records), step)) | {len(records) - 1})
    sampled = []
    for i in idx:
        r = records[i]
        util = r.get("average_utilization") or {}
        tight = min(util.items(), key=lambda kv: kv[1]) if util else None
        sampled.append({"year": r["year"], "population": round(r["population_end"], 1), "food_produced_over_needed": ratio(r),
                        "shortage_months": r["shortage_months"], "starvation_deaths": round(r["starvation_deaths"], 1),
                        "least_utilized_sector": [tight[0], round(tight[1], 3)] if tight else None,
                        "stocks_end": {k: round(v, 1) for k, v in (r.get("stocks_end") or {}).items()}})
    return {"key_figures": key, "sampled_years": sampled}


def build_prompt(city_dir: Path, sim) -> str:
    doc = (city_dir / "CITY.md")
    d = digest(sim.records)
    parts = ["## City specification\n" + (city_dir / "city.json").read_text(),
             "## Economic system documentation\n" + (doc.read_text() if doc.exists() else "(none; see economy.json)\n" + (city_dir / "economy.json").read_text()),
             f"## Outcome\n{sim.collapse_message()}",
             "## Key figures (computed by the program)\n" + json.dumps(d["key_figures"], indent=1),
             "## Sampled years\n" + json.dumps(d["sampled_years"])]
    return "\n\n".join(parts)


def write_report(city_dir: Path, sim, llm=None) -> Path:
    city_dir = Path(city_dir)
    out = city_dir / "report.md"
    prompt = build_prompt(city_dir, sim)
    try:
        if llm is None:
            from devtool.llm import OllamaLLM
            llm = OllamaLLM()
        text = llm.complete("report", REPORT_SYSTEM, prompt, max_tokens=4000)
        out.write_text(text)
        print(f"  Report written to {out}")
    except Exception as e:     # no API key, network, etc.
        (city_dir / "report_input.md").write_text(prompt)
        print(f"  Could not generate the LLM report ({e}). The exact input was saved to {city_dir / 'report_input.md'}.")
        return city_dir / "report_input.md"
    return out
