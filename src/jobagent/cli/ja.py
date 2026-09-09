"""CLI entrypoint for jobsearch-agent."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from jobagent.store.db import session_scope
from jobagent.store.jobs import count_jobs, recent_jobs
from jobagent.tools.discover import run_discovery

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
