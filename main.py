# main.py
"""
Inventor Automation CLI

Usage:
  python main.py extract input/assembly.iam
  python main.py modify input/part.ipt --changes '{"Width": "150 mm"}'
  python main.py ask "make the cylinders 20cm longer" --file input/assembly.iam
  python main.py ask "make the cylinders 20cm longer"   # uses currently open doc
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # loads .env from cwd or any parent — must run before os.environ reads

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from inventor_api import InventorConnection
from extract import extract_all
from modify import set_parameters_batch, save_as, open_in_inventor
from utils import ensure_dirs, write_json, write_csv, output_path
from agent.llm import ClaudeLLMClient, ClaudeCodeCLIClient
from agent.loop import AgentLoop, ToolExecutor

app = typer.Typer(help="Autodesk Inventor automation agent")
console = Console()


def get_connection(file_path: Optional[Path] = None) -> tuple[InventorConnection, object]:
    """
    Connect to Inventor and optionally open a file.
    Returns (connection, document).
    """
    conn = InventorConnection()
    conn.connect(launch_if_not_running=True)

    if file_path:
        doc = conn.open_document(file_path.resolve())
        console.print(f"[green]Opened:[/green] {file_path}")
    else:
        # Use the active document already open in Inventor
        doc = conn.app.ActiveDocument
        console.print(f"[green]Using active document:[/green] {doc.DisplayName}")

    return conn, doc


@app.command()
def extract(
    file: Path = typer.Argument(..., help="Path to .ipt, .iam, or .ipn file"),
    fmt: str = typer.Option("json", "--format", "-f", help="Output format: json, csv, or both"),
):
    """Extract parameters, BOM, and properties from an Inventor file."""
    ensure_dirs()
    conn, doc = get_connection(file)

    data = extract_all(doc)
    stem = Path(data["display_name"]).stem

    if fmt in ("json", "both"):
        dest = output_path(f"{stem}_extracted.json")
        write_json(data, dest)
        console.print(f"[blue]JSON saved:[/blue] {dest}")

    if fmt in ("csv", "both"):
        if data["parameters"]:
            params_csv = [
                {"name": k, **v} for k, v in data["parameters"].items()
            ]
            dest = output_path(f"{stem}_parameters.csv")
            write_csv(params_csv, dest)
            console.print(f"[blue]CSV saved:[/blue] {dest}")

        if data["bom"]:
            dest = output_path(f"{stem}_bom.csv")
            write_csv(data["bom"], dest)
            console.print(f"[blue]BOM CSV saved:[/blue] {dest}")

    # Pretty-print summary
    table = Table(title=f"Parameters — {data['display_name']}")
    table.add_column("Name", style="cyan")
    table.add_column("Value")
    table.add_column("Units")
    table.add_column("Comment", style="dim")
    for name, info in data["parameters"].items():
        table.add_row(name, info["value"], info["units"], info.get("comment", ""))
    console.print(table)


@app.command()
def modify(
    file: Path = typer.Argument(..., help="Path to .ipt or .iam file"),
    changes: str = typer.Option(..., help='JSON dict of changes, e.g. \'{"Width": "150 mm"}\''),
    output_name: Optional[str] = typer.Option(None, "--output", "-o", help="Output filename"),
):
    """Apply parameter changes to an Inventor file and save a modified copy."""
    ensure_dirs()
    conn, doc = get_connection(file)

    changes_dict: dict = json.loads(changes)
    console.print(f"Applying {len(changes_dict)} change(s)...")

    results = set_parameters_batch(doc, changes_dict, raise_on_error=False)
    for r in results:
        if r.get("error"):
            console.print(f"[red]ERROR[/red] {r['name']}: {r['error']}")
        else:
            console.print(f"[green]OK[/green] {r['name']}: {r['old_value']} → {r['new_value']}")

    stem = file.stem
    out_name = output_name or f"{stem}_modified{file.suffix}"
    dest = output_path(out_name)
    save_as(doc, dest)
    console.print(f"\n[green]Saved:[/green] {dest}")

    if typer.confirm("Open modified file in Inventor?"):
        open_in_inventor(conn, dest)
        console.print(f"[green]Opened in Inventor:[/green] {dest}")


@app.command()
def ask(
    instruction: str = typer.Argument(..., help="Natural language instruction for the agent"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="File to open (uses active doc if omitted)"),
    api_key: Optional[str] = typer.Option(None, envvar="ANTHROPIC_API_KEY"),
):
    """
    Send a natural-language instruction to the AI agent.

    Examples:
      python main.py ask "make the cylinders 20cm longer" --file input/assembly.iam
      python main.py ask "extract all parameters and save as JSON"
      python main.py ask "set Width to 150mm and Height to 75mm, then save"
    """
    ensure_dirs()
    conn, doc = get_connection(file)

    use_claude_code = os.environ.get("CLAUDE_CODE", "false").lower() == "true"

    if use_claude_code:
        llm = ClaudeCodeCLIClient()
        console.print("[dim]Using Claude Code CLI (CLAUDE_CODE=true)[/dim]")
    else:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            console.print(
                "[red]Error:[/red] No LLM backend configured.\n"
                "  Option A: Set CLAUDE_CODE=true in .env (uses Claude Code CLI, no API key needed)\n"
                "  Option B: Set ANTHROPIC_API_KEY=sk-ant-... in .env"
            )
            raise typer.Exit(1)
        llm = ClaudeLLMClient(api_key=key)
    executor = ToolExecutor(doc=doc, conn=conn)
    loop = AgentLoop(llm=llm, executor=executor)

    console.print(Panel(f"[bold]Instruction:[/bold] {instruction}", style="blue"))

    with console.status("Agent thinking..."):
        result = loop.run(instruction)

    console.print(Panel(result.final_text, title="Agent Response", style="green"))

    if result.tool_calls_made:
        table = Table(title="Tools Used")
        table.add_column("Tool", style="cyan")
        table.add_column("Input")
        for tc in result.tool_calls_made:
            table.add_row(tc.name, json.dumps(tc.input, default=str)[:80])
        console.print(table)

    console.print(f"[dim]Completed in {result.iterations} iteration(s)[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Launch the web UI on localhost."""
    import uvicorn
    import webbrowser
    import threading

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run("web:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
