"""SQLAlchemy models for the jobsearch-agent store."""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    source_pdf_hash: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(default=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    careers_type: Mapped[str | None] = mapped_column(String(32))  # greenhouse|lever|ashby|workday|custom
    careers_url: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(default=5)


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"))
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str | None] = mapped_column(String(256))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    company_name: Mapped[str | None] = mapped_column(String(256))
    level: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(256))
    remote: Mapped[str | None] = mapped_column(String(16))
    comp_min: Mapped[int | None] = mapped_column(Integer)
    comp_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(8))
    url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)  # full listing text (match + artifact input)
    skills: Mapped[dict | None] = mapped_column(JSONB)
    raw: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list | None] = mapped_column(Vector(768))
    active: Mapped[bool] = mapped_column(default=True, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    __tablename__ = "match"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), index=True)
    profile_version: Mapped[int] = mapped_column(default=1)
    score: Mapped[float] = mapped_column(Float)
    dimensions: Mapped[dict] = mapped_column(JSONB, default=dict)
    gaps: Mapped[list] = mapped_column(JSONB, default=list)
    rationale: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("job_id", "profile_version", name="uq_match_job_profile"),)


class Application(Base):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), index=True)
    tracker_uid: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="researching", index=True)
    history: Mapped[list] = mapped_column(JSONB, default=list)
    shortlisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_followup: Mapped[date | None] = mapped_column(Date)


class Artifact(Base):
    __tablename__ = "artifact"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # resume_variant|cover_letter|answers|prep_pack|tmay|intro_draft
    files: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|sent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Followup(Base):
    __tablename__ = "followup"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id"), index=True)
    due_on: Mapped[date] = mapped_column(Date, index=True)
    action: Mapped[str] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(default=False)


class SourceState(Base):
    __tablename__ = "source_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), unique=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_cursor: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict | None] = mapped_column(JSONB)
    healthy: Mapped[bool] = mapped_column(default=True)
