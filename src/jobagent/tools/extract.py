"""Structured extraction from unstructured listings via the local model.

Only local Ollama models ever see raw listing text; nothing leaves the host
(guardrail rule: external models get scrubbed data only). qwen3 runs with
thinking disabled: extraction is a classification task, not a reasoning task.
"""

from __future__ import annotations

import json
import os

import httpx

_SYSTEM = (
    "You extract job postings from messy text. "
    "Return JSON: {\"company\": str|null, \"title\": str|null, \"location\": str|null, "
    "\"remote\": \"yes\"|\"no\"|null, \"level\": str|null, \"url\": str|null, \"is_job\": bool}. "
    "Set is_job false when the text is not a job posting. Company/title default to null when unknown."
)


def _model() -> str:
    return os.environ.get("MODEL_LOCAL", "ollama/qwen3:4b").removeprefix("ollama/")


def extract_listing(text: str) -> dict | None:
    """Classify and extract one unstructured listing. Returns None on failure."""
    try:
        resp = httpx.post(
            f"{os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/chat",
            json={
                "model": _model(),
                "stream": False,
                "think": False,  # top-level, not options: qwen3 ignores options.think
                "format": "json",
                "options": {"num_ctx": 4096, "temperature": 0, "num_predict": 256},
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text[:1500]},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        if not content.strip():  # safety net: answer sometimes lands in thinking
            content = resp.json()["message"].get("thinking", "")
        data = json.loads(content)
        if not data.get("is_job"):
            return None
        return data
    except Exception:  # noqa: BLE001 - extraction failure degrades to skip
        return None
