# jobsearch-agent

Open-source agentic job-search copilot. Nightly discovery across startup boards,
RSS feeds, and curated company career pages; profile-vs-role matching with an
explicit gap breakdown; per-role application artifacts (resume variant, cover
letter, prep pack) generated only after human approval; application status
synced to a versioned tracker.

## Design intent

A self-hosted, single-node replica of a managed agent platform's architecture: harness-orchestrated stage pipeline, MCP-style
tool gateway, Postgres state and memory, policy-enforced tool autonomy,
guardrails on model input/output, OpenTelemetry traces, and regression-gated
evaluation. Every component is open source; cloud spend is limited to LLM
inference.

## Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph + Postgres checkpointer |
| Tools | Domain services behind a tool layer (harness-swappable) |
| State | Postgres 17 (psycopg, alembic migrations) |
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

| Milestone | State |
|---|---|
| M1 store schema | ✅ 8 tables + alembic `9b6cb6ba60ef`, `0f2a166e0056` (job.description) |
| M2 discovery | ✅ HN / RSS / ATS adapters, local-model extraction, 415+ jobs, source health |
| M3 profile | ✅ versioned profile store, resume parser (txt/md/pdf via local model), YAML/JSON load |
| M4 matching | ✅ deterministic explainable scoring, policy gate, digest, golden-set tests |
| M5 nightly graph | ⏳ LangGraph wiring + scheduler |
| M6 artifacts | ⏳ resume variants, cover letters, HITL interrupts |
| M7 connections | ⏳ LinkedIn lookup (cap-enforced) |
| M8 sync + evals | ⏳ tracker sync, eval harness |

### CLI

```bash
ja discover          # fetch + extract + persist across enabled sources
ja jobs              # recent jobs
ja profile load <f>  # resume (pdf/txt/md) or structured profile (yaml/json)
ja profile show      # active profile
ja match             # score all active jobs; digest table with gaps
```

### Matching design (FR-7..9)

Deterministic local prefilter scoring, no model call: dimensions `role`,
`skills`, `seniority`, `location`, `comp` (weights 0.30/0.25/0.15/0.20/0.10),
each recorded with evidence. Every score stores its dimension breakdown, gap
list, and rationale in the `match` table. Policy filters (`config/filters.yaml`,
FR-6) run before scoring; below-cutoff roles stay searchable (FR-8).

```bash
ja match --cutoff 60 --top 10
# 418 jobs | 0 policy-rejected | 418 scored | 2 passed (cutoff 60.0)
# score  pass  company  title  location
#   60    Y    Airbnb   Senior Staff Machine Learning Engineer, Trust  Remote - USA
```

Tests: `tests/test_match.py` holds the golden-set regression (synthetic roles
with expected ordering/dimensions); `tests/test_profile.py` covers schema
validation and resume-text handling.
