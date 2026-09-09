"""Match orchestration: policy gate -> deterministic scoring -> persist.

One function the CLI and the (later) nightly graph both call, so scores are
identical however a run is triggered (FR-20 re-runnable).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobagent.guardrails.policy import apply_policy
from jobagent.store.matches import clear_matches, upsert_match
from jobagent.store.models import Job, Profile
from jobagent.tools.match import score_job
from jobagent.tools.profile import ProfileData, ProfileParseError

CONFIG_DIR = Path(os.environ.get("JOBAGENT_CONFIG_DIR", "config"))


def load_filters() -> dict:
    """Real filter policy if present; permissive defaults otherwise."""
    path = CONFIG_DIR / "filters.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def run_matching(session: Session, cutoff: float = 60.0) -> dict:
    """Score every active job against the active profile version.

    Policy-rejected jobs are recorded with a reason and excluded from scoring
    (FR-6); below-cutoff scored jobs stay in the store and stay searchable
    (FR-8). Returns a summary dict.
    """
    profile = session.execute(select(Profile).where(Profile.active.is_(True))).scalar_one_or_none()
    if profile is None:
        raise ProfileParseError("no active profile — load one first (`ja profile load <file>`)")
    profile_data = ProfileData.model_validate(profile.data)
    filters = load_filters()

    jobs = session.execute(select(Job).where(Job.active.is_(True))).scalars().all()
    clear_matches(session, profile.version)

    policy_rejected = 0
    scored = 0
    passed = 0
    for job in jobs:
        job_dict = {
            "title": job.title,
            "company_name": job.company_name,
            "level": job.level,
            "location": job.location,
            "remote": job.remote,
            "comp_min": job.comp_min,
            "comp_max": job.comp_max,
            "currency": job.currency,
            "description": job.description,
            "raw": job.raw,
        }
        decision = apply_policy(job_dict, filters)
        if not decision.allowed:
            policy_rejected += 1
            upsert_match(
                session,
                job.id,
                profile.version,
                {
                    "score": 0.0,
                    "dimensions": {},
                    "gaps": decision.reasons,
                    "rationale": f"policy-rejected: {'; '.join(decision.reasons)}",
                    "passed": False,
                },
            )
            continue
        result = score_job(profile_data, job_dict, cutoff=cutoff)
        upsert_match(session, job.id, profile.version, result.to_payload())
        scored += 1
        passed += 1 if result.passed else 0

    session.flush()  # make rows visible to the caller's own session (autoflush=False)
    return {
        "profile_version": profile.version,
        "jobs_total": len(jobs),
        "policy_rejected": policy_rejected,
        "scored": scored,
        "passed": passed,
    }
