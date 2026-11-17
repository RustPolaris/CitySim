"""Local LLM access through Ollama (no API key, no internet). Roles: concept, coder, analysis, docs, report.

Environment overrides:
  CITYSIM_OLLAMA_URL      default http://localhost:11434   (point this at the host when running inside a VM)
  CITYSIM_MODEL_<ROLE>    e.g. CITYSIM_MODEL_CODER=qwen2.5-coder:7b-instruct
  CITYSIM_NUM_CTX         context window, default 12288
  CITYSIM_TIMEOUT         seconds per request, default 1800
"""
from __future__ import annotations
import json, os, re, urllib.request

DEFAULT_MODELS = {
    "concept": "qwen2.5:14b-instruct",
    "analysis": "qwen2.5:14b-instruct",
    "docs": "qwen2.5:14b-instruct",
    "report": "qwen2.5:14b-instruct",
    "coder": "qwen2.5-coder:7b-instruct",
}
JSON_ROLES = {"concept", "analysis", "coder"}     # replies that must be a JSON object


class OllamaLLM:
    def __init__(self, url: str | None = None):
        self.url = (url or os.environ.get("CITYSIM_OLLAMA_URL") or "http://localhost:11434").rstrip("/")

    def complete(self, role: str, system: str, prompt: str, max_tokens: int = 8000) -> str:
        model = os.environ.get(f"CITYSIM_MODEL_{role.upper()}") or DEFAULT_MODELS.get(role, DEFAULT_MODELS["concept"])
        body = {"model": model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "options": {"num_ctx": int(os.environ.get("CITYSIM_NUM_CTX", 12288)), "num_predict": max_tokens,
                            "temperature": 0.4}}
        if role in JSON_ROLES:
            body["format"] = "json"
        req = urllib.request.Request(self.url + "/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get("CITYSIM_TIMEOUT", 1800))) as r:
                return json.loads(r.read())["message"]["content"]
        except OSError as e:
            raise RuntimeError(f"could not reach Ollama at {self.url} (is it running, and is model '{model}' pulled?): {e}")


def extract_json(text: str) -> dict:
    """Pull one JSON object out of a model reply (plain, fenced, or surrounded by prose)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not candidate.strip():
        raise ValueError("no JSON object found in the reply")
    return json.loads(candidate)
