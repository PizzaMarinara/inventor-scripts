# tests/test_web.py
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient


# ── HTTP route tests ──────────────────────────────────────────────────────────

def test_get_root_returns_html():
    from web import app
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_api_files_lists_input_dir(tmp_path, monkeypatch):
    from web import app
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "assembly.iam").touch()
    (input_dir / "part.ipt").touch()
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/api/files")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["files"]) == {"assembly.iam", "part.ipt"}


def test_api_outputs_lists_output_dir(tmp_path, monkeypatch):
    from web import app
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "result.json").touch()
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/api/outputs")
    assert resp.status_code == 200
    assert "result.json" in resp.json()["files"]


def test_api_download_rejects_path_traversal(tmp_path, monkeypatch):
    from web import app
    (tmp_path / "output").mkdir()
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    # Use percent-encoded slash so the path traversal reaches the endpoint
    resp = client.get("/api/download/..%2Fweb.py")
    assert resp.status_code == 400


def test_api_download_returns_file(tmp_path, monkeypatch):
    from web import app
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    target = output_dir / "data.json"
    target.write_text('{"ok": true}')
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/api/download/data.json")
    assert resp.status_code == 200
    assert resp.content == b'{"ok": true}'
    assert "application/json" in resp.headers["content-type"]


def test_api_download_missing_file_returns_404(tmp_path, monkeypatch):
    from web import app
    (tmp_path / "output").mkdir()
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/api/download/ghost.json")
    assert resp.status_code == 404


# ── WebSocket tests ───────────────────────────────────────────────────────────

def test_websocket_chat_sends_events_in_order():
    """
    A single chat message should produce tool_start → tool_result → done
    messages over the WebSocket.
    """
    from web import app, session_manager
    from agent.loop import StreamEvent

    session_manager.active_session = None  # ensure clean state

    mock_events = [
        StreamEvent(type="tool_start", tool_name="describe_model", tool_input={}),
        StreamEvent(type="tool_result", tool_name="describe_model", result="summary"),
        StreamEvent(type="done", content="Described.", iterations=1),
    ]

    mock_llm = MagicMock()

    with patch("web.get_llm_client", return_value=mock_llm) as mock_get_client, \
         patch("web.AgentLoop") as MockLoop, \
         patch("web.InventorConnection"), \
         patch("web.ToolExecutor"):
        instance = MockLoop.return_value
        instance.run_streaming.return_value = iter(mock_events)

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "chat", "message": "describe model", "file": "part.ipt"})
            msgs = []
            for _ in range(3):
                msgs.append(ws.receive_json())

    mock_get_client.assert_called_once_with(provider=None, api_key=None, model=None)
    types = [m["type"] for m in msgs]
    assert types == ["tool_start", "tool_result", "done"]


def test_websocket_chat_passes_provider_from_message():
    """When provider is specified in the chat message, it should be passed to get_llm_client."""
    from web import app, session_manager
    from agent.loop import StreamEvent

    session_manager.active_session = None

    mock_events = [StreamEvent(type="done", content="OK.", iterations=1)]
    mock_llm = MagicMock()

    with patch("web.get_llm_client", return_value=mock_llm) as mock_get_client, \
         patch("web.AgentLoop") as MockLoop, \
         patch("web.InventorConnection"), \
         patch("web.ToolExecutor"):
        instance = MockLoop.return_value
        instance.run_streaming.return_value = iter(mock_events)

        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({
                "type": "chat",
                "message": "test",
                "file": "",
                "provider": "openrouter",
                "api_key": "sk-or-test",
                "model": "anthropic/claude-3.5-sonnet",
            })
            ws.receive_json()  # consume the done event

    mock_get_client.assert_called_once_with(
        provider="openrouter",
        api_key="sk-or-test",
        model="anthropic/claude-3.5-sonnet",
    )


def test_websocket_chat_returns_error_on_config_failure():
    """When get_llm_client raises an error, it should be sent back to the client."""
    from web import app, session_manager

    session_manager.active_session = None

    with patch("web.get_llm_client", side_effect=ValueError("Missing API key")):
        client = TestClient(app)
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"type": "chat", "message": "test", "file": ""})
            msg = ws.receive_json()

    assert msg["type"] == "error"
    assert "Missing API key" in msg["message"]


def test_websocket_rejects_second_connection_when_session_active():
    from web import app, session_manager, Session

    # Simulate an already-active session
    fake_session = MagicMock(spec=Session)
    session_manager.active_session = fake_session

    client = TestClient(app)
    with client.websocket_connect("/ws/chat") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "active" in msg["message"].lower()

    session_manager.active_session = None  # cleanup
