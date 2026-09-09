"""Nightly LangGraph: discover -> match, resumable via a Postgres checkpointer.

The design's nightly chain — discover -> normalize -> policy filter -> prefilter
score (local) -> persist matches -> digest — is expressed over the implemented
services, which already own those stages: discovery fetches, extracts with a
local model, normalizes, and persists; matching applies the policy gate,
scores deterministically, and persists. Both services keep their own OTel
spans, so a graph run appears in Phoenix as one `nightly.run` trace whose
children are the familiar discover.* and match.* spans.

Resume semantics: the checkpointer keys runs by date (thread_id = YYYY-MM-DD).
Re-invoking a day that already completed replays its final state instead of
re-running; re-invoking after a failure resumes from the failed node. A manual
re-run passes force=True, which stamps a fresh thread id. Node writes are
committed per node (session_scope), so checkpoints align with DB commits.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import yaml
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import make_url

from jobagent import telemetry
from jobagent.store.db import PG_DSN, session_scope
from jobagent.tools.discover import run_discovery
from jobagent.tools.scout import run_matching

CONFIG_DIR = Path(os.environ.get("JOBAGENT_CONFIG_DIR", "config"))


class NightlyState(TypedDict, total=False):
    """State channels for the nightly graph (all checkpoint-serializable)."""

    run_id: str
    started_at: str
    cutoff: float
    discover: dict  # per-source summary from run_discovery
    matches: dict  # summary from run_matching


def _load_configs() -> tuple[dict, list[dict]]:
    """Real configs (sources.yaml, companies.yaml); mirrors the CLI loader."""
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as fh:
        sources = yaml.safe_load(fh) or {}
    companies: list[dict] = []
    comp_path = CONFIG_DIR / "companies.yaml"
    if comp_path.exists():
        with open(comp_path, encoding="utf-8") as fh:
            companies = yaml.safe_load(fh) or []
    return sources, companies


def _psycopg_dsn() -> str:
    """SQLAlchemy DSN (postgresql+psycopg://...) -> psycopg-native DSN."""
    url = make_url(PG_DSN).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def discover_node(state: NightlyState) -> dict:
    """Fetch + extract + normalize + persist every enabled source (FR-3..5)."""
    sources, companies = _load_configs()
    with session_scope() as session:
        return {"discover": run_discovery(session, sources, companies)}


def match_node(state: NightlyState) -> dict:
    """Policy gate + deterministic scoring + persist (FR-6..9)."""
    with session_scope() as session:
        return {"matches": run_matching(session, cutoff=float(state.get("cutoff", 60.0)))}


def build_graph(checkpointer=None):
    """discover -> match. Compiled without a checkpointer it is a plain pipeline."""
    graph = StateGraph(NightlyState)
    graph.add_node("discover", discover_node)
    graph.add_node("match", match_node)
    graph.add_edge(START, "discover")
    graph.add_edge("discover", "match")
    graph.add_edge("match", END)
    return graph.compile(checkpointer=checkpointer)


def run_nightly(cutoff: float = 60.0, force: bool = False) -> dict:
    """Run (or resume) today's nightly graph; returns the final state.

    force=True runs regardless of an earlier completion today (fresh thread id,
    FR-21 manual re-run). A completed thread re-invoked without force replays
    its stored final state — the caller can detect that via "_replayed".
    """
    day = datetime.now().astimezone().date().isoformat()
    now = datetime.now().astimezone()
    if force:
        thread_id = now.strftime("%Y%m%dT%H%M%S")
        run_id = f"{day}-force-{now.strftime('%H%M%S')}"
    else:
        thread_id = day
        run_id = f"{day}-nightly"
    started_at = now.isoformat(timespec="seconds")
    inputs: NightlyState = {"run_id": run_id, "started_at": started_at, "cutoff": cutoff}
    config: dict = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(_psycopg_dsn()) as checkpointer:
        checkpointer.setup()
        graph = build_graph(checkpointer)
        config: dict = {"configurable": {"thread_id": thread_id}}
        # Finished thread -> replay its stored state instead of re-running.
        # Crashed thread (nodes pending) -> invoke resumes from the failed node.
        snapshot = graph.get_state(config)  # type: ignore[arg-type]
        if not force and snapshot.values and not snapshot.next:
            final = {**snapshot.values}
            final["_run_id"] = run_id
            final["_thread_id"] = thread_id
            final["_replayed"] = True
            return final
        with telemetry.span(
            "nightly.run",
            attrs={"run_id": run_id, "thread_id": thread_id, "cutoff": cutoff},
        ) as sp:
            final = graph.invoke(inputs, config)  # type: ignore[arg-type]
            sp.set_attribute("replayed", False)
        final["_run_id"] = run_id
        final["_thread_id"] = thread_id
        final["_replayed"] = False
        return final
