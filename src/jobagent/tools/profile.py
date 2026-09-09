"""Profile construction: parse resumes into the structured master profile.

Privacy: resume text is personal data. Only local Ollama models ever see it;
nothing leaves the host (NFR-1). Structured YAML/JSON profiles bypass the model
entirely and are validated against the same schema.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field, ValidationError

_TEXT_EXT = {".txt", ".md", ".markdown"}
_HTML_EXT = {".html", ".htm"}
_PDF_EXT = {".pdf"}
_STRUCTURED_EXT = {".yaml", ".yml", ".json"}

_PROFILE_SCHEMA_HINT = (
    "Produce JSON only, matching this schema:\n"
    "{\n"
    '  "name": str, "headline": str, "location": str|null,\n'
    '  "remote_ok": bool, "comp_min": number|null, "comp_max": number|null, "currency": str|null,\n'
    '  "experience_years": number|null,\n'
    '  "skills": [{"name": str, "proficiency": int 1-5, "keywords": [str]}],\n'
    '  "roles": [{"title": str, "org": str|null, "years": str|null}],\n'
    '  "domains": [str],\n'
    '  "education": [{"degree": str, "school": str|null, "year": str|null}],\n'
    '  "target_levels": [str],\n'
    '  "target_titles": [str],\n'
    '  "notes": str|null\n'
    "}\n"
    "Proficiency 5 = daily expert use, 1 = exposure only. Keep every claim "
    "traceable to the resume; do not invent skills or titles."
)


class Skill(BaseModel):
    name: str
    proficiency: int = Field(ge=1, le=5)
    keywords: list[str] = Field(default_factory=list)


class Role(BaseModel):
    title: str
    org: str | None = None
    years: str | None = None


class Education(BaseModel):
    degree: str
    school: str | None = None
    year: str | None = None


class ProfileData(BaseModel):
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    remote_ok: bool = True
    comp_min: float | None = None
    comp_max: float | None = None
    currency: str | None = None
    experience_years: float | None = None
    skills: list[Skill] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    target_levels: list[str] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)
    notes: str | None = None


def _model() -> str:
    return os.environ.get("MODEL_LOCAL", "ollama/qwen3:4b").removeprefix("ollama/")


def _read_text(path: Path) -> str:
    """Extract plain text from .txt/.md/.html/.pdf (FR-1)."""
    if path.suffix.lower() in _TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in _HTML_EXT:
        return html_to_text(path.read_text(encoding="utf-8", errors="replace"))
    if path.suffix.lower() in _PDF_EXT:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "") for p in reader.pages]
        return "\n\n".join(pages)
    raise ValueError(
        f"unsupported resume format: {path.suffix} "
        f"(want {sorted(_TEXT_EXT | _HTML_EXT | _PDF_EXT)})"
    )


def parse_resume_text(text: str) -> ProfileData:
    """Extract a structured profile from resume text via the local model.

    Only the local model is used; resume text never reaches an external API.
    Returns validated ProfileData or raises ProfileParseError.
    """
    try:
        resp = httpx.post(
            f"{os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/chat",
            json={
                "model": _model(),
                "stream": False,
                "think": False,  # top-level, not options: qwen3 ignores options.think
                "format": "json",
                "options": {"num_ctx": 8192, "temperature": 0, "num_predict": 2048},
                "messages": [
                    {"role": "system", "content": "You structure resumes into a JSON profile. " + _PROFILE_SCHEMA_HINT},
                    {"role": "user", "content": text[:14000]},
                ],
            },
            timeout=180,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        if not content.strip():  # safety net: answer sometimes lands in thinking
            content = resp.json()["message"].get("thinking", "")
        return ProfileData.model_validate(json.loads(content))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ProfileParseError(f"model returned invalid profile JSON: {exc}") from exc
    except Exception as exc:
        raise ProfileParseError(f"local profile extraction failed: {exc}") from exc


def load_structured(path: Path) -> ProfileData:
    """Load a hand-authored YAML/JSON profile (validated, no model involved)."""
    raw = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            data = yaml.safe_load(raw) or {}
    except Exception as exc:
        raise ProfileParseError(f"cannot parse {path.name}: {exc}") from exc
    try:
        return ProfileData.model_validate(data)
    except ValidationError as exc:
        raise ProfileParseError(f"profile schema errors in {path.name}: {exc}") from exc


def load_profile(path: str | Path) -> ProfileData:
    """Load a profile from a resume (txt/md/html/pdf) or structured file (yaml/json)."""
    p = Path(path).expanduser()
    if not p.exists():
        raise ProfileParseError(f"no such file: {p}")
    if p.suffix.lower() in _STRUCTURED_EXT:
        return load_structured(p)
    return parse_resume_text(_read_text(p))


def source_hash(path: str | Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Tag sets for html_to_text — immutable on purpose (no class-attribute state).
_HTML_SKIP = frozenset({"script", "style", "head", "title", "noscript"})
_HTML_BLOCK = frozenset(
    {"p", "div", "li", "tr", "br", "section", "article", "header",
     "ul", "ol", "table", "blockquote"}
)
_HTML_HEADING = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def html_to_text(html: str) -> str:
    """Structure-preserving HTML→text for resume pages (FR-1 HTML resumes).

    Script/style content is dropped; block boundaries (headings, lists,
    paragraphs, table rows) are kept as line breaks so a downstream reader
    still sees the resume's section layout. Entities are decoded. The parser
    is spec-tolerant: malformed markup yields the best-effort text.
    """
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs) -> None:
            if tag in _HTML_SKIP:
                self._skip += 1
            if tag in _HTML_BLOCK:
                self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
            if tag in _HTML_HEADING:
                self.parts.append("## ")

        def handle_endtag(self, tag) -> None:
            if tag in _HTML_SKIP:
                self._skip = max(0, self._skip - 1)
            if tag in _HTML_BLOCK:
                self.parts.append("\n")

        def handle_data(self, data) -> None:
            if not self._skip and data.strip():
                self.parts.append(data)

    extractor = _Extractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.parts)
    text = re.sub(r"[ \t\r]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(text: str) -> str:
    """Minimal HTML→text for ATS snippets; entities decoded, tags removed."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&#x2F;", "/").replace("&amp;", "&").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


class ProfileParseError(Exception):
    """Raised when a resume/profile cannot be parsed or validated."""
