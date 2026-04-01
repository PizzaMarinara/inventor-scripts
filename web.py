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
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.llm import ClaudeLLMClient, ClaudeCodeCLIClient
from agent.loop import AgentLoop, StreamEvent, ToolExecutor
from inventor_api import InventorConnection

BASE_DIR = Path(__file__).parent

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


# ── WebSocket handler ─────────────────────────────────────────────────────────

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
    loop_obj = asyncio.get_event_loop()

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
                doc = conn.open_document((Path.cwd() / "input" / file_name).resolve())
                if doc is None:
                    return [StreamEvent(
                        type="error",
                        content=(
                            f"Inventor non ha restituito un documento per '{file_name}'. "
                            "Verifica che il file esista nella cartella input/ e sia un "
                            "file .ipt/.iam/.ipn valido."
                        ),
                    )]
            else:
                doc = conn.app.ActiveDocument
                if doc is None:
                    return [StreamEvent(
                        type="error",
                        content=(
                            "Nessun documento aperto in Inventor. "
                            "Apri un file in Inventor oppure selezionane uno dall'elenco."
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
        for event in events:
            if session.cancel_event.is_set():
                break
            payload: dict = {"type": event.type}
            if event.type == "text_delta":
                payload["content"] = event.content
            elif event.type == "tool_start":
                payload["tool"] = event.tool_name
                payload["input"] = event.tool_input
            elif event.type == "tool_result":
                payload["tool"] = event.tool_name
                payload["result"] = str(event.result)
            elif event.type == "done":
                payload["content"] = event.content
                payload["iterations"] = event.iterations
            elif event.type == "error":
                payload["message"] = event.content
            await session.ws.send_json(payload)
    except Exception as exc:
        await session.ws.send_json({"type": "error", "message": str(exc)})
    finally:
        session.is_running = False


async def _handle_chat(session: Session, data: dict) -> None:
    if session.is_running:
        await session.ws.send_json({"type": "error", "message": "Agent is already running."})
        return

    file_name: str = data.get("file") or ""
    instruction: str = data.get("message", "")

    session.is_running = True
    session.cancel_event.clear()

    # Select LLM backend — no COM involved here
    use_claude_code = os.environ.get("CLAUDE_CODE", "false").lower() == "true"
    if use_claude_code:
        llm: Any = ClaudeCodeCLIClient()
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            await session.ws.send_json({
                "type": "error",
                "message": (
                    "Nessun backend LLM configurato. "
                    "Imposta CLAUDE_CODE=true oppure ANTHROPIC_API_KEY nel file .env."
                ),
            })
            session.is_running = False
            return
        llm = ClaudeLLMClient(api_key=api_key)

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
