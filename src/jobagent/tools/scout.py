"""Match orchestration: policy gate -> deterministic scoring -> persist.

One function the CLI and the (later) nightly graph both call, so scores are
identical however a run is triggered (FR-20 re-runnable). Emits an OTel
trace per run (match.run -> policy gate + scored batches) so Phoenix shows
live per-run traces with stage latencies and counts.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobagent import telemetry
from jobagent.guardrails.policy import apply_policy
from jobagent.store.matches import clear_matches, upsert_match
from jobagent.store.models import Job, Profile
from jobagent.tools.match import score_job
from jobagent.tools.profile import ProfileData, ProfileParseError

CONFIG_DIR = Path(os.environ.get("JOBAGENT_CONFIG_DIR", "config"))

# Scored jobs per child span, so one run's trace stays readable at any
# store size (a 418-job run -> ~6 spans, not ~420).
SCORE_BATCH = 100


def load_filters() -> dict:
    """Real filter policy if present; permissive defaults otherwise."""
    path = CONFIG_DIR / "filters.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _job_dict(job: Job) -> dict:
    return {
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

    with telemetry.span(
        "match.run",
        attrs={"profile_version": profile.version, "cutoff": cutoff, "jobs_total": len(jobs)},
    ) as root:
        # Phase 1: policy gate (FR-6) — reject with recorded reason.
        allowed: list[Job] = []
        rejected = 0
        with telemetry.span("match.policy_gate", attrs={"evaluated": len(jobs)}) as gate:
            for job in jobs:
                decision = apply_policy(_job_dict(job), filters)
                if not decision.allowed:
                    rejected += 1
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
                else:
                    allowed.append(job)
            gate.set_attribute("allowed", len(allowed))
            gate.set_attribute("rejected", rejected)

        # Phase 2: deterministic scoring in readable batches.
        scored = 0
        passed = 0
        for start in range(0, len(allowed), SCORE_BATCH):
            chunk = allowed[start : start + SCORE_BATCH]
            with telemetry.span(
                "match.score_batch",
                attrs={"batch": start // SCORE_BATCH, "jobs": len(chunk)},
            ):
                for job in chunk:
                    result = score_job(profile_data, _job_dict(job), cutoff=cutoff)
                    upsert_match(session, job.id, profile.version, result.to_payload())
                    scored += 1
                    passed += 1 if result.passed else 0

        session.flush()  # make rows visible to the caller's own session (autoflush=False)
        root.set_attribute("policy_rejected", rejected)
        root.set_attribute("scored", scored)
        root.set_attribute("passed", passed)

    return {
        "profile_version": profile.version,
        "jobs_total": len(jobs),
        "policy_rejected": rejected,
        "scored": scored,
        "passed": passed,
    }
