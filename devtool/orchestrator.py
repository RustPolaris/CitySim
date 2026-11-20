"""Development tool: guides the LLMs through city generation, economy construction rounds, gap repair and documentation.

Not the finished CLI. Intermediate specifications, generated code snapshots, test results and decisions are preserved
under cities/<slug>/rounds and cities/<slug>/logs. Failed rounds are rolled back to the last good state.
Note: model-written code runs in a subprocess with a timeout; that is NOT a
security sandbox. Run the tool inside a container or VM if you do not trust the model output.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

from citysim.analysis import find_gaps
from citysim.docgen import build_city_doc
from citysim.reproduction import calibrate, format_feedback
from citysim.seeding import seed_initial_stocks
from citysim.spec import CitySpec, EconomySpec
from citysim.validate import load_city
from .llm import extract_json
from . import prompts

ALLOWED_WRITE = ("citysim/economy/", "citysim/spec.py", "tests/generated/")
SNAPSHOT_PATHS = ("citysim/economy", "citysim/spec.py", "tests/generated")
REPAIR_KINDS = {"few_sectors", "orphan_output"}
REPRO_ATTEMPTS = 3     # concept-model tries per round to deliver an economy that reproduces itself (after calibration)


class RoundFailed(Exception):
    pass


def _fmt(seconds: float) -> str:
    m, sec = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


class Orchestrator:
    def __init__(self, repo_root, slug, llm, rounds=15, max_repair_cycles=6, log=print, use_git=True,
                 code_attempts=3, validation_years=20):
        self.root = Path(repo_root)
        self.slug = slug
        self.dir = self.root / "cities" / slug
        self.llm, self.rounds, self.max_repairs = llm, rounds, max_repair_cycles
        self._t0 = self._lap = time.monotonic()
        self.log = lambda msg: log(f"[{_fmt(time.monotonic() - self._t0)}] {msg}")    # every line carries the total elapsed time
        self.code_attempts, self.validation_years = code_attempts, validation_years
        for sub in ("rounds", "logs"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.use_git = use_git and shutil.which("git") is not None
        if self.use_git and not (self.root / ".git").exists():
            self._git("init")
        self.decisions: list[str] = []

    # ------------------------------------------------------------ helpers
    def done(self, label: str):
        """Log how long the stage that just ended took (the line prefix shows the total)."""
        now = time.monotonic()
        self.log(f"{label} done in {_fmt(now - self._lap)}")
        self._lap = now

    def _git(self, *args) -> str:
        try:
            r = subprocess.run(["git", "-c", "user.name=citysim", "-c", "user.email=citysim@localhost", *args],
                               cwd=self.root, capture_output=True, text=True, timeout=60)
            return r.stdout
        except Exception:
            return ""

    def commit(self, message: str):
        if self.use_git:
            self._git("add", "-A")
            self._git("commit", "-q", "--allow-empty", "-m", message)

    def _ask_json(self, role, system, prompt, validate, attempts=3, max_tokens=12000):
        error = ""
        for attempt in range(attempts):
            text = self.llm.complete(role, system, prompt + (f"\n\nYour previous reply was rejected: {error}\nReturn corrected JSON." if error else ""), max_tokens)
            (self.dir / "logs" / f"{role}_last_reply.txt").write_text(text)
            try:
                return validate(extract_json(text))
            except Exception as e:
                error = str(e)[:1500]
                self.log(f"    {role}: reply rejected ({error[:120]})")
        raise RoundFailed(f"{role} could not produce a valid reply: {error[:300]}")

    def snapshot(self, tag: str):
        snap = self.dir / "logs" / f"snap_{tag}"
        shutil.rmtree(snap, ignore_errors=True)
        snap.mkdir(parents=True)
        for rel in SNAPSHOT_PATHS:
            src = self.root / rel
            if src.is_dir():
                shutil.copytree(src, snap / rel, ignore=shutil.ignore_patterns("__pycache__"))
            elif src.is_file():
                (snap / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, snap / rel)
        for f in ("economy.json", "city.json"):
            if (self.dir / f).exists():
                shutil.copy2(self.dir / f, snap / f)
        return snap

    def restore(self, snap: Path):
        for rel in SNAPSHOT_PATHS:
            dst, src = self.root / rel, snap / rel
            if dst.is_dir():
                shutil.rmtree(dst)
            elif dst.is_file():
                dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst)
            elif src.is_file():
                shutil.copy2(src, dst)
        for f in ("economy.json", "city.json"):
            if (snap / f).exists():
                shutil.copy2(snap / f, self.dir / f)

    def read_code(self) -> str:
        out = []
        for rel in ("citysim/spec.py", "citysim/ledger.py", "citysim/economy"):
            p = self.root / rel
            files = sorted(p.rglob("*.py")) if p.is_dir() else [p]
            for f in files:
                if "__pycache__" not in f.parts:
                    out.append(f"### {f.relative_to(self.root)}\n{f.read_text()}")
        return "\n\n".join(out)

    def apply_files(self, files: dict) -> list[str]:
        written = []
        for rel, content in files.items():
            norm = os.path.normpath(rel).replace("\\", "/")
            if norm.startswith("/") or ".." in norm.split("/") or not norm.startswith(ALLOWED_WRITE):
                raise ValueError(f"path not allowed: {rel}")
            if not isinstance(content, str) or len(content) > 200_000:
                raise ValueError(f"bad content for {rel}")
            if norm.endswith(".py"):
                compile(content, norm, "exec")          # syntax check before writing anything
        for rel, content in files.items():
            norm = os.path.normpath(rel)
            dest = self.root / norm
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            written.append(norm)
        return written

    def validate(self) -> dict:
        env = dict(os.environ)
        try:
            r = subprocess.run([sys.executable, "-m", "citysim.validate", str(self.dir), "--years", str(self.validation_years)],
                               cwd=self.root, capture_output=True, text=True, timeout=300, env=env)
            report = json.loads(r.stdout) if r.stdout.strip() else {"errors": [f"validator produced no output: {r.stderr[-500:]}"]}
        except subprocess.TimeoutExpired:
            report = {"errors": ["validation timed out (infinite loop or far too slow)"]}
        except Exception as e:
            report = {"errors": [f"validator failed to run: {e}"]}
        report.setdefault("errors", [])
        return report

    def run_generated_tests(self) -> list[str]:
        """Runs tests/generated/ (written by the coder model) if any exist."""
        tdir = self.root / "tests" / "generated"
        if not tdir.is_dir() or not any(tdir.glob("test_*.py")):
            return []
        env = dict(os.environ)
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", str(tdir)], cwd=self.root,
                               capture_output=True, text=True, timeout=300, env=env)
        except subprocess.TimeoutExpired:
            return ["generated tests timed out"]
        return [] if r.returncode == 0 else [("generated tests failed:\n" + r.stdout[-1500:])]

    # ------------------------------------------------------------ stages
    def generate_city(self, hint: str = "") -> CitySpec:
        city = self._ask_json("concept", prompts.CITY_SYSTEM, prompts.CITY_PROMPT.format(hint=hint),
                              lambda o: CitySpec.model_validate(o))
        (self.dir / "city.json").write_text(city.model_dump_json(indent=1))
        self.log(f"City: {city.name} (population {city.population:,.0f})")
        return city

    def concept_step(self, n, total, city, prev, feedback=""):
        def check(obj):
            spec = EconomySpec.model_validate(obj["economy"])
            if prev is not None:
                gone = ({g.id for g in prev.goods} | {s.id for s in prev.sectors}) - ({g.id for g in spec.goods} | {s.id for s in spec.sectors})
                gone -= set(obj.get("removals", []))
                if gone:
                    raise ValueError(f"ids removed without being listed in 'removals': {sorted(gone)}")
            return spec, list(obj.get("new_mechanics_requests", [])), str(obj.get("notes", ""))
        prev_json = prev.model_dump_json(indent=1) if prev else "null"
        prompt = prompts.concept_prompt(n, total, city.model_dump_json(indent=1), prev_json, "\n".join(self.decisions[-12:]), feedback,
                                       prompts.scale_anchors(city))
        return self._ask_json("concept", prompts.CONCEPT_SYSTEM, prompt, check)

    def code_step(self, spec: EconomySpec, requests: list[str]) -> str:
        feedback, notes = "", ""
        for attempt in range(self.code_attempts):
            (self.dir / "economy.json").write_text(spec.model_dump_json(indent=1))
            reply = self._ask_json("coder", prompts.CODER_SYSTEM, prompts.coder_prompt(
                spec.model_dump_json(indent=1), requests, self.read_code(), feedback),
                lambda o: {"files": dict(o.get("files", {})), "notes": str(o.get("notes", ""))}, max_tokens=16000)
            snap = self.snapshot("code_attempt")
            try:
                if reply["files"]:
                    self.apply_files(reply["files"])
                notes = reply["notes"]
            except Exception as e:
                feedback = f"your files could not be applied: {e}"
                continue
            report = self.validate()
            problems = report["errors"] + self.run_generated_tests()
            (self.dir / "logs" / "last_validation.json").write_text(json.dumps(report, indent=1))
            if not problems:
                return notes
            feedback = "\n".join(problems)[:3000]
            self.log(f"    validation found {len(problems)} problem(s); asking the coder to repair")
        raise RoundFailed("coder could not satisfy validation: " + feedback[:400])

    def run_round(self, n: int, city: CitySpec, prev: EconomySpec | None, feedback: str = "") -> EconomySpec:
        snap = self.snapshot(f"round{n:02d}")
        try:
            fb = feedback
            for attempt in range(REPRO_ATTEMPTS):
                spec, requests, notes = self.concept_step(n, self.rounds, city, prev, fb)
                fixed, cal_notes, remaining = calibrate(spec, city)    # Option B: small, logged corrections by the tool
                if not remaining:
                    spec = fixed
                    break
                self.log(f"    economy not self-reproducing ({len(remaining)} imbalance(s)); asking the conceptual model to fix it")
                fb = (feedback + "\n\n" if feedback else "") + format_feedback(remaining)
            else:
                raise RoundFailed("the economy cannot reproduce itself: " + "; ".join(p["message"] for p in remaining)[:500])
            if cal_notes:
                notes += " | automatic calibration: " + "; ".join(cal_notes)
            seeded = seed_initial_stocks(spec, city)
            if seeded:
                notes += " | automatic starting stocks: " + "; ".join(seeded)
            (self.dir / "rounds" / f"{n:02d}_economy.json").write_text(spec.model_dump_json(indent=1))
            code_notes = self.code_step(spec, requests)
        except RoundFailed as e:
            self.log(f"  round {n} FAILED and was rolled back: {e}")
            self.restore(snap)
            (self.dir / "rounds" / f"{n:02d}_FAILED.txt").write_text(str(e))
            raise
        self.decisions.append(f"Round {n}: {notes} | code: {code_notes}")
        (self.dir / "rounds" / f"{n:02d}_notes.md").write_text(f"# Round {n}\n\n{notes}\n\n## Code changes\n{code_notes}\n")
        self.commit(f"round {n}: {notes[:60]}")
        return spec

    def construct(self, city: CitySpec) -> EconomySpec:
        prev = None
        for n in range(1, self.rounds + 1):
            self.log(f"Round {n}/{self.rounds}")
            try:
                prev = self.run_round(n, city, prev)
                self.done(f"Round {n}/{self.rounds}")
            except RoundFailed:
                self.done(f"Round {n}/{self.rounds} (failed, rolled back)")
                continue                      # state already rolled back; the next round starts from the last good economy
        if prev is None:
            raise RoundFailed("no construction round succeeded")
        return prev

    def repair_gaps(self, city: CitySpec, spec: EconomySpec) -> EconomySpec:
        for cycle in range(1, self.max_repairs + 1):
            report = self.validate()
            gaps = find_gaps(spec)
            blocking = [g for g in gaps if g["severity"] == "error" or g["kind"] in REPAIR_KINDS]
            if not report["errors"] and not blocking:
                self.log(f"Gap analysis: nothing left to repair after {cycle - 1} cycle(s).")
                return spec
            self.log(f"Repair cycle {cycle}: {len(report['errors'])} error(s), {len(blocking)} gap(s)")
            material = (f"Economy:\n{spec.model_dump_json(indent=1)}\n\nStatic gaps:\n{json.dumps(blocking, indent=1)}\n\n"
                        f"Validation report:\n{json.dumps(report, indent=1)[:4000]}\n\nCode:\n{self.read_code()}")
            analysis = self._ask_json("analysis", prompts.ANALYSIS_SYSTEM, material, lambda o: o)
            feedback = "Conceptual repairs proposed by the analysis model:\n" + str(analysis.get("conceptual_repairs", "")) + \
                       "\nProblems:\n" + json.dumps(analysis.get("problems", []))
            (self.dir / "rounds" / f"repair_{cycle:02d}_analysis.json").write_text(json.dumps(analysis, indent=1))
            try:
                spec = self.run_round(100 + cycle, city, spec, feedback)
                self.done(f"Repair cycle {cycle}")
            except RoundFailed:
                self.done(f"Repair cycle {cycle} (failed, rolled back)")
                continue
        self.log("Repair cycles exhausted; remaining problems are listed in logs/last_validation.json")
        return spec

    def compile_docs(self, city: CitySpec, spec: EconomySpec):
        base = build_city_doc(city, spec)
        (self.dir / "CITY.md").write_text(base)           # always consistent with the implemented specs
        try:
            text = self.llm.complete("docs", prompts.DOCS_SYSTEM, base + "\n\n---\nEngine code:\n" + self.read_code(), 6000)
            if len(text) > 500:
                (self.dir / "CITY.md").write_text(text)
        except Exception as e:
            self.log(f"  documentation LLM unavailable, kept the deterministic CITY.md ({e})")

    def run(self, hint: str = ""):
        city = self.generate_city(hint)
        self.commit("city specification")
        self.done("City generation")
        spec = self.construct(city)
        spec = self.repair_gaps(city, spec)
        self.done("Gap repair")
        self.compile_docs(city, spec)
        self.commit("documentation")
        self.done("Documentation")
        final = self.validate()
        self.done("Final validation")
        self.log(f"Total time {_fmt(time.monotonic() - self._t0)}")
        self.log("Final validation: " + ("OK" if not final["errors"] else "PROBLEMS: " + "; ".join(final["errors"][:3])))
        self.log(f"Launch the CLI with:  python -m citysim.cli cities/{self.slug}")
        return final
