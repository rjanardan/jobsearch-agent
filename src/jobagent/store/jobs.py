"""Persistence operations for jobs and source health."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobagent.store.models import Job, SourceState


def upsert_jobs(session: Session, jobs: list[dict]) -> dict:
    """Insert or refresh jobs by fingerprint. Returns {"inserted": n, "updated": n}."""
    inserted = updated = 0
    now = datetime.now(UTC)
    seen: set[str] = set()
    for j in jobs:
        fp = j["fingerprint"]
        if fp in seen:  # batch-internal duplicates (e.g. localized twin listings)
            continue
        seen.add(fp)
        row = session.execute(select(Job).where(Job.fingerprint == fp)).scalar_one_or_none()
        if row is None:
            session.add(Job(**j, first_seen=now, last_seen=now))
            inserted += 1
        else:
            for key, value in j.items():
                if key not in {"fingerprint"} and value is not None:
                    setattr(row, key, value)
            row.last_seen = now
            updated += 1
    session.flush()
    return {"inserted": inserted, "updated": updated}


def touch_source(
    session: Session, source: str, *, ok: bool, error: str | None = None, cursor: str | None = None
) -> None:
    """Record source health for one run (FR-3, NFR-6)."""
    row = session.execute(select(SourceState).where(SourceState.source == source)).scalar_one_or_none()
    if row is None:
        row = SourceState(source=source)
        session.add(row)
    row.last_run_at = datetime.now(UTC)
    row.healthy = ok
    row.error = {"message": error} if error else None
    if cursor is not None:
        row.last_cursor = cursor


def count_jobs(session: Session) -> int:
    return session.execute(select(Job)).scalars().all().__len__()  # type: ignore[no-any-return]


def recent_jobs(session: Session, limit: int = 10) -> list[Job]:
    return list(
        session.execute(select(Job).order_by(Job.first_seen.desc()).limit(limit)).scalars()
    )
