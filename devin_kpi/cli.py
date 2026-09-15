"""CLI: `python -m devin_kpi <command>`.

Commands: collect, enrich, demo-data, export-kpis, scope.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from devin_kpi.config import Settings
from devin_kpi.store import Store

app = typer.Typer(help="Devin Enterprise KPI reporting backend.")


def _parse_dt(value: str) -> datetime:
    """Accept 'YYYY-MM-DD' or a relative offset like '90d', '24h'."""
    m = re.fullmatch(r"(\d+)([dh])", value.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return datetime.now(tz=UTC) - (timedelta(days=n) if unit == "d" else timedelta(hours=n))
    return datetime.fromisoformat(value.strip()).replace(tzinfo=UTC)


def _settings() -> Settings:
    return Settings()


def _open_store(settings: Settings) -> Store:
    if settings.demo_mode:
        from devin_kpi.synth.generate import ensure_demo_db

        return ensure_demo_db(settings)
    return Store(settings.DATABASE_PATH)


@app.command()
def collect(
    since: str = typer.Option("90d", help="Start (YYYY-MM-DD or Nd/Nh)"),
    until: str = typer.Option("now", help="End (YYYY-MM-DD or Nd/Nh)"),
) -> None:
    """Pull Devin API data into the local SQLite store."""
    settings = _settings()
    if settings.demo_mode:
        typer.echo("No DEVIN_API_KEY set — nothing to collect (demo mode).")
        raise typer.Exit(1)
    store = Store(settings.DATABASE_PATH)
    start = _parse_dt(since)
    end = datetime.now(tz=UTC) if until == "now" else _parse_dt(until)
    from devin_kpi.collector.run import collect as run_collect

    run_collect(settings, start, end, store)
    typer.echo(f"Collected into {store.path}: {store.count('sessions')} sessions.")


@app.command()
def enrich() -> None:
    """Run git-provider and issue-tracker enrichment on collected data."""
    settings = _settings()
    store = _open_store(settings)
    from devin_kpi.enrichment.git_providers import build_providers, enrich_prs
    from devin_kpi.enrichment.trackers import build_trackers, enrich_issues

    n_pr = enrich_prs(store, build_providers(settings))
    n_issue = enrich_issues(store, build_trackers(settings))
    typer.echo(f"Enriched {n_pr} PRs, {n_issue} issues.")


@app.command(name="demo-data")
def demo_data(seed: int = typer.Option(42, help="RNG seed")) -> None:
    """Generate (or regenerate) the synthetic demo dataset."""
    settings = _settings()
    path = Path(settings.DEMO_DATABASE_PATH)
    if path.exists():
        typer.echo(f"Demo DB already exists at {path}; delete it to regenerate.")
    from devin_kpi.synth.generate import generate

    store = Store(path)
    stats = generate(store, seed=seed)
    typer.echo(f"Demo data at {path}: {stats}")


@app.command(name="export-kpis")
def export_kpis(
    start: str = typer.Option("90d", help="Start (YYYY-MM-DD or Nd)"),
    end: str = typer.Option("now", help="End (YYYY-MM-DD or Nd)"),
    out: str = typer.Option("kpis.csv", help="Output CSV path"),
) -> None:
    """Export the full KPI table (current vs previous period) to CSV."""
    settings = _settings()
    store = _open_store(settings)
    from devin_kpi.kpis.filters import FilterSet
    from devin_kpi.kpis.formulas import current_and_previous

    s = _parse_dt(start)
    e = datetime.now(tz=UTC) if end == "now" else _parse_dt(end)
    f = FilterSet(start=s, end=e)
    table = current_and_previous(
        store.read_df("sessions"),
        store.read_df("session_prs"),
        store.read_df("session_insights"),
        store.read_df("session_issues"),
        store.read_df("consumption_daily"),
        f,
        settings,
    )
    table.to_csv(out, index=False)
    typer.echo(f"Wrote {len(table)} KPIs to {out}")


@app.command()
def scope() -> None:
    """Detect and print the API key's scope (enterprise or organization)."""
    settings = _settings()
    if settings.demo_mode:
        typer.echo("demo (no DEVIN_API_KEY)")
        raise typer.Exit(0)
    from devin_kpi.api.client import DevinClient

    with DevinClient(
        settings.DEVIN_API_KEY, settings.DEVIN_API_BASE_URL, settings.DEVIN_ORG_ID
    ) as client:
        detected = client.detect_scope(int(datetime.now(tz=UTC).timestamp()))
    typer.echo(detected)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app()


if __name__ == "__main__":
    main()
