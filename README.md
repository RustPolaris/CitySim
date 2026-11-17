# City economy prototype (brief v0.5, section 11)

Two programs:

1. **Development tool** (`devtool/`): orchestrates a conceptual model, a coder model and an analysis model to generate a
   city, build its economy over ~15 rounds, find and repair gaps, and write the city documentation.
2. **CLI simulation** (`citysim/cli.py`): loads a finished city, lets you inspect it, advances month by month, skips
   years (still month by month), records yearly figures, detects collapse and writes the final Marxist report.

A hand-built demo city (`cities/demo_ford`) ships so you can run everything without an API key.

## Quick start
```
pip install -r requirements.txt
python -m pytest -q                                  # 22 tests incl. the brief's 100-pop starvation example
python -m citysim.cli cities/demo_ford               # interactive (n = month, y = skip years, 1-7 = inspect, q = quit)
python -m citysim.cli cities/demo_ford --run 1000    # headless, prints the outcome
```
Generate a new city (needs Ollama running locally):
```
python -m devtool.build my_city --rounds 15 [--hint "a mountain mining town"]
python -m citysim.cli cities/my_city
```
Models (all local, via Ollama): `ollama pull qwen2.5:14b-instruct` (concept/analysis/docs/report) and
`ollama pull qwen2.5-coder:7b-instruct` (coder). Override with `CITYSIM_MODEL_CONCEPT|CODER|ANALYSIS|DOCS|REPORT`,
`CITYSIM_OLLAMA_URL` (e.g. the host's address when running in a VM), `CITYSIM_NUM_CTX`.

## Rules implemented (brief 11.7)
- Monthly births = opening pop x 1%/12, natural deaths = opening pop x 0.15%/12, both on the same opening population.
- Food is not stocked; each month's production is all there is. Starving = max(0, pop - food).
- No pop tracking: the last three monthly starvation figures are kept; starvation deaths = their minimum; deaths are
  subtracted from the population and from each retained figure; the record clears when food >= population.
- Collapse = population below one pop (population is a float). The run also ends after 1,000 years ("no collapse").
- Employed labour = pop x labour-force fraction x (1 - unemployed share), split by fixed sector percentages.

## How the generation loop maps onto the brief
- The conceptual model returns the **complete economy spec** (`citysim/spec.py`, the stable interface). The tool refuses
  rounds that silently delete earlier goods/sectors.
- `citysim/economy/engine.py` is a data-driven reference engine. The coder model is called every round with the spec and the
  existing code, but returns no files unless a new mechanic is needed. It may edit only `citysim/economy/`,
  `citysim/spec.py` and `tests/generated/`.
- After each round the tool runs `citysim.validate` in a subprocess: static gap detector + monthly ledger conservation
  (every stock change must be explained by a flow) + invalid-state checks. A failed round is rolled back (file snapshots,
  plus a git commit per good round).
- Gap analysis -> conceptual repair -> coder repair repeats up to `--repairs` times.
- Specs, round notes, failures and snapshots are kept in `cities/<slug>/rounds` and `cities/<slug>/logs`.

## Known limits
- The LLM-facing parts (`devtool.build`, LLM report) were tested only with scripted fake models, not against a live Ollama server.
- Subprocess execution with a timeout is not a security sandbox; run the tool in a VM or container.
- CLI reads a single keypress on a real terminal and a line when input is piped.
- Sector labour shares are constant unless the generated economy adds a reallocation rule.
