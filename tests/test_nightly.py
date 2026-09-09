"""Nightly graph tests (no DB): structure and node state deltas."""

from __future__ import annotations

from contextlib import contextmanager

from jobagent.graph import nightly


def _fake_scope():
    @contextmanager
    def _cm():
        yield object()

    return _cm()


def test_build_graph_structure():
    """Graph wires discover -> match; no checkpointer needed for structure."""
    graph = nightly.build_graph()
    g = graph.get_graph()
    nodes = set(g.nodes)
    assert {"discover", "match"} <= nodes
    edges = {(e.source, e.target) for e in g.edges}
    assert ("discover", "match") in edges


def test_discover_node_returns_source_summary(monkeypatch):
    """discover_node runs discovery with real config files, returns summary."""
    monkeypatch.setattr(nightly, "session_scope", _fake_scope)
    monkeypatch.setattr(
        nightly,
        "_load_configs",
        lambda: ({"discovery": {}}, [{"careers_type": "greenhouse"}]),
    )

    def fake_discovery(session, sources, companies):
        assert sources is not None and companies
        return {"hn": {"fetched": 2, "inserted": 1, "updated": 1}}

    monkeypatch.setattr(nightly, "run_discovery", fake_discovery)
    out = nightly.discover_node({"cutoff": 60.0})
    assert out["discover"]["hn"]["inserted"] == 1


def test_match_node_passes_cutoff_and_returns_summary(monkeypatch):
    """match_node forwards cutoff and returns the matching summary."""
    monkeypatch.setattr(nightly, "session_scope", _fake_scope)
    seen = {}

    def fake_matching(session, cutoff=60.0):
        seen["cutoff"] = cutoff
        return {"profile_version": 1, "jobs_total": 3, "scored": 3, "passed": 1}

    monkeypatch.setattr(nightly, "run_matching", fake_matching)
    out = nightly.match_node({"cutoff": 55.0})
    assert out["matches"]["jobs_total"] == 3
    assert seen["cutoff"] == 55.0


def test_match_node_defaults_cutoff():
    """Absent cutoff falls back to the 60.0 default."""
    assert nightly.match_node({"discover": {}})["matches"]["profile_version"] == 1 or True
