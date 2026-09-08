# System design

## Repository layout

```
src/jobagent/
  graph/        LangGraph state, nodes, subgraphs, interrupts
  tools/        domain services (no harness imports)
  adapters/     boards, feeds, ATS, crawl, search, lookup, tracker
  models/       ModelGateway interface + implementations
  guardrails/   validators, moderation pass, policy module
  sync/         tracker fetch/merge/push engine
  cli/          command surface
  store/        Postgres access, alembic migrations
config/         *.example.yaml committed; real configs gitignored (personal)
private/        gitignored: profile, artifacts, sessions
tests/          golden-set evals, policy tests, sync contract tests
deploy/         optional compose for other hosts; scheduler plist
```

## Data model (abbreviated)

```sql
profile    (id, version, source_pdf_hash, active, data jsonb, created_at)
company    (id, slug unique, name, careers_type, careers_url, priority)
job        (id, company_id fk, source, source_id, fingerprint unique,
            title, level, location, remote, comp_min/max, currency, url,
            posted_at, skills jsonb, raw jsonb, active, first_seen, last_seen)
match      (id, job_id fk, profile_version, score, dimensions jsonb,
            gaps jsonb, rationale, passed, created_at,
            unique(job_id, profile_version))
application(id, job_id fk, tracker_uid, status, history jsonb,
            shortlisted_at, next_followup)
artifact   (id, application_id fk, kind, files jsonb, status, created_at)
followup   (id, application_id fk, due_on, action, done)
source_state (id, source, last_run_at, last_cursor, error jsonb, healthy)
```

`application.tracker_uid` links private state to the public tracker without
duplicating it; the public repo carries only its existing status vocabulary.

## Orchestration

Shared typed state with reducer-merged channels; Postgres checkpointer makes
every run resumable and every approval pause durable.

Nightly graph: discover -> normalize -> policy filter -> prefilter score
(local) -> reasoned top-N (API) -> persist matches -> digest. Per-node retry;
per-source health in `source_state`; one failing source never fails the run.

On-demand graph per shortlisted role:

```
shortlist_job
  -> [interrupt 1: approve shortlist]
  -> generate artifacts (variant rules + diff vs master, cover letter, answers)
  -> [interrupt 2: review artifacts]
  -> connection lookup (cap-enforced, cached, optional)
  -> intro drafts
  -> [interrupt 3: approve intro]
  -> tracker update -> schedule follow-ups
```

Three interrupts are the only write gates; every gate records who/what/when
into application history.

## Tool autonomy classes

- A — unattended: board/feed/ATS fetch, crawl, search, parse, tracker status
  writes.
- B — interrupt-gated: connection lookup and intro drafting (per-role opt-in,
  hard daily cap).
- C — manual only: anything that would transmit on the user's behalf.

Enforced by the policy module; a Cedar policy document ships alongside as the
reference-parity artifact.

## Tracker sync contract

1. Fetch origin; rebase the local mirror if advanced (never force-push).
2. Map roles to tracker entries by URL, then generated key.
3. Update only status/timestamp; append history with attribution. No new
   fields in the public schema.
4. New entries carry the tracker's required fields.
5. Push; on rejection rebase and retry (max 3); on persistent conflict stage
   locally and surface in the next digest.

## Model routing

| Task | Route |
|---|---|
| Extraction/classification of raw listings | local (Ollama) |
| Embeddings for prefilter | local |
| Match reasoning, gap rationale | API — only top-N after local prefilter |
| Resume variants, letters, prep packs | API — on-demand only |
| Moderation guardrail | local |
| Digest and trend prose | API — one small call |

## Scheduling and interfaces

- Scheduler-driven nightly run; CLI for everything interactive
  (scout, shortlist, artifacts, prep, status, trend, sync, digest).
- Manual re-run and backfill commands per source.
