# Architecture

## Shape

Single-node, self-hosted system with two execution modes over one LangGraph
orchestrator:

- **Nightly batch** (scheduler): discovery -> normalize -> filter -> match ->
  digest. Bulk work on local models.
- **On-demand** (CLI, per shortlisted role): artifacts, interview prep,
  connection lookup. Reasoning on an API model.

## Topology

```
                 +----------------------------------------------+
  scheduler/CLI  |  LangGraph orchestrator (Postgres checkpoints)|
                 |  discover->normalize->filter->match->shortlist|
                 |  ->artifacts->prep->lookup->tracker->digest   |
                 +-------+-----------------+---------+-----------+
                         | tool calls      | traces  | policy
                 +-------v-------+  +------v------+ +v-----------+
                 | tool layer    |  |  Phoenix    | | guardrails  |
                 | (harness-     |  | (OTel span  | +------------+
                 |  swappable)   |  |  store)     |
                 +---+---+---+---+  +-------------+
        adapters: boards | feeds | ATS APIs | career crawl | search | lookup
                 +-------v----------------------+
                 | Postgres + pgvector          |
                 | state, jobs, matches, memory |
                 +-----------------------------+
                 Model gateway (thin interface): API model (reasoning) +
                 local Ollama (bulk, embeddings, moderation)
```

## Layer decisions

| Layer | Choice | Rationale |
|---|---|---|
| Orchestration | LangGraph + Postgres checkpointer | staged pipeline with resume-after-crash and first-class human interrupts |
| Harness portability | graph nodes call domain services only | LangGraph today, another harness tomorrow = wiring change, not rewrite |
| Tool bus | MCP-style tool layer over domain services | same contract any harness can consume |
| State/memory | Postgres 16 + pgvector | one engine for checkpoints, jobs, matches, vector search |
| Policy | typed policy module (unit-tested) + Cedar policy document for tool permissions | deterministic, testable; mirrors managed-platform policy pillar |
| Guardrails | deterministic validators + local-model moderation pass | private data never leaves the host unscrubbed |
| Observability | OpenTelemetry -> Phoenix (self-hosted) | single-process store that fits an 8 GB host; exporter abstraction keeps heavier backends (ClickHouse-class) as an option |
| Models | LiteLLM behind a thin gateway interface | router swappable; local Ollama for bulk, API for reasoning |
| Evaluation | golden-set regression (pytest) | scoring drift caught on every change |

## Cost and resource posture

- Nightly batch ~free: local extraction, embeddings, moderation.
- On-demand sessions: small per-session API spend (reasoning/writing only).
- Peak RAM budget ~5 GB on an 8 GB host; batch and browser workloads never
  overlap.

## Security boundaries

- Secrets via environment; nothing in git.
- Candidate data (profile, artifacts, session state) lives in a gitignored
  private store and is scrubbed before any external model call; only local
  models see the full profile.
- LinkedIn-style personal-account access is an isolated, low-volume,
  opt-in module with hard caps.
