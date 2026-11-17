"""Deterministic CITY.md generator from the validated specs (fallback / seed for the LLM-written documentation)."""
from __future__ import annotations
from .spec import CitySpec, EconomySpec


def build_city_doc(city: CitySpec, econ: EconomySpec) -> str:
    L = [f"# {city.name}", "",
         "## Initial conditions",
         f"- Technology: {city.technology_level}", f"- Geography: {city.geography}", f"- History: {city.history}",
         f"- Climate and resources: {city.climate_and_resources}",
         f"- Initial population: {city.population:,.0f}; labour-force fraction {city.labour_force_fraction:.0%}; unemployed share {city.unemployed_share:.0%}",
         "", "## Productive sectors (per worker-month at full capacity)"]
    for s in sorted(econ.sectors, key=lambda x: x.order):
        f = lambda d: ", ".join(f"{k} {v:g}" for k, v in d.items()) or "none"
        L += [f"- **{s.name}** ({s.labour_share:.0%} of employed labour, step {s.order})",
              f"  - means of production required: {f(s.capital)}", f"  - inputs: {f(s.inputs)}", f"  - outputs: {f(s.outputs)}"]
    L += ["", "## Goods and resource dependencies"]
    for g in econ.goods:
        bits = [g.kind, g.unit]
        if g.initial_stock: bits.append(f"initial stock {g.initial_stock:,.0f}")
        if g.regen_per_month: bits.append(f"regenerates {g.regen_per_month:,.0f}/month")
        if g.depreciation_rate: bits.append(f"wears/spoils {g.depreciation_rate:.2%}/month")
        if not g.stockable: bits.append("cannot be stored")
        L.append(f"- {g.name} ({g.id}): " + ", ".join(bits))
    L += ["", "## Population requirements",
          "- Each pop needs one unit of food per month. Food is not stocked: each month's production is all there is.",
          "- Births 1% per year, natural deaths 0.15% per year (both on the opening monthly population).",
          "- Starvation: starving pops = max(0, population - food). Deaths = minimum of the last three monthly starvation figures; "
          "the record resets when food covers the population.",
          "- Collapse = population below one pop. The run also stops after 1,000 years (no collapse).",
          "", "## Assumptions and abstractions"]
    L += [f"- {a}" for a in city.assumptions + econ.assumptions]
    L += ["- Prototype limitation: no social actors, institutions, ideology or political organization exist in this model; "
          "the economy runs in isolation, so any analysis must not attribute outcomes to such mechanisms."]
    return "\n".join(L) + "\n"
