"""Deterministic local match scoring (FR-7..9).

Scores are computed entirely locally, dimension by dimension, and every
dimension records its evidence (which profile lines and which role text
contributed) so a score can always be explained and traced. No model call is
involved in the prefilter: the cheap deterministic pass runs first, and only
its top-N would ever reach a reasoning model (see models/gateway.py).

Policy (FR-6) is applied *before* scoring by callers via guardrails.policy;
a policy-rejected job never receives a score in the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobagent.tools.profile import ProfileData, strip_html

# Seniority bands, coarse on purpose: titles in the wild are noisy ("Full-time"
# lands in level columns, ATS rows carry "mid-level" etc.). We rank by the most
# senior keyword present in title+level text, then compare band-to-band.
_BANDS = {
    "intern": 0,
    "junior": 1,
    "associate": 1,
    "mid": 2,
    "senior": 3,
    "lead": 3,
    "staff": 4,
    "principal": 5,
    "manager": 3,
    "director": 6,
    "head": 6,
    "vp": 7,
    "chief": 8,
    "cto": 8,
    "founder": 6,
}

_WEIGHTS = {
    "role": 0.30,
    "skills": 0.25,
    "seniority": 0.15,
    "location": 0.20,
    "comp": 0.10,
}


@dataclass
class Dimension:
    score: float  # 0..1
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    score: float  # 0..100
    dimensions: dict[str, Dimension]
    gaps: list[str]
    passed: bool
    rationale: str

    def to_payload(self) -> dict:
        return {
            "score": round(self.score, 1),
            "dimensions": {
                k: {"score": round(v.score, 3), "detail": v.detail, "evidence": v.evidence}
                for k, v in self.dimensions.items()
            },
            "gaps": self.gaps,
            "passed": self.passed,
            "rationale": self.rationale,
        }


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9+#. ]", " ", (text or "").lower())


def _band(title: str | None, level: str | None) -> int | None:
    """Seniority band of a role from its title+level text, or None if unclear."""
    hay = f"{title or ''} {level or ''}".lower()
    best = None
    for keyword, band in _BANDS.items():
        if keyword in hay and (best is None or band > best):
            best = band
    return best


def _job_text(job: dict) -> str:
    """Searchable text for one job: title + company + description (fallback raw)."""
    description = job.get("description") or ""
    if not description:
        raw = job.get("raw") or {}
        if isinstance(raw, dict) and not raw.get("truncated"):
            description = raw.get("raw_text") or ""
        elif isinstance(raw, str):
            description = raw
    return f"{job.get('title') or ''} {job.get('company_name') or ''} {strip_html(description)}"


def _is_remote(job: dict) -> bool:
    """Remote when flagged, or when every listed location segment says remote.

    Location strings carry semicolon-separated metros ("Remote, India; Remote,
    Israel") or single entries ("Remote - USA", "Remote"). A role is remote
    when all segments are remote; mixed lists (some offices, some remote) are
    treated as hybrid, not remote.
    """
    if job.get("remote") == "yes":
        return True
    raw_loc = (job.get("location") or "").strip()
    if not raw_loc:
        return False
    segments = [seg for seg in raw_loc.split(";") if seg.strip()]
    if not segments:
        return False
    return all("remote" in _norm(seg) for seg in segments)


def score_job(profile: ProfileData, job: dict, cutoff: float = 60.0) -> MatchResult:
    """Deterministic prefilter score of one job against the active profile."""
    dims: dict[str, Dimension] = {}
    gaps: list[str] = []
    text = _norm(_job_text(job))
    title = _norm(job.get("title"))

    # --- role: target titles + domains vs job title/company -----------------
    targets = [t for t in (profile.target_titles or []) if t] + [d for d in (profile.domains or []) if d]
    role_hits: list[str] = []
    for term in targets:
        if _norm(term) and _norm(term) in title:
            role_hits.append(term)
    if targets:
        role_score = min(1.0, len(role_hits) / max(1, min(3, len(targets))))
        if not role_hits:
            dims["role"] = Dimension(role_score * 0.5, detail="no target title/domain keyword in job title")
        else:
            dims["role"] = Dimension(role_score, evidence=role_hits[:5])
    else:
        dims["role"] = Dimension(0.5, detail="no target titles/domains set; neutral")

    # --- skills: profile skill names/keywords present in job text -----------
    total_w = sum(s.proficiency for s in profile.skills)
    hit_w = 0
    hit_names: list[str] = []
    for s in profile.skills:
        tokens = [s.name] + [k for k in (s.keywords or []) if k]
        if any(_norm(t) and _norm(t) in text for t in tokens):
            hit_w += s.proficiency
            hit_names.append(s.name)
    skills_score = hit_w / total_w if total_w else 0.0
    missing = [s.name for s in profile.skills if s.name not in hit_names][:6]
    dims["skills"] = Dimension(
        skills_score,
        detail=f"{len(hit_names)}/{len(profile.skills)} profile skills evidenced in role text",
        evidence=hit_names[:8],
    )

    # --- seniority band -------------------------------------------------------
    target_bands = {b for t in (profile.target_levels or []) if (b := _band(t, None)) is not None}
    job_band = _band(job.get("title"), job.get("level"))
    if not target_bands or job_band is None:
        seniority_score, seniority_detail = 0.5, "seniority unclear on one side; neutral"
    else:
        lo, hi = min(target_bands), max(target_bands)
        if job_band >= hi:
            seniority_score, seniority_detail = 1.0, f"job band {job_band} meets/exceeds most senior target {hi}"
        elif job_band >= lo:
            seniority_score, seniority_detail = 0.85, f"job band {job_band} within target range {lo}-{hi}"
        elif job_band >= lo - 1:
            seniority_score, seniority_detail = 0.6, f"job band {job_band} one below target range {lo}-{hi}"
        else:
            seniority_score, seniority_detail = 0.3, f"job band {job_band} well below target range {lo}-{hi}"
    dims["seniority"] = Dimension(seniority_score, detail=seniority_detail)
    if seniority_score < 0.6:
        gaps.append(f"seniority: {seniority_detail}")

    # --- location / remote -----------------------------------------------------
    loc = _norm(job.get("location"))
    remote_ok = bool(profile.remote_ok)
    is_remote = _is_remote(job)
    profile_loc = _norm(profile.location or "")
    profile_city = (profile_loc.split() or [""])[0]  # "bengaluru india" -> "bengaluru"
    loc_evidence: list[str] = []
    if remote_ok and is_remote:
        loc_score, loc_detail = 1.0, "role is remote and profile allows remote"
        loc_evidence = [job.get("location") or ""]
    elif profile_city and profile_city in loc:
        loc_score, loc_detail = 1.0, f"location matches profile ({profile.location})"
        loc_evidence = [job.get("location") or ""]
    elif is_remote:
        loc_score, loc_detail = 0.4, "role is remote but profile prefers on-site"
    elif profile_city:
        same_country = "india" in loc or "in " in f" {loc} "
        loc_score, loc_detail = (0.5, "role in India, not profile city") if same_country else (0.1, "location outside profile region")
        if loc_score < 0.5:
            gaps.append(f"location: {job.get('location')} vs profile {profile.location}")
    else:
        loc_score, loc_detail = 0.5, "profile location not set; neutral"
    dims["location"] = Dimension(loc_score, detail=loc_detail, evidence=loc_evidence)

    # --- compensation ------------------------------------------------------------
    if job.get("comp_min") is not None and profile.comp_max:
        overlap = min(job["comp_max"] or job["comp_min"], profile.comp_max) - max(job["comp_min"], profile.comp_min or 0)
        span = max(1, (job["comp_max"] or job["comp_min"]) - job["comp_min"])
        comp_score = max(0.0, min(1.0, overlap / span))
        dims["comp"] = Dimension(comp_score, detail=f"job comp {job['comp_min']}-{job.get('comp_max')} vs profile cap {profile.comp_max}")
        if comp_score < 0.5:
            gaps.append(f"comp: role range below profile expectation (cap {profile.comp_max})")
    else:
        dims["comp"] = Dimension(0.5, detail="comp not listed on one side; neutral")

    # --- weighted total (all dims present) --------------------------------------
    total = sum(dims[k].score * _WEIGHTS[k] for k in _WEIGHTS if k in dims)
    score = round(total * 100 / sum(_WEIGHTS.values()), 1)
    passed = score >= cutoff

    if not role_hits and (profile.target_titles or profile.domains):
        gaps.append(f"role: title '{job.get('title')}' not in target titles/domains")
    if missing and skills_score < 0.6:
        gaps.append(f"skills: not evidenced in role text: {', '.join(missing)}")

    rationale = _rationale(job, dims, score, gaps)
    return MatchResult(score=score, dimensions=dims, gaps=gaps[:6], passed=passed, rationale=rationale)


def _rationale(job: dict, dims: dict[str, Dimension], score: float, gaps: list[str]) -> str:
    lines = [
        f"{job.get('company_name') or '?'} — {job.get('title') or '?'}: deterministic score {score}/100",
        *[f"  {k}: {v.score:.2f} — {v.detail}" for k, v in dims.items()],
    ]
    if gaps:
        lines.append("  gaps: " + "; ".join(gaps))
    return "\n".join(lines)
