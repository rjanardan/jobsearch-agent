"""Persistence for match rows (FR-7..9)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jobagent.store.models import Match


def upsert_match(session: Session, job_id: int, profile_version: int, payload: dict) -> None:
    """Insert or refresh one match row; unique on (job_id, profile_version)."""
    row = session.execute(
        select(Match).where(Match.job_id == job_id, Match.profile_version == profile_version)
    ).scalar_one_or_none()
    if row is None:
        session.add(
            Match(
                job_id=job_id,
                profile_version=profile_version,
                score=payload["score"],
                dimensions=payload["dimensions"],
                gaps=payload["gaps"],
                rationale=payload["rationale"],
                passed=payload["passed"],
                created_at=datetime.now(UTC),
            )
        )
    else:
        row.score = payload["score"]
        row.dimensions = payload["dimensions"]
        row.gaps = payload["gaps"]
        row.rationale = payload["rationale"]
        row.passed = payload["passed"]


def clear_matches(session: Session, profile_version: int) -> None:
    """Drop previous scores for a profile version before a full re-score."""
    session.execute(delete(Match).where(Match.profile_version == profile_version))


def count_matches(session: Session, profile_version: int) -> dict:
    rows = session.execute(select(Match).where(Match.profile_version == profile_version)).scalars().all()
    return {"total": len(rows), "passed": sum(1 for r in rows if r.passed)}
