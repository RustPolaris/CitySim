"""    python -m devtool.build my_city [--rounds 15] [--hint "a mountain mining town"]

Needs Ollama running locally with the models pulled (see README). Writes cities/<slug>/ (city.json, economy.json, CITY.md, rounds/, logs/).
"""
import argparse
from pathlib import Path
from .llm import OllamaLLM
from .orchestrator import Orchestrator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--rounds", type=int, default=15)
    ap.add_argument("--repairs", type=int, default=6)
    ap.add_argument("--hint", default="")
    ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    Orchestrator(root, a.slug, OllamaLLM(), rounds=a.rounds, max_repair_cycles=a.repairs,
                 use_git=not a.no_git).run(a.hint)


if __name__ == "__main__":
    main()
