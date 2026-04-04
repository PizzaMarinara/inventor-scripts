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
from config import get_llm_client
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
        if doc is None:
            raise typer.BadParameter(f"Inventor returned None for '{file_path}'. "
                                     "Check that the file exists and is a valid .ipt/.iam/.ipn.")
        console.print(f"[green]Opened:[/green] {file_path}")
    else:
        # Use the active document already open in Inventor
        doc = conn.app.ActiveDocument
        if doc is None:
            raise typer.BadParameter(
                "No document open in Inventor.\n"
                "  Open a file in Inventor or pass the path as an argument:\n"
                "  python main.py <command> input/model.iam"
            )
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
    provider: Optional[str] = typer.Option(None, "--provider", "-p", envvar="LLM_PROVIDER", help="LLM provider (anthropic, claude_code, openrouter, openai, groq, together, ollama, custom)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", envvar="LLM_MODEL", help="Override default model for the selected provider"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="LLM_API_KEY", help="API key for the selected provider"),
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

    llm = get_llm_client(provider=provider, api_key=api_key, model=model)
    console.print(f"[dim]Using LLM provider: {llm.__class__.__name__}[/dim]")
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
    import copy
    import uvicorn
    import webbrowser
    import threading
    from uvicorn.config import LOGGING_CONFIG

    # Extend uvicorn's logging config so the root logger (and therefore all
    # app loggers — agent.llm, agent.loop, config, web) emit INFO messages
    # using the same "default" handler/formatter as uvicorn itself.
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["root"] = {"level": "INFO", "handlers": ["default"]}

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run("web:app", host=host, port=port, reload=False, log_config=log_config)


if __name__ == "__main__":
    app()
