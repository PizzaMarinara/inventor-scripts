# web.py
"""
FastAPI web server for the Inventor automation agent.

Launch:
  python web.py
  python main.py serve
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import get_llm_client
from agent.loop import AgentLoop, StreamEvent, ToolExecutor
from inventor_api import InventorConnection
from script_generator import SCRIPTS_DIR

BASE_DIR = Path(__file__).parent

logger = logging.getLogger(__name__)

app = FastAPI(title="Inventor Automation Web UI")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── Session model ─────────────────────────────────────────────────────────────

@dataclass
class Session:
    ws: WebSocket
    conn: InventorConnection | None = None
    doc: object | None = None
    active_file: str | None = None
    loop: Any | None = None          # AgentLoop reused across messages for memory
    is_running: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)


class SessionManager:
    def __init__(self) -> None:
        self.active_session: Session | None = None


session_manager = SessionManager()


# ── HTTP routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/files")
async def list_files():
    input_dir = Path.cwd() / "input"
    if not input_dir.exists():
        return {"files": []}
    # rglob("*") recurses into all subdirectories; use POSIX separators for the UI
    files = [
        f.relative_to(input_dir).as_posix()
        for f in sorted(input_dir.rglob("*"))
        if f.is_file()
    ]
    return {"files": files}


@app.get("/api/outputs")
async def list_outputs():
    output_dir = Path.cwd() / "output"
    if not output_dir.exists():
        return {"files": []}
    files = [f.name for f in output_dir.iterdir() if f.is_file()]
    return {"files": sorted(files)}


@app.get("/api/download/{filename:path}")
async def download_file(filename: str):
    from fastapi import HTTPException
    output_dir = (Path.cwd() / "output").resolve()
    resolved = (output_dir / filename).resolve()
    if not resolved.is_relative_to(output_dir):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(resolved), filename=resolved.name)


# ── Script REST endpoints ─────────────────────────────────────────────────────


@app.get("/api/scripts")
async def list_scripts():
    """List all generated scripts with metadata."""
    from script_generator import list_scripts as _list_scripts
    try:
        scripts = _list_scripts()
        return {"scripts": scripts}
    except Exception as e:
        return {"scripts": [], "error": str(e)}


@app.get("/api/scripts/{filename}")
async def get_script(filename: str):
    """Get the content of a specific script file."""
    from fastapi import HTTPException
    from script_generator import get_script_content
    try:
        content, script_type = get_script_content(filename)
        return {"content": content, "type": script_type, "filename": filename}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Script not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")


@app.get("/api/scripts/download/{filename:path}")
async def download_script(filename: str):
    """Download a script file."""
    from fastapi import HTTPException
    from script_generator import SCRIPTS_DIR
    resolved = (SCRIPTS_DIR / filename).resolve()
    if not str(resolved).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Script not found")
    return FileResponse(str(resolved), filename=resolved.name)


# ── WebSocket handler ─────────────────────────────────────────────────────────


async def _handle_run_script(session: Session, data: dict) -> None:
    """Execute a saved script and stream results back over WebSocket."""
    from script_generator import (
        get_script_content,
        run_python_script,
        run_ilogic_rule,
        SCRIPTS_DIR,
    )
    filename = data.get("filename", "")
    if not filename:
        await session.ws.send_json({"type": "error", "message": "No filename provided"})
        return

    try:
        content, script_type = get_script_content(filename)
    except FileNotFoundError:
        await session.ws.send_json({"type": "error", "message": f"Script not found: {filename}"})
        return
    except ValueError:
        await session.ws.send_json({"type": "error", "message": f"Invalid filename: {filename}"})
        return

    script_path = (SCRIPTS_DIR / filename).resolve()
    await session.ws.send_json({
        "type": "tool_start",
        "tool": "run_script",
        "input": {"filename": filename, "type": script_type},
    })

    loop_obj = asyncio.get_event_loop()

    if script_type == "python":
        def _run_python():
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except (ImportError, OSError):
                pass
            try:
                return run_python_script(script_path, file_path=session.active_file)
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        result = await loop_obj.run_in_executor(None, _run_python)
        # Stream stdout line by line
        for line in result.get("stdout", "").split("\n"):
            if line.strip():
                await session.ws.send_json({
                    "type": "text_delta",
                    "content": line,
                })
        if result.get("stderr"):
            for line in result["stderr"].split("\n"):
                if line.strip():
                    await session.ws.send_json({
                        "type": "text_delta",
                        "content": f"[stderr] {line}",
                    })
        await session.ws.send_json({
            "type": "tool_result",
            "tool": "run_script",
            "result": {
                "exit_code": result.get("exit_code", -1),
                "success": result.get("exit_code", -1) == 0,
                "timed_out": result.get("timed_out", False),
            },
        })

    elif script_type == "ilogic":
        def _run_ilogic():
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except (ImportError, OSError):
                pass
            try:
                conn = None
                if session.conn:
                    conn = session.conn
                return run_ilogic_rule(content, file_path=session.active_file, conn=conn)
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        result = await loop_obj.run_in_executor(None, _run_ilogic)
        if result.get("output"):
            await session.ws.send_json({
                "type": "text_delta",
                "content": result["output"],
            })
        if result.get("error"):
            await session.ws.send_json({
                "type": "text_delta",
                "content": f"[error] {result['error']}",
            })
        await session.ws.send_json({
            "type": "tool_result",
            "tool": "run_script",
            "result": {
                "success": result.get("success", False),
                "error": result.get("error", ""),
            },
        })


async def _handle_list_scripts_ws(session: Session) -> None:
    """Send the current list of scripts over WebSocket."""
    from script_generator import list_scripts as _list_scripts
    try:
        scripts = _list_scripts()
        await session.ws.send_json({
            "type": "script_list",
            "scripts": scripts,
        })
    except Exception as e:
        await session.ws.send_json({
            "type": "error",
            "message": f"Failed to list scripts: {e}",
        })

async def _stream_events(
    session: Session,
    file_name: str,
    llm: Any,
    instruction: str,
) -> None:
    """
    Run the agent in a thread-pool executor and stream events back over WebSocket.

    ALL COM operations (InventorConnection, open_document, ActiveDocument, and every
    call made inside AgentLoop/ToolExecutor) happen inside _blocking() so they share
    the same OS thread.  Inventor is an STA COM server: objects created on one thread
    cannot be safely used from another thread.  pythoncom.CoInitialize() initialises
    COM for the worker thread; CoUninitialize() cleans up on exit.
    """
    cwd = Path.cwd()  # capture on main thread before spawning worker
    loop_obj = asyncio.get_event_loop()
    logger.info("Starting agent stream for file=%s", file_name or "(active document)")

    def _blocking() -> list[StreamEvent]:
        # ── COM thread initialisation ────────────────────────────────────────
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_ready = True
        except (ImportError, OSError):
            _com_ready = False  # non-Windows / tests without pywin32

        try:
            # ── Inventor connection (same thread as all subsequent COM calls) ─
            conn = InventorConnection()
            conn.connect(launch_if_not_running=True)

            if file_name:
                doc = conn.open_document((cwd / "input" / file_name).resolve())
                if doc is None:
                    return [StreamEvent(
                        type="error",
                        content=(
                            f"Inventor did not return a document for '{file_name}'. "
                            "Verify the file exists in the input/ folder and is a valid "
                            ".ipt/.iam/.ipn file."
                        ),
                    )]
            else:
                doc = conn.app.ActiveDocument
                if doc is None:
                    return [StreamEvent(
                        type="error",
                        content=(
                            "No document open in Inventor. "
                            "Open a file in Inventor or select one from the list."
                        ),
                    )]

            # ── AgentLoop: reuse for memory, refresh executor COM refs each turn ─
            normalised = file_name or ""
            file_changed = normalised != (session.active_file or "") or session.loop is None
            executor = ToolExecutor(doc=doc, conn=conn)
            if file_changed:
                session.loop = AgentLoop(llm=llm, executor=executor)
                session.active_file = normalised
            else:
                # Same file: keep history but hand the loop fresh COM object refs
                # so it uses the connection initialised on this thread.
                session.loop._executor = executor

            return list(session.loop.run_streaming(instruction))

        finally:
            if _com_ready:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    try:
        events = await loop_obj.run_in_executor(None, _blocking)
        logger.debug("Received %d events from agent", len(events))
        script_was_generated = False
        for event in events:
            if session.cancel_event.is_set():
                break
            payload: dict = {"type": event.type}
            if event.type == "text_delta":
                payload["content"] = event.content
            elif event.type == "tool_start":
                payload["tool"] = event.tool_name
                payload["input"] = event.tool_input
                if event.tool_name == "generate_script":
                    script_was_generated = True
            elif event.type == "tool_result":
                payload["tool"] = event.tool_name
                payload["result"] = str(event.result)
            elif event.type == "done":
                payload["content"] = event.content
                payload["iterations"] = event.iterations
            elif event.type == "error":
                payload["message"] = event.content
            await session.ws.send_json(payload)

        # If a script was generated, send updated script list to refresh sidebar
        if script_was_generated:
            logger.info("Script generated, refreshing script list")
            from script_generator import list_scripts as _list_scripts
            try:
                scripts = _list_scripts()
                await session.ws.send_json({
                    "type": "script_list",
                    "scripts": scripts,
                })
            except Exception:
                pass
    except Exception as exc:
        logger.error("Agent stream failed: %s", exc)
        await session.ws.send_json({"type": "error", "message": str(exc)})
    finally:
        session.is_running = False


async def _handle_chat(session: Session, data: dict) -> None:
    if session.is_running:
        await session.ws.send_json({"type": "error", "message": "Agent is already running."})
        return

    file_name: str = data.get("file") or ""
    instruction: str = data.get("message", "")
    provider: str | None = data.get("provider")
    model: str | None = data.get("model")
    api_key: str | None = data.get("api_key")

    session.is_running = True
    session.cancel_event.clear()

    try:
        llm: Any = get_llm_client(provider=provider, api_key=api_key, model=model)
    except (ValueError, EnvironmentError) as e:
        await session.ws.send_json({"type": "error", "message": str(e)})
        session.is_running = False
        return

    await _stream_events(session, file_name, llm, instruction)


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    if session_manager.active_session is not None:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Another session is active."})
        await ws.close()
        return

    session = Session(ws=ws)
    session_manager.active_session = session
    await ws.accept()

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "chat":
                await _handle_chat(session, data)
            elif data.get("type") == "cancel":
                session.cancel_event.set()
            elif data.get("type") == "run_script":
                await _handle_run_script(session, data)
            elif data.get("type") == "list_scripts":
                await _handle_list_scripts_ws(session)
    except WebSocketDisconnect:
        pass
    finally:
        if session.conn:
            try:
                session.conn.quit()
            except Exception:
                pass
        session_manager.active_session = None


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web:app", host="127.0.0.1", port=8000, reload=False)
