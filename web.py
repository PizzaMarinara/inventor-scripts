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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

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
    messages: list[dict] = field(default_factory=list)
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
    files = [f.name for f in input_dir.iterdir() if f.is_file()]
    return {"files": sorted(files)}


@app.get("/api/outputs")
async def list_outputs():
    output_dir = Path.cwd() / "output"
    if not output_dir.exists():
        return {"files": []}
    files = [f.name for f in output_dir.iterdir() if f.is_file()]
    return {"files": sorted(files)}


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    target = Path.cwd() / "output" / filename
    if not target.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(target), filename=filename)


# ── WebSocket handler ─────────────────────────────────────────────────────────

async def _stream_events(session: Session, loop: AgentLoop, instruction: str) -> None:
    """Run run_streaming() in a thread executor and forward events to the WebSocket."""
    loop_obj = asyncio.get_event_loop()

    def _blocking():
        return list(loop.run_streaming(instruction))

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

    file_name: str | None = data.get("file")
    instruction: str = data.get("message", "")

    session.is_running = True
    session.cancel_event.clear()

    try:
        # Select LLM backend — mirrors the same logic as main.py `ask`
        use_claude_code = os.environ.get("CLAUDE_CODE", "false").lower() == "true"
        if use_claude_code:
            llm = ClaudeCodeCLIClient()
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

        conn = InventorConnection()
        conn.connect(launch_if_not_running=True)
        session.conn = conn

        if file_name:
            doc = conn.open_document((Path.cwd() / "input" / file_name).resolve())
            if doc is None:
                await session.ws.send_json({
                    "type": "error",
                    "message": f"Inventor non ha restituito un documento per '{file_name}'. "
                               "Verifica che il file esista nella cartella input/ e sia un file .ipt/.iam/.ipn valido.",
                })
                session.is_running = False
                return
            session.doc = doc
            session.active_file = file_name
        else:
            doc = conn.app.ActiveDocument
            if doc is None:
                await session.ws.send_json({
                    "type": "error",
                    "message": "Nessun documento aperto in Inventor. "
                               "Apri un file in Inventor oppure selezionane uno dall'elenco.",
                })
                session.is_running = False
                return
            session.doc = doc

        executor = ToolExecutor(doc=doc, conn=conn)
        loop = AgentLoop(llm=llm, executor=executor)

        await _stream_events(session, loop, instruction)

    except Exception as exc:
        await session.ws.send_json({"type": "error", "message": str(exc)})
        session.is_running = False


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
