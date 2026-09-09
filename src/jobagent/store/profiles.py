"""Versioned profile persistence (FR-1, FR-2)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from jobagent.store.models import Profile


def add_profile(session: Session, data: dict, source_hash: str | None = None) -> Profile:
    """Insert a new profile version and deactivate every older one.

    Versions are append-only: the previous active row stays for audit, the new
    row becomes the single active master (FR-2).
    """
    max_version = session.execute(select(func.max(Profile.version))).scalar() or 0
    session.execute(update(Profile).values(active=False))  # deactivate all
    row = Profile(
        version=max_version + 1,
        source_pdf_hash=source_hash,
        active=True,
        data=data,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def get_active_profile(session: Session) -> Profile | None:
    return session.execute(select(Profile).where(Profile.active.is_(True))).scalar_one_or_none()


def count_profiles(session: Session) -> int:
    return session.execute(select(func.count(Profile.id))).scalar() or 0
