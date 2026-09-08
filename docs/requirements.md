# Requirements

## Goals

A self-hosted, open-source agentic job-search copilot: nightly discovery of
roles, profile-vs-role matching with an explicit gap breakdown, per-role
application artifacts, and application tracking — built as a close replica of a
managed agent platform's architecture (Bedrock AgentCore as reference), using
only open-source components. Cloud spend is limited to LLM inference and GPU
compute.

## Governing constraints

- 100% open-source software stack; no proprietary services in the build.
- Cloud compute only where raw GPU or model weights are required.
- Human-in-the-loop: the system prepares and stages; a human sends, submits,
  and approves. It never transmits anything externally on its own.

## Functional requirements

### Profile

- FR-1 Parse a resume PDF into a structured profile: skills with proficiency,
  roles, experience, domains, education, location, compensation bar.
- FR-2 Versioned master profile plus variant rules per target type. Variants
  frame and trim only; titles stay factual; no softening or inflation. Rules
  are data, not prompts.

### Discovery

- FR-3 Nightly sweep over startup job boards, "who is hiring" threads, and
  subscribed feeds; incremental and source-health-tracked.
- FR-4 Curated-company scanner over career pages and public ATS feeds for a
  seeded target list.
- FR-5 Canonical job record with a dedupe fingerprint; re-scans never
  duplicate.
- FR-6 Filters (location, remote, level, compensation) enforced as policy, not
  prompt text.

### Matching

- FR-7 Match score 0-100 with a per-dimension breakdown and an explicit gap
  list.
- FR-8 Ranking digest, threshold-gated; below-cutoff roles stay searchable.
- FR-9 Every score is explainable and traceable to profile lines and role
  text.

### Artifacts

- FR-10 Tailored resume variant, cover letter, application-form answers —
  staged for review with a diff against the master.
- FR-11 Interview prep pack: role-specific questions, a "tell me about
  yourself" draft, company backgrounder.

### Connections

- FR-12 Optional per-role lookup of the candidate's connections at the hiring
  company; hard daily cap enforced in code; results cached.
- FR-13 Intro-message drafts per contact — approval-gated.

### Tracking

- FR-14 Application state machine: research -> saved -> applied -> responded ->
  interview -> offer / rejected / withdrawn, with history.
- FR-15 Follow-up scheduler with per-stage cadence.
- FR-16 Sync engine writing statuses to a versioned public tracker (JSON,
  git-mastered; fetch-merge-push, never force). All private detail stays in a
  local private store, keyed to tracker entries — the public schema is not
  extended.

### Analysis

- FR-17 Weekly trend pass over collected roles -> recurring skill demand vs the
  profile -> upskilling suggestions.
- FR-18 Market calibration signals (level, compensation) per segment.
- FR-19 Single weekly digest: new matches, status changes, follow-ups due,
  trends.

### Operations

- FR-20 Every run and decision is traced and re-runnable.
- FR-21 Manual re-run, backfill, and per-source disable commands.

## Non-functional requirements

- NFR-1 Privacy: strict public/private split; nothing personal in the public
  repo.
- NFR-2 Cost: API spend target on the order of a few dollars a month; all bulk
  work routed to local models.
- NFR-3 Runtime: nightly pipeline under ~30 minutes; on-demand artifact
  generation in minutes; single-node, self-hosted.
- NFR-4 Observability: traces per run and per request; structured logs.
- NFR-5 Evaluation: fixed golden set of synthetic roles as a match-scoring
  regression; score-drift alerts.
- NFR-6 Reliability: connector failures degrade gracefully — log, skip, retry
  next cycle.
- NFR-7 Security: secrets via environment; personal-data sources isolated from
  the core.
- NFR-8 Maintainability: stage-based layout; configuration as code.
