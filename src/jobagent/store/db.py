"""Database engine and session management."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PG_DSN = os.environ.get(
    "PG_DSN", "postgresql+psycopg://jobagent:jobagent@localhost:5432/jobagent"
)

engine = create_engine(PG_DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope():
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _scope()
