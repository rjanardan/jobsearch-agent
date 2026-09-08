"""Wiring smoke test: Postgres checkpointer persistence + one-node graph + OTel span.

Run: .venv/bin/python scripts/smoke.py
Requires: Postgres running (brew services start postgresql@17), Phoenix on :6006.
"""

import os
import time

PG_DSN = os.environ.get(
    "PG_DSN", "postgresql://jobagent:jobagent@localhost:5432/jobagent"
)


def main() -> None:
    # --- 1. LangGraph node + Postgres checkpointer ---------------------------
    from typing import TypedDict

    from langchain_core.runnables.config import RunnableConfig
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.graph import END, START, StateGraph

    class SmokeState(TypedDict, total=False):
        n: int

    def bump(state: SmokeState) -> SmokeState:
        return {"n": state.get("n", 0) + 1}

    graph = StateGraph(SmokeState)
    graph.add_node("bump", bump)
    graph.add_edge(START, "bump")
    graph.add_edge("bump", END)

    with PostgresSaver.from_conn_string(PG_DSN) as saver:
        saver.setup()  # creates checkpoint tables if absent
        app = graph.compile(checkpointer=saver)

        cfg: RunnableConfig = {"configurable": {"thread_id": "smoke-1"}}
        r1 = app.invoke({"n": 0}, cfg)
        r2 = app.invoke({}, cfg)  # resumes from checkpoint
        assert r1["n"] == 1 and r2["n"] == 2, f"checkpoint resume failed: {r1} {r2}"
        print(f"checkpointer OK: run1 n={r1['n']}, resumed run2 n={r2['n']}")

    # --- 2. OTel span -> Phoenix ---------------------------------------------
    try:
        from phoenix.otel import register

        tracer_provider = register(endpoint="http://127.0.0.1:4317")
        tracer = tracer_provider.get_tracer("jobsearch-agent.smoke")
        with tracer.start_as_current_span("smoke.wiring") as span:
            span.set_attribute("app", "jobsearch-agent")
            span.set_attribute("stage", "wiring-smoke")
        print("otel span OK: smoke.wiring emitted -> Phoenix (see :6006)")
    except Exception as exc:  # noqa: BLE001 - smoke should not hard-fail on trace
        print(f"otel span WARN (non-fatal): {exc}")

    print("SMOKE OK")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"elapsed {time.time() - t0:.1f}s")
