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

## System design

What the nightly run executes, from entry to persistence, and the services every stage shares. Milestone detail for matching and the nightly graph lives further down; this is the component view.

```text
┌──────────────────────────────────────────────────────────────┐
│ENTRY                                                         │
│launchd agent 02:30 daily      ja CLI: discover | match       │
│nightly [--force] — one code path: scheduler = CLI = graph    │
┌──────────────────────────────────────────────────────────────┐
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ORCHESTRATION  graph/nightly.py  (LangGraph)                  │
│nodes wrap the instrumented stage services; NightlyState      │
│carries run_id/cutoff/counters; PostgresSaver keeps a         │
│date-keyed thread: a finished day replays stored state,       │
│a crashed run resumes at the failed node; --force re-runs     │
┌──────────────────────────────────────────────────────────────┐
                               ▼
┌──────────────────────────────────────────────────────────────┐
│DISCOVER  tools/discover.py — run_discovery()                 │
│fetch    adapters: hn.algolia + hnrss.org (HN who-is-hiring), │
│         Greenhouse (?content=true), Lever, Ashby             │
│extract  local qwen3:4b via the model gateway — raw listing   │
│         text never leaves this host                          │
│normalize → persist → jobs + source_state; per-source         │
│         health — one failing source never fails the run      │
┌──────────────────────────────────────────────────────────────┐
                               ▼
┌──────────────────────────────────────────────────────────────┐
│MATCH  tools/scout.py + tools/match.py — run_matching()       │
│1 policy gate  guardrails/policy.py · config/filters.yaml     │
│2 score        deterministic, explainable, no model call:     │
│               role .30 · skills .25 · seniority .15 ·        │
│               location .20 · comp .10 — evidence per dim     │
│3 persist + digest → match rows + daily summary table         │
┌──────────────────────────────────────────────────────────────┐
                               ▼
┌──────────────────────────────────────────────────────────────┐
│SHARED RAILS — read and written by every stage                │
│Postgres 17 + pgvector   8 tables, alembic: jobs · match ·    │
│                        profiles jsonb (versioned, active) ·  │
│                        source_state                          │
│Model gateway (LiteLLM)  local today: Ollama qwen3:4b extract,│
│                        nomic-embed-text embeddings; DeepSeek │
│                        API route reserved for M6 on-demand   │
│                        reasoning                             │
│Telemetry  OTel spans from every service → Arize Phoenix      │
│                        (OTLP :4317, UI :6006) — one tree     │
│                        trace per nightly run                 │
│Scheduler  launchd plists + idempotent installer; Phoenix     │
│                        kept alive under launchd              │
┌──────────────────────────────────────────────────────────────┐
```

### Component catalog

| Component | Purpose | Interface |
|---|---|---|
| Launchd agents `deploy/*.plist` | run the job unattended; keep Phoenix alive across reboots | `com.jobsearch-agent.nightly` fires `ja nightly` at 02:30; `com.jobsearch-agent.phoenix` runs under KeepAlive; logs land in `~/Library/Logs/jobsearch-agent/`; `install-services.sh` / `uninstall-services.sh` manage both idempotently |
| CLI `ja` | interactive entry to every capability — the same code path the scheduler and the graph use | Typer subcommands: `discover`, `jobs`, `profile load\|show`, `match`, `nightly [--force]`, `smoke` (see Usage) |
| Nightly graph `graph/nightly.py` | orchestrates the stages as a durable LangGraph state machine | `build_graph(checkpointer)` composes `discover` → `match` nodes; `run_nightly(cutoff, force)` drives it; state is the `NightlyState` TypedDict; `PostgresSaver` keeps date-keyed threads — a finished day replays stored state in ~1 s, a crashed run resumes at the failed node |
| Discover `tools/discover.py` | fetch, extract, normalize, persist listings per source | `run_discovery()`; per-source fault isolation; writes `jobs` + `source_state` health rows |
| Adapters | one board-specific fetcher per source | hn.algolia.com + hnrss.org (HN who-is-hiring), Greenhouse with `?content=true` for full descriptions, Lever, Ashby — each returns normalized listing dicts |
| Extraction (model gateway) | turn raw listing text into structured job fields | local `qwen3:4b` chat call; raw listing text reaches only local Ollama (NFR-1) |
| Policy `guardrails/policy.py` | pre-score filter that states a reason | `evaluate(job) → allow \| reject + reason`; rule set in `config/filters.yaml` |
| Match `tools/match.py` | deterministic, explainable scoring | `score(job, profile)` → total, per-dimension evidence, gaps, rationale; dims role .30 · skills .25 · seniority .15 · location .20 · comp .10 |
| Runner `tools/scout.py` | the match choke point: gate → score → persist | `run_matching(cutoff)` writes `match` rows and prints the daily digest |
| Profile `tools/profile.py`, `store/profiles.py` | resume → versioned structured profile, the match target | `ja profile load <file>` reads txt/md/pdf resumes and YAML/JSON profiles; store keeps versions with an active flag |
| Store `store/` | persistence and schema evolution | SQLAlchemy models on Postgres 17 + pgvector; alembic migrations; tables `app`, `source`, `jobs`, `match`, `source_state`, `profiles` + joins |
| Model gateway `models/` | one interface to every model; the routing decision lives here | `chat()` / `embed()`; local route = Ollama `qwen3:4b`, `nomic-embed-text`; API route (DeepSeek) reserved for M6 on-demand reasoning |
| Telemetry `telemetry.py` | one shared tracing surface for every service | OTel spans per service call → Phoenix over OTLP `:4317`, UI `:6006`; each nightly run is one tree trace (`nightly.run` → stage spans) |
| Phoenix (Arize, OSS) | trace store and dashboard | OTLP ingest; local UI; data in `~/.phoenix/phoenix.db` |

### Why it is shaped this way

- The graph is thin: stages are plain services with one choke point each (`run_discovery`, `run_matching`), so the identical code runs from the CLI, the scheduler, or LangGraph — FR-20.
- Replay is a property of the checkpointer, not of job logic. A finished day's run is one `get_state()` call; nothing re-fetches.
- Every service emits spans through one telemetry module, so there is no per-stage wiring to maintain and every run is a single tree trace.
- Privacy is a boundary, not a feature: raw listing and resume text route to local models only; the API route sees sanitized data, and only from M6 onward.
- Planned extension: M6 on-demand graph with human interrupts, M7 LinkedIn source, M8 tracker sync and evals — all land on the same store and rails.

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
| M2 discovery | ✅ HN / RSS / ATS adapters, local-model extraction, 421 jobs, source health |
| M3 profile | ✅ versioned profile store, resume parser (txt/md/pdf via local model), YAML/JSON load |
| M4 matching | ✅ deterministic explainable scoring, policy gate, digest, golden-set tests |
| M5 nightly graph | ✅ LangGraph `discover -> match`, Postgres checkpointer, replay-safe threads, launchd plist |
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
ja nightly           # scheduled graph: discover -> match (checkpointed, replay-safe)
ja nightly --force   # re-run today with a fresh thread
```

### Nightly graph (M5)

`src/jobagent/graph/nightly.py` wires the two stage services into a LangGraph:
`discover` (fetch + local-model extract + normalize + persist) then `match`
(policy gate + deterministic score + persist). A Postgres checkpointer keys runs
by date: a finished day replays its stored state instead of re-running; a
crashed run resumes from its failed node. One `nightly.run` OTel span wraps the
invocation, so a scheduled run shows up in Phoenix as a single tree-shaped trace
(`discover.*` and `match.*` spans nest under it). The scheduler is a launchd
LaunchAgent — `deploy/com.jobsearch-agent.nightly.plist` (02:30 daily) plus a
Phoenix keepalive agent; `deploy/install-services.sh` installs both.

### Matching design (FR-7..9)

Deterministic local prefilter scoring, no model call: dimensions `role`,
`skills`, `seniority`, `location`, `comp` (weights 0.30/0.25/0.15/0.20/0.10),
each recorded with evidence. Every score stores its dimension breakdown, gap
list, and rationale in the `match` table. Policy filters (`config/filters.yaml`,
FR-6) run before scoring; below-cutoff roles stay searchable (FR-8).

```bash
ja match --cutoff 60 --top 10
# 421 jobs | 0 policy-rejected | 421 scored | 2 passed (cutoff 60.0)
# score  pass  company  title  location
#   60    Y    Airbnb   Senior Staff Machine Learning Engineer, Trust  Remote - USA
```

Tests: `tests/test_match.py` holds the golden-set regression (synthetic roles
with expected ordering/dimensions); `tests/test_profile.py` covers schema
validation and resume-text handling.
