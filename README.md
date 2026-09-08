# jobsearch-agent

Open-source agentic job-search copilot. Nightly discovery across startup boards,
RSS feeds, and curated company career pages; profile-vs-role matching with an
explicit gap breakdown; per-role application artifacts (resume variant, cover
letter, prep pack) generated only after human approval; application status
synced to a versioned tracker.

## Design intent

A self-hosted, single-node replica of a managed agent platform's architecture
(Bedrock AgentCore reference): harness-orchestrated stage pipeline, MCP-style
tool gateway, Postgres state and memory, policy-enforced tool autonomy,
guardrails on model input/output, OpenTelemetry traces, and regression-gated
evaluation. Every component is open source; cloud spend is limited to LLM
inference.

## Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph + Postgres checkpointer |
| Tools | Domain services behind a tool layer (harness-swappable) |
| State | Postgres (psycopg, alembic migrations) |
| Models | LiteLLM router behind a thin ModelGateway interface; local Ollama for bulk work |
| Traces | OpenTelemetry export (Phoenix-compatible OTLP endpoint) |
| Runtime | uv-managed Python 3.12 on a single host; launchd/cron scheduling |

## Repository layout

```
src/jobagent/     graph, tools, adapters, models, guardrails, sync, cli, store
config/           *.example.yaml committed; real configs gitignored (personal)
private/          gitignored: profile, artifacts, sessions
tests/            golden-set evals, policy tests, sync contract tests
deploy/           optional docker-compose for VM deployment; launchd plist
```

## Status

Wiring stage: repository scaffold and model interface. No stages implemented
yet. See the requirements and design artifacts in `docs/` (in progress).
