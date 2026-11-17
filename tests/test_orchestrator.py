import json, shutil
from pathlib import Path
import pytest
from devtool.orchestrator import Orchestrator, RoundFailed

ROOT = Path(__file__).resolve().parent.parent
DEMO_CITY = (ROOT / "cities/demo_ford/city.json").read_text()
DEMO_ECON = json.loads((ROOT / "cities/demo_ford/economy.json").read_text())


class FakeLLM:
    def __init__(self, coder_reply=None):
        self.coder_reply = coder_reply or {"files": {}, "notes": "engine already supports this"}
        self.calls = []

    def complete(self, role, system, prompt, max_tokens=8000):
        self.calls.append(role)
        if role == "concept":
            if "Invent a simple city" in prompt:
                return "```json\n" + DEMO_CITY + "\n```"
            return json.dumps({"economy": DEMO_ECON, "notes": "demo economy", "removals": [], "new_mechanics_requests": []})
        if role == "coder":
            return json.dumps(self.coder_reply)
        if role == "analysis":
            return json.dumps({"problems": [], "conceptual_repairs": ""})
        return "short"                                      # docs: too short, deterministic CITY.md is kept


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    shutil.copytree(ROOT / "citysim", r / "citysim", ignore=shutil.ignore_patterns("__pycache__"))
    return r


def make(repo, llm, **kw):
    return Orchestrator(repo, "t", llm, use_git=False, log=lambda *_: None, validation_years=3, **kw)


def test_full_pipeline_with_scripted_models(repo):
    llm = FakeLLM()
    orch = make(repo, llm, rounds=2, max_repair_cycles=2)
    final = orch.run()
    d = repo / "cities" / "t"
    assert final["errors"] == []
    assert (d / "city.json").exists() and (d / "economy.json").exists() and (d / "CITY.md").exists()
    assert (d / "rounds" / "01_economy.json").exists() and (d / "rounds" / "02_notes.md").exists()
    assert llm.calls.count("coder") == 2


def test_removing_ids_silently_is_rejected(repo):
    class Dropper(FakeLLM):
        n = 0
        def complete(self, role, system, prompt, max_tokens=8000):
            if role == "concept" and "Invent a simple city" not in prompt:
                self.n += 1
                econ = json.loads(json.dumps(DEMO_ECON))
                if self.n >= 2:                               # drop a good that nothing else references
                    econ["goods"] = [g for g in econ["goods"] if g["id"] != "clothing"]
                    econ["population_consumption"] = {}
                    for s in econ["sectors"]:
                        s["outputs"].pop("clothing", None)
                return json.dumps({"economy": econ, "notes": "x", "removals": [], "new_mechanics_requests": []})
            return super().complete(role, system, prompt, max_tokens)
    orch = make(repo, Dropper(), rounds=1)
    city = orch.generate_city()
    spec = orch.run_round(1, city, None)
    with pytest.raises(RoundFailed):
        orch.run_round(2, city, spec)


def test_disallowed_paths_are_refused(repo):
    orch = make(repo, FakeLLM())
    for bad in ("citysim/simulation.py", "../evil.py", "/etc/passwd", "citysim/economy/../simulation.py"):
        with pytest.raises(ValueError):
            orch.apply_files({bad: "x = 1"})
    with pytest.raises(SyntaxError):
        orch.apply_files({"citysim/economy/engine.py": "def broken(:"})


def test_failed_round_is_rolled_back(repo):
    broken = "class EconomyModel:\n    def __init__(self, spec, city): raise RuntimeError('boom')\n"
    llm = FakeLLM({"files": {"citysim/economy/engine.py": broken}, "notes": "bad change"})
    orch = make(repo, llm, rounds=1, code_attempts=2)
    original = (repo / "citysim/economy/engine.py").read_text()
    city = orch.generate_city()
    with pytest.raises(RoundFailed):
        orch.run_round(1, city, None)
    assert (repo / "citysim/economy/engine.py").read_text() == original
    assert (repo / "cities/t/rounds/01_FAILED.txt").exists()
