"""Golden-set regression for deterministic match scoring (NFR-5 seed).

Synthetic roles with known-good relative order and dimension expectations.
Pure-function tests: no DB, no model calls. Scores must stay stable or the
test fails — this is the drift alarm the full eval harness builds on (M8).
"""

from __future__ import annotations

from jobagent.guardrails.policy import apply_policy
from jobagent.tools.match import _is_remote, score_job
from jobagent.tools.profile import ProfileData

PROFILE = ProfileData.model_validate(
    {
        "name": "Golden Tester",
        "location": "Bengaluru, India",
        "remote_ok": True,
        "skills": [
            {"name": "Python", "proficiency": 5, "keywords": ["python"]},
            {"name": "PyTorch", "proficiency": 4, "keywords": ["pytorch"]},
            {"name": "PostgreSQL", "proficiency": 4, "keywords": ["postgres", "postgresql"]},
            {"name": "LangGraph", "proficiency": 4, "keywords": ["langgraph", "llm agent"]},
            {"name": "Kubernetes", "proficiency": 3, "keywords": ["kubernetes", "k8s"]},
        ],
        "domains": ["AI platform", "machine learning", "agentic AI"],
        "target_titles": ["Staff Engineer", "Principal Engineer", "Head of AI"],
        "target_levels": ["Staff", "Principal", "Head"],
    }
)


def _job(**kw) -> dict:
    base = {
        "title": "",
        "company_name": "Acme",
        "level": None,
        "location": "Remote",
        "remote": None,
        "comp_min": None,
        "comp_max": None,
        "currency": None,
        "description": "",
        "raw": None,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------- strong match

def test_strong_staff_ml_role_passes_cutoff() -> None:
    job = _job(
        title="Staff Machine Learning Engineer, AI Platform",
        location="Bangalore, India",  # spelling variant of profile city Bengaluru
        description=(
            "Build ML platforms with Python and PyTorch. Postgres for feature "
            "stores, Kubernetes for serving. LangGraph agent orchestration."
        ),
    )
    result = score_job(PROFILE, job, cutoff=60)
    assert result.passed
    assert result.score >= 60
    # skills evidenced: python, pytorch, postgres, kubernetes, langgraph -> all 5
    skills = result.dimensions["skills"]
    assert len(skills.evidence) >= 4, skills.evidence
    # Bangalore == Bengaluru via the city alias, not a 0.5 "India, not city"
    assert result.dimensions["location"].score == 1.0
    assert result.dimensions["seniority"].score >= 0.85


# ---------------------------------------------------------------- weak match

def test_junior_unrelated_onsite_role_fails_with_gaps() -> None:
    job = _job(
        title="Sales Development Representative",
        company_name="SomeCorp",
        level="Junior",
        location="New York, NY",
        remote="no",
        description="Cold calling and pipeline generation for enterprise accounts.",
    )
    result = score_job(PROFILE, job, cutoff=60)
    assert not result.passed
    assert result.score < 40
    assert any("seniority" in g for g in result.gaps)
    assert any("location" in g for g in result.gaps)
    assert result.dimensions["skills"].evidence == []


# ------------------------------------------------------------------ ordering

def test_ordering_strong_beats_weak() -> None:
    strong = score_job(
        PROFILE,
        _job(title="Staff ML Engineer", location="Remote", description="Python PyTorch PostgreSQL Kubernetes LangGraph"),
    )
    weak = score_job(
        PROFILE,
        _job(title="Accountant", location="Omaha, NE", remote="no", description="GAAP reporting, Excel."),
    )
    assert strong.score > weak.score


# ----------------------------------------------------------------- remote logic

def test_remote_detection() -> None:
    assert _is_remote({"remote": "yes", "location": "Bengaluru"})
    assert _is_remote({"remote": None, "location": "Remote - USA"})
    assert _is_remote({"remote": None, "location": "Remote, India; Remote, Israel"})
    assert not _is_remote({"remote": None, "location": "Bengaluru, India"})
    assert not _is_remote({"remote": None, "location": "Remote, Canada; Toronto, Canada"})  # hybrid


# -------------------------------------------------------------------- policy

def test_policy_excludes_by_title_regex() -> None:
    filters = {"excluded_titles": ["sales", "recruit"]}
    assert not apply_policy(_job(title="Sales Engineer"), filters).allowed
    assert not apply_policy(_job(title="Technical Recruiter"), filters).allowed
    assert apply_policy(_job(title="Staff Engineer"), filters).allowed


def test_policy_remote_only_and_location() -> None:
    assert not apply_policy(_job(title="Engineer", location="NYC", remote="no"), {"remote": "yes"}).allowed
    assert apply_policy(_job(title="Engineer", location="NYC", remote="yes"), {"remote": "yes"}).allowed
    assert not apply_policy(_job(title="Engineer", location="Paris, France", remote="no"), {"locations": ["Bengaluru"]}).allowed
    assert apply_policy(_job(title="Engineer", location="Bengaluru, India", remote="no"), {"locations": ["Bengaluru"]}).allowed


# ------------------------------------------- India / full-time policy (2026-09-10)

INDIA_FULLTIME = {"countries": ["india"], "employment": ["full-time"]}


def test_policy_india_country_gate() -> None:
    assert apply_policy(_job(title="Staff Engineer", location="Bangalore, India"), INDIA_FULLTIME).allowed
    assert apply_policy(_job(title="Staff Engineer", location="Remote, India"), INDIA_FULLTIME).allowed
    assert not apply_policy(_job(title="Staff Engineer", location="Remote - USA"), INDIA_FULLTIME).allowed
    assert not apply_policy(_job(title="Staff Engineer", location="Remote"), INDIA_FULLTIME).allowed  # strict: no country evidence
    assert not apply_policy(_job(title="Staff Engineer", location=None), INDIA_FULLTIME).allowed
    # word boundary: "Indiana, United States" must NOT read as India
    assert not apply_policy(_job(title="Staff Engineer", location="Indiana, United States"), INDIA_FULLTIME).allowed


def test_policy_full_time_gate() -> None:
    assert apply_policy(
        _job(title="Staff Engineer", location="Bangalore, India", description="Build AI platforms in Python."),
        INDIA_FULLTIME,
    ).allowed
    assert not apply_policy(
        _job(title="Staff Engineer", location="Bangalore, India", description="Part-time role, 20 hours a week."),
        INDIA_FULLTIME,
    ).allowed
    assert not apply_policy(
        _job(title="Software Engineer (Contract)", location="Bangalore, India"),
        INDIA_FULLTIME,
    ).allowed
    assert not apply_policy(
        _job(title="Machine Learning Internship", location="Bangalore, India"),
        INDIA_FULLTIME,
    ).allowed
    # subject-matter plural must not trip the contract marker
    assert apply_policy(
        _job(title="Staff Engineer", location="Bangalore, India", description="Owns vendor contracts for the platform team."),
        INDIA_FULLTIME,
    ).allowed
    # GitLab JD boilerplate: "contract" in a testing list is not employment
    # signal (regression from the 2026-09-10 corpus run)
    assert apply_policy(
        _job(title="Staff Engineer", location="Bangalore, India", description="Add unit, integration, contract, and end-to-end tests."),
        INDIA_FULLTIME,
    ).allowed
