"""Prompts for the conceptual, coder and analysis models."""
import json
from citysim.spec import EconomySpec

RULES = """Fixed rules of the simulation (do not contradict them):
- Monthly tick. Population: births 1%/yr, natural deaths 0.15%/yr. Each pop needs 1 unit of food per month.
- Food is NOT stocked: only the food produced in a month exists that month. Services are not stored either.
- Only a share of the population works (labour_force_fraction), minus an unemployed share. Employed labour is split
  across sectors by fixed percentage shares (they must sum to 1.0). Food comes from the food-related sectors.
- The economy must contain at least twelve sectors by the end of construction (crop agriculture, livestock/fisheries,
  food processing, forestry, mining/quarrying, energy/fuels, metallurgy, tools/machinery, textiles, construction,
  transport/trade, maintenance/services are the default list; adapt to the technological level).
- Production coefficients are per worker-month at full capacity. Wealth cannot appear without inputs: every output
  needs inputs, means of production (capital stocks that wear out) or natural reserves/regeneration.
- The starting economy must reproduce itself (the city has a history): at full employment, for every good the monthly
  production must cover its monthly use as an input, the wear of the capital held in place (depreciation_rate x capital
  required by the sectors, summed over sectors) and, for food, the population's needs. Example: if the sectors need 1000
  tools in place and tools wear at 1%/month, the tool sector must make at least 10 tools per month. Never rely on
  starting stocks to cover a permanent shortfall. Finite natural reserves are the only exception.
- Do NOT model social actors, institutions, politics, ideology or classes: the prototype is economy-only.
- Keep physical goods and units separate; never treat incommensurable quantities as interchangeable."""

CITY_SYSTEM = "You are the conceptual model of an economic-simulation design tool. Reply with one JSON object only.\n" + RULES

CITY_PROMPT = """Invent a simple city. Choose its technological level and broad productive capabilities, the geography and
environment of its surroundings, a vague historical context, a realistic population (your choice, no imposed range), a
labour_force_fraction, an unemployed_share (arbitrary but plausible), and other initial conditions that constrain its
economy (climate, land, water, raw materials). {hint}
Reply with a JSON object with exactly these keys: name, technology_level, geography, history, population (number),
labour_force_fraction (0-1), unemployed_share (0-1), start_year (integer), climate_and_resources, assumptions (list of strings)."""

CONCEPT_SYSTEM = "You are the conceptual model of an economic-simulation design tool. Reply with one JSON object only.\n" + RULES


def scale_anchors(city) -> str:
    """Numbers computed by code so the model cannot confuse per-worker coefficients with sector totals."""
    employed = city.population * city.labour_force_fraction * (1 - city.unemployed_share)
    half = employed / 2
    return (f"Scale of this city: population {city.population:,.0f}; employed workers {employed:,.0f}. A sector with "
            f"labour_share s has employed x s workers. EVERY coefficient (outputs, inputs, capital) is per ONE worker, "
            f"never a total for the sector. Reference: the population eats {city.population:,.0f} food per month; if the "
            f"food sectors together held half of the workers ({half:,.0f}), each of them would have to yield about "
            f"{city.population / half:.1f} food per month, so food outputs of dozens or hundreds per worker are wrong. "
            "Capital in place is a few units per worker, not tens or hundreds. Only natural reserves may regenerate.")


def concept_prompt(n, total, city_json, prev_spec_json, decisions, feedback, anchors=""):
    schema = json.dumps(EconomySpec.model_json_schema())
    first = prev_spec_json is None
    task = ("Describe the city's initial economic starting point: productive organization, principal sectors, available "
            "resources and the basic relationships through which the population reproduces its material life."
            if first else
            "Continue developing the economy, taking account of the city specification and the system already represented. "
            "EXTEND the existing economy (keep ids stable, do not silently replace earlier assumptions).")
    return f"""Round {n} of about {total}.
{task}

City specification:
{city_json}

{anchors}

Current economy specification (null in round 1):
{prev_spec_json}

Decisions and assumptions from earlier rounds:
{decisions or '(none yet)'}

Feedback from the last validation (fix problems it lists):
{feedback or '(none)'}

Output a JSON object with keys:
 "economy": the COMPLETE updated economy following this JSON schema: {schema}
 "notes": short text on the assumptions and decisions introduced this round,
 "removals": list of good/sector ids you deliberately removed (empty if none),
 "new_mechanics_requests": list of mechanics the current engine cannot express and the coder must add (usually empty).
Sectors are processed in `order` within a month; a service good must be produced by a sector that runs BEFORE the sectors
that use it. Initial stocks must let sectors run in month 1."""


CODER_SYSTEM = """You are the coder model of an economic-simulation design tool. You receive a structured economy specification and the
existing project code. Implement what the specification needs, preserving and extending the architecture. The engine in
citysim/economy/engine.py is data-driven and already supports goods, sectors, capital, inputs, outputs, regeneration,
depreciation and unstorable goods. If the specification needs nothing new, return no files.
Contract: EconomyModel(spec, city) with .stocks and .step(population, employed_labour) -> EconomyStep; EVERY stock change must
be recorded in the returned ledger (citysim/ledger.py) so conservation tests pass. You may edit only files under
citysim/economy/, citysim/spec.py and tests/generated/. Reply with one JSON object only:
{"files": {"<path>": "<complete new file content>"}, "notes": "<what changed and why>"}"""


def coder_prompt(spec_json, requests, code, feedback):
    return f"""Economy specification:
{spec_json}

Requested new mechanics (may be empty):
{json.dumps(requests)}

Existing code:
{code}

Problems reported by the last test run (fix them):
{feedback or '(none)'}"""


ANALYSIS_SYSTEM = """You are the analysis model of an economic-simulation design tool. Find places where the simulated economy cannot continue
coherently: missing inputs, unexplained outputs, processes with no source of necessary resources, stocks that change
without an accounted cause, dependencies that lead nowhere. Describe each problem CONCEPTUALLY and propose the missing
economic relationships. Reply with one JSON object only:
{"problems": [{"subject": "...", "description": "..."}], "conceptual_repairs": "<text the conceptual model will turn into spec changes>"}"""

DOCS_SYSTEM = """Write readable documentation of a simulated city for a human. Use ONLY the facts in the provided material; it must be
consistent with the implemented system. Cover: initial conditions, productive sectors, principal economic processes,
resource dependencies, population requirements, assumptions and abstractions. State plainly that the prototype contains no
social actors, institutions or superstructure. Reply with Markdown only."""
