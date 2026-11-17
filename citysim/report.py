"""Final analytical report written by a fresh LLM from the saved city data (brief 11.8)."""
from __future__ import annotations
import json
from pathlib import Path

REPORT_SYSTEM = """You write a concise analytical report on a simulated city, with a Marxist analysis grounded ONLY in the
information provided. Structure: (1) the society and its economic development, (2) analysis, (3) an explanation of the
material and economic processes that led to collapse (or, if the city survived, what kept it materially sustainable).
Rules: clearly separate MODELED FACTS (numbers in the data) from INTERPRETATION. The simulation contains no social actors,
institutions, ideology, political organization or changing social relations; say so, and do not attribute outcomes to
political or ideological mechanisms the simulation never represented. Do not invent figures."""


def _compact_history(records: list[dict], max_rows: int = 60) -> list[dict]:
    if len(records) <= max_rows:
        return records
    step = len(records) / max_rows
    keep = {int(i * step) for i in range(max_rows)} | {len(records) - 1, len(records) - 2}
    return [r for i, r in enumerate(records) if i in keep]


def build_prompt(city_dir: Path, sim) -> str:
    doc = (city_dir / "CITY.md")
    parts = ["## City specification\n" + (city_dir / "city.json").read_text(),
             "## Economic system documentation\n" + (doc.read_text() if doc.exists() else "(none; see economy.json)\n" + (city_dir / "economy.json").read_text()),
             f"## Outcome\n{sim.collapse_message()}",
             "## Yearly structured history (sampled if long)\n" + json.dumps(_compact_history(sim.records))]
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
