"""CLI entrypoint for jobsearch-agent."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from jobagent import telemetry
from jobagent.store.db import session_scope
from jobagent.store.jobs import count_jobs, recent_jobs
from jobagent.store.matches import count_matches
from jobagent.store.models import Job, Match
from jobagent.store.profiles import add_profile, count_profiles, get_active_profile
from jobagent.tools.discover import run_discovery
from jobagent.tools.profile import ProfileParseError, load_profile, source_hash
from jobagent.tools.scout import run_matching

app = typer.Typer(help="Agentic job-search copilot")
console = Console()

CONFIG_DIR = Path(os.environ.get("JOBAGENT_CONFIG_DIR", "config"))


def _configs() -> tuple[dict, list[dict]]:
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as fh:
        sources = yaml.safe_load(fh) or {}
    companies: list[dict] = []
    comp_path = CONFIG_DIR / "companies.yaml"
    if comp_path.exists():
        with open(comp_path, encoding="utf-8") as fh:
            companies = yaml.safe_load(fh) or []
    return sources, companies


# ---------------------------------------------------------------- discovery

@app.command()
def discover() -> None:
    """Run the discovery pipeline across enabled sources."""
    sources, companies = _configs()
    with session_scope() as session:
        summary = run_discovery(session, sources, companies)
    table = Table(title="Discovery run")
    table.add_column("Source")
    table.add_column("Fetched")
    table.add_column("Inserted")
    table.add_column("Updated")
    table.add_column("Notes")
    total = {"fetched": 0, "inserted": 0, "updated": 0}
    for name, s in summary.items():
        table.add_row(
            name,
            str(s.get("fetched", "-")),
            str(s.get("inserted", "-")),
            str(s.get("updated", "-")),
            s.get("error", ""),
        )
        for k in total:
            total[k] += int(s.get(k, 0) or 0)
    console.print(table)
    console.print(f"total fetched={total['fetched']} inserted={total['inserted']} updated={total['updated']}")


@app.command()
def jobs(limit: int = 10) -> None:
    """Show the most recently discovered jobs."""
    with session_scope() as session:
        n = count_jobs(session)
        rows = recent_jobs(session, limit=limit)
    console.print(f"[bold]{n}[/bold] jobs in store\n")
    table = Table()
    for col in ("company", "title", "location", "source", "url"):
        table.add_column(col)
    for j in rows:
        table.add_row(j.company_name or "-", j.title or "-", j.location or "-", j.source, j.url or "-")
    console.print(table)


# ------------------------------------------------------------------ profile

profile_app = typer.Typer(help="Master profile (FR-1/2)")


@profile_app.command("load")
def profile_load(path: str) -> None:
    """Parse a resume (pdf/txt/md) or structured profile (yaml/json) into the store."""
    try:
        with telemetry.span("profile.load", attrs={"source": Path(path).name}):
            data = load_profile(path)
        with session_scope() as session:
            row = add_profile(session, data.model_dump(mode="json"), source_hash(path))
    except ProfileParseError as exc:
        console.print(f"[red]profile load failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]profile v{row.version} active[/green] — {data.name or '(unnamed)'} | "
        f"{len(data.skills)} skills, {len(data.domains)} domains"
    )


@profile_app.command("show")
def profile_show() -> None:
    """Show the active profile."""
    with session_scope() as session:
        n = count_profiles(session)
        p = get_active_profile(session)
    if p is None:
        console.print("no active profile — run `ja profile load <file>`")
        raise typer.Exit(1)
    d = p.data
    console.print(f"[bold]profile v{p.version}[/bold] (of {n} versions) — {d.get('name') or '(unnamed)'}")
    console.print(f"headline: {d.get('headline') or '-'} | location: {d.get('location') or '-'} | remote_ok: {d.get('remote_ok')}")
    skills = ", ".join(f"{s['name']}({s['proficiency']})" for s in d.get("skills", []))
    console.print(f"skills: {skills}")
    console.print(f"domains: {', '.join(d.get('domains', []))}")
    console.print(f"target levels: {', '.join(d.get('target_levels', []))}")


app.add_typer(profile_app, name="profile")


# ------------------------------------------------------------------- matching

@app.command()
def match(cutoff: float = 60.0, top: int = 10) -> None:
    """Score all active jobs against the active profile (FR-7..9)."""
    with session_scope() as session:
        try:
            summary = run_matching(session, cutoff=cutoff)
        except ProfileParseError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        rows = (
            session.execute(
                select(Match, Job)
                .join(Job, Job.id == Match.job_id)
                .where(Match.profile_version == summary["profile_version"])
                .order_by(Match.score.desc())
                .limit(top)
            )
            .all()
        )
        tally = count_matches(session, summary["profile_version"])
    console.print(
        f"[bold]{summary['jobs_total']}[/bold] jobs | {summary['policy_rejected']} policy-rejected | "
        f"{summary['scored']} scored | [green]{tally['passed']} passed[/green] (cutoff {cutoff})"
    )
    table = Table(title=f"Top {len(rows)} by score (profile v{summary['profile_version']})")
    for col in ("score", "pass", "company", "title", "location"):
        table.add_column(col)
    for m, j in rows:
        table.add_row(f"{m.score:.0f}", "Y" if m.passed else "n", j.company_name or "-", j.title or "-", j.location or "-")
    console.print(table)
    for m, j in rows[:5]:
        console.print(f"\n[bold cyan]{m.score:.0f}[/bold cyan] {j.company_name} — {j.title}")
        console.print(m.rationale or "(policy-rejected)")


# --------------------------------------------------------------------- nightly

@app.command()
def nightly(cutoff: float = 60.0, force: bool = False) -> None:
    """Run the scheduled graph: discover -> match (LangGraph, Postgres-checkpointed)."""
    from jobagent.graph.nightly import run_nightly

    try:
        state = run_nightly(cutoff=cutoff, force=force)
    except ProfileParseError as exc:
        console.print(f"[red]nightly failed:[/red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001 — unattended job: clean error beats a traceback
        console.print(f"[red]nightly failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(1)
    tag = "replayed (already ran for this thread)" if state.get("_replayed") else "ran"
    console.print(
        f"[bold]nightly {state.get('_run_id')}[/bold] — {tag} — thread {state.get('_thread_id')}"
    )
    d = state.get("discover") or {}
    total = {"fetched": 0, "inserted": 0, "updated": 0}
    for s in d.values():
        for k in total:
            total[k] += int(s.get(k, 0) or 0)
    errors = [n for n, s in d.items() if s.get("error")]
    line = f"discover: fetched={total['fetched']} inserted={total['inserted']} updated={total['updated']}"
    if errors:
        line += f" | source errors: {errors}"
    console.print(line)
    m = state.get("matches") or {}
    if m:
        console.print(
            f"match: {m.get('jobs_total')} jobs | {m.get('policy_rejected')} policy-rejected | "
            f"{m.get('scored')} scored | {m.get('passed')} passed"
        )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
