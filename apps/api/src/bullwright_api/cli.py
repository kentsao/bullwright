"""`bw` — the operator CLI. Key minting happens here (never via the API),
so admin credentials only ever exist in the operator's terminal."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from bullwright_core.ids import new_id
from bullwright_db import make_engine, make_session_factory, session_scope
from bullwright_db.models import Agent, ApiKey, Ticker
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import bullwright_api.auth.keys as keys
from bullwright_api.settings import settings

app = typer.Typer(name="bw", help="Bullwright operator CLI", no_args_is_help=True)
keys_app = typer.Typer(help="API key management", no_args_is_help=True)
agents_app = typer.Typer(help="Agent identities", no_args_is_help=True)
tickers_app = typer.Typer(help="Watchlist", no_args_is_help=True)
app.add_typer(keys_app, name="keys")
app.add_typer(agents_app, name="agents")
app.add_typer(tickers_app, name="tickers")


def _factory() -> "sessionmaker[Session]":
    return make_session_factory(make_engine(settings().db_url))


@app.command()
def serve(host: str | None = None, port: int | None = None) -> None:
    """Run the API server (dev)."""
    import uvicorn

    cfg = settings()
    host = host or cfg.api_host
    if host not in ("127.0.0.1", "localhost"):
        typer.secho(
            "WARNING: binding beyond localhost — Bullwright is not hardened "
            "for public exposure (docs/API.md §6).",
            fg=typer.colors.RED,
        )
    uvicorn.run(
        "bullwright_api.app:create_app",
        factory=True,
        host=host,
        port=port or cfg.api_port,
        log_level=cfg.log_level,
    )


@app.command("db-upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to head."""
    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).parents[4].parent / "packages" / "db" / "alembic.ini"
    # Resolve relative to repo root when running from a checkout.
    if not ini.exists():
        ini = Path("packages/db/alembic.ini").resolve()
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", settings().db_url)
    command.upgrade(cfg, "head")
    typer.echo("migrated to head")


@app.command("openapi-export")
def openapi_export(out: Path = Path("docs/openapi.json")) -> None:
    """Write the OpenAPI spec to docs/openapi.json (CI checks drift)."""
    from bullwright_api.app import create_app

    spec = create_app().openapi()
    out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    typer.echo(f"wrote {out}")


@app.command("export-blog")
def export_blog_cmd(
    out: Path = Path("apps/web/src/content"),
) -> None:
    """Regenerate blog content from published reports."""
    from bullwright_api.export_blog import export_published

    with session_scope(_factory()) as s:
        n = export_published(s, out)
    typer.echo(f"exported {n} published report(s) to {out}")


@agents_app.command("create")
def agents_create(
    name: str,
    kind: str = typer.Option(..., help="cloud | local | human"),
    model: str | None = typer.Option(None, help="default model id"),
) -> None:
    if kind not in ("cloud", "local", "human"):
        raise typer.BadParameter("kind must be cloud|local|human")
    with session_scope(_factory()) as s:
        if s.scalars(select(Agent).where(Agent.name == name)).first():
            raise typer.BadParameter(f"agent {name!r} already exists")
        agent = Agent(agent_id=new_id("agt"), name=name, kind=kind, default_model=model)
        s.add(agent)
        typer.echo(f"created agent {name} ({agent.agent_id})")


@keys_app.command("create")
def keys_create(
    agent: str = typer.Option(..., help="agent name"),
    scopes: str = typer.Option(..., help="comma-separated scopes"),
    expires_days: int | None = typer.Option(None, help="expiry in days"),
) -> None:
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    with session_scope(_factory()) as s:
        row = s.scalars(select(Agent).where(Agent.name == agent)).first()
        if row is None:
            raise typer.BadParameter(f"no agent named {agent!r} — create it first")
        expires = datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
        try:
            plaintext, key_row = keys.mint_key(
                s, row, scope_list, env=settings().env_key_label(), expires_at=expires
            )
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        typer.echo(f"key_id: {key_row.key_id}")
        typer.secho(plaintext, fg=typer.colors.GREEN, bold=True)
        typer.echo("Shown ONCE. Store it in the agent's environment as BW_API_KEY.")


@keys_app.command("bootstrap")
def keys_bootstrap() -> None:
    """First-run: create the operator identity + an admin key."""
    with session_scope(_factory()) as s:
        existing = s.scalars(select(Agent).where(Agent.name == "operator")).first()
        if existing:
            raise typer.BadParameter("operator already exists; use `bw keys create`")
        operator = Agent(agent_id=new_id("agt"), name="operator", kind="human")
        s.add(operator)
        s.flush()
        plaintext, key_row = keys.mint_key(s, operator, ["admin"], env=settings().env_key_label())
        typer.echo(f"operator agent: {operator.agent_id}\nkey_id: {key_row.key_id}")
        typer.secho(plaintext, fg=typer.colors.GREEN, bold=True)
        typer.echo("Shown ONCE. This is your admin key — treat it like a password.")


@keys_app.command("revoke")
def keys_revoke(key_id: str) -> None:
    with session_scope(_factory()) as s:
        row = s.get(ApiKey, key_id)
        if row is None:
            raise typer.BadParameter(f"no key {key_id!r}")
        row.revoked_at = datetime.now(UTC)
        typer.echo(f"revoked {key_id}")


@tickers_app.command("add")
def tickers_add(
    symbol: str,
    exchange: str = typer.Option("NASDAQ"),
    name: str | None = typer.Option(None),
    sector: str | None = typer.Option(None),
) -> None:
    with session_scope(_factory()) as s:
        row = Ticker(
            ticker_id=new_id("tkr"),
            symbol=symbol.upper(),
            exchange=exchange,
            name=name,
            sector=sector,
        )
        s.add(row)
        typer.echo(f"added {symbol.upper()} ({row.ticker_id})")


if __name__ == "__main__":
    app()
