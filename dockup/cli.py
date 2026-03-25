"""dockup CLI — manage and interact with the backup service."""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from rich.text import Text

app = typer.Typer(name="dockup", help="Database backup manager CLI", add_completion=False)
console = Console()

_BASE_URL = "http://localhost:8080"
_TOKEN_FILE = ".dockup_token"


def _get_token() -> str:
    try:
        return open(_TOKEN_FILE).read().strip()
    except FileNotFoundError:
        return ""


def _client() -> httpx.Client:
    token = _get_token()
    headers = {"Authorization": token} if token else {}
    return httpx.Client(base_url=_BASE_URL, headers=headers, timeout=30)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8080, help="Bind port"),
    log_level: str = typer.Option("info", help="Log level"),
):
    """Start the dockup server."""
    import os
    os.environ["DOCKUP_API_HOST"] = host
    os.environ["DOCKUP_API_PORT"] = str(port)
    os.environ["DOCKUP_LOG_LEVEL"] = log_level
    from dockup.main import main
    asyncio.run(main())


@app.command()
def login(
    username: str = typer.Option("admin", prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    url: str = typer.Option(_BASE_URL, help="dockup API URL"),
):
    """Authenticate with the dockup API."""
    resp = httpx.post(f"{url}/api/v1/auth/login", json={"username": username, "password": password})
    if resp.status_code == 200:
        data = resp.json()
        with open(_TOKEN_FILE, "w") as f:
            f.write(data["access_token"])
        rprint(f"[green]✓ Logged in as {username} (role: {data['role']})[/green]")
    else:
        rprint(f"[red]✗ Login failed: {resp.json().get('detail', resp.text)}[/red]")
        raise typer.Exit(1)


@app.command("list")
def list_databases():
    """List all discovered database targets."""
    with _client() as c:
        resp = c.get("/api/v1/databases")
    if resp.status_code != 200:
        rprint(f"[red]Error: {resp.text}[/red]"); raise typer.Exit(1)
    dbs = resp.json()
    if not dbs:
        rprint("[yellow]No databases discovered.[/yellow]"); return

    table = Table(title="Discovered Databases", border_style="bright_black")
    for col in ["Name", "Type", "Host", "Port", "Schedule", "Retention", "Source", "Enabled"]:
        table.add_column(col, style="cyan" if col == "Name" else "white")
    for d in dbs:
        table.add_row(
            d["name"], d["db_type"], d["host"], str(d["port"]),
            d.get("schedule", "@daily"), f"{d.get('retention_days', 7)}d",
            d.get("source", "docker"),
            "[green]✓[/green]" if d.get("enabled") else "[red]✗[/red]",
        )
    console.print(table)


@app.command()
def backup(
    target: str = typer.Argument(..., help="Target ID or name"),
    wait: bool = typer.Option(True, help="Wait for backup to complete"),
):
    """Trigger a backup for a specific database target."""
    with _client() as c:
        # Find target by name if not ID
        dbs_resp = c.get("/api/v1/databases")
        dbs = dbs_resp.json() if dbs_resp.status_code == 200 else []
        target_id = target
        for db in dbs:
            if db["name"] == target or db["id"] == target:
                target_id = db["id"]
                break

        rprint(f"[cyan]Triggering backup for target: {target}[/cyan]")
        resp = c.post(f"/api/v1/backup/{target_id}")

    if resp.status_code != 200:
        rprint(f"[red]Error: {resp.json().get('detail', resp.text)}[/red]"); raise typer.Exit(1)

    result = resp.json()
    color = "green" if result["status"] == "success" else "red"
    rprint(f"[{color}]Backup {result['status']}: {result['target_name']}[/{color}]")
    rprint(f"  Job ID: {result['job_id']}")
    rprint(f"  Message: {result['message']}")


@app.command()
def history(
    target: Optional[str] = typer.Option(None, help="Filter by target ID"),
    limit: int = typer.Option(20, help="Number of jobs to show"),
):
    """Show backup job history."""
    with _client() as c:
        path = f"/api/v1/history/{target}" if target else "/api/v1/history"
        resp = c.get(path, params={"limit": limit})

    if resp.status_code != 200:
        rprint(f"[red]Error: {resp.text}[/red]"); raise typer.Exit(1)

    jobs = resp.json()
    if not jobs:
        rprint("[yellow]No backup history.[/yellow]"); return

    table = Table(title="Backup History", border_style="bright_black")
    for col in ["Job ID", "Target", "Type", "Status", "Duration", "Size", "Completed"]:
        table.add_column(col)
    for j in jobs:
        status_style = {"success": "green", "failed": "red", "running": "cyan"}.get(j["status"], "yellow")
        table.add_row(
            j["id"][:8] + "…", j["target_name"], j["db_type"],
            Text(j["status"], style=status_style),
            f"{j['duration_seconds']:.1f}s" if j.get("duration_seconds") else "—",
            _fmt_bytes(j.get("size_bytes", 0)),
            j.get("finished_at", "—"),
        )
    console.print(table)


@app.command()
def status():
    """Show system status."""
    with _client() as c:
        resp = c.get("/api/v1/status")
    if resp.status_code != 200:
        rprint(f"[red]Error: {resp.text}[/red]"); raise typer.Exit(1)
    d = resp.json()
    rprint(f"[bold]dockup v{d['version']}[/bold]")
    rprint(f"  Uptime: {_fmt_uptime(d['uptime_seconds'])}")
    rprint(f"  Discovered databases: [cyan]{d['discovered_databases']}[/cyan]")
    rprint(f"  Active workers: [cyan]{d['active_workers']}[/cyan]")
    rprint(f"  Queue depth: [cyan]{d['queue_depth']}[/cyan]")


def _fmt_bytes(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _fmt_uptime(s: float) -> str:
    if s < 60: return f"{s:.0f}s"
    if s < 3600: return f"{s/60:.0f}m"
    if s < 86400: return f"{s/3600:.1f}h"
    return f"{s/86400:.1f}d"


if __name__ == "__main__":
    app()
