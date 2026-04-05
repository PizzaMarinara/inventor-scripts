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


# ── Script REST endpoint tests ────────────────────────────────────────────────


def test_api_scripts_lists_scripts(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "20260402_120000_test.py").write_text("# Description : Test script\nprint('hi')")
    (scripts_dir / "rule.ilogic").write_text("' Description : iLogic rule\nParameter('X') = 10")
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scripts"]) == 2


def test_api_scripts_returns_empty_when_no_scripts(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts")
        assert resp.status_code == 200
        assert resp.json()["scripts"] == []


def test_api_scripts_get_content(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "test.py").write_text("print('hello')")
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts/test.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "print('hello')"
        assert data["type"] == "python"


def test_api_scripts_get_ilogic_content(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "rule.ilogic").write_text("Parameter('X') = 10")
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts/rule.ilogic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "ilogic"


def test_api_scripts_get_missing_returns_404(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts/nonexistent.py")
        assert resp.status_code == 404


def test_api_scripts_download_returns_file(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "test.py").write_text("print('hi')")
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts/download/test.py")
        assert resp.status_code == 200
        assert resp.content == b"print('hi')"


def test_api_scripts_download_rejects_path_traversal(tmp_path, monkeypatch):
    from web import app
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        client = TestClient(app)
        resp = client.get("/api/scripts/download/..%2Fweb.py")
        assert resp.status_code == 400


# ── WebSocket script tests ────────────────────────────────────────────────────


def test_websocket_run_python_script(tmp_path, monkeypatch):
    """Running a Python script should produce tool_start → text_delta → tool_result."""
    from web import app, session_manager, Session

    session_manager.active_session = None
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "test.py").write_text("print('script output')")
    monkeypatch.chdir(tmp_path)

    mock_session = MagicMock(spec=Session)
    mock_session.ws = AsyncMock()
    mock_session.active_file = None
    mock_session.conn = None
    mock_session.is_running = False  # must be falsy to pass the is_running guard
    session_manager.active_session = mock_session

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        from web import _handle_run_script
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            _handle_run_script(mock_session, {"filename": "test.py"})
        )

    # Check that events were sent in the right order
    calls = mock_session.ws.send_json.call_args_list
    types = [c[0][0]["type"] for c in calls]
    assert "tool_start" in types
    assert "text_delta" in types
    assert "tool_result" in types
    # tool_start must come before tool_result
    assert types.index("tool_start") < types.index("tool_result")


def test_websocket_run_script_missing_file(tmp_path, monkeypatch):
    """Running a nonexistent script should return an error."""
    from web import app, session_manager, Session

    session_manager.active_session = None
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    mock_session = MagicMock(spec=Session)
    mock_session.ws = AsyncMock()
    session_manager.active_session = mock_session

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        from web import _handle_run_script
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            _handle_run_script(mock_session, {"filename": "nonexistent.py"})
        )

    calls = mock_session.ws.send_json.call_args_list
    assert len(calls) == 1
    assert calls[0][0][0]["type"] == "error"


def test_websocket_list_scripts(tmp_path, monkeypatch):
    """list_scripts WS message should return the script list."""
    from web import app, session_manager, Session

    session_manager.active_session = None
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "test.py").write_text("# Description : Test\nprint('hi')")
    monkeypatch.chdir(tmp_path)

    mock_session = MagicMock(spec=Session)
    mock_session.ws = AsyncMock()
    session_manager.active_session = mock_session

    with patch("script_generator.SCRIPTS_DIR", scripts_dir):
        from web import _handle_list_scripts_ws
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            _handle_list_scripts_ws(mock_session)
        )

    calls = mock_session.ws.send_json.call_args_list
    assert len(calls) == 1
    msg = calls[0][0][0]
    assert msg["type"] == "script_list"
    assert len(msg["scripts"]) == 1


# ── Bug C-2: _handle_run_script missing is_running guard ──────────────────────

def test_run_script_rejected_when_agent_already_running():
    """Bug C-2: _handle_run_script must reject with error when is_running=True."""
    import asyncio
    from web import Session, _handle_run_script

    mock_session = MagicMock(spec=Session)
    mock_session.ws = AsyncMock()
    mock_session.is_running = True  # agent is already in flight

    asyncio.get_event_loop().run_until_complete(
        _handle_run_script(mock_session, {"filename": "test.py"})
    )

    calls = mock_session.ws.send_json.call_args_list
    assert len(calls) == 1, "Should send exactly one error message"
    msg = calls[0][0][0]
    assert msg["type"] == "error"
    assert "running" in msg["message"].lower()


# ── /api/active-document ──────────────────────────────────────────────────────

def test_api_active_document_returns_null_with_no_session():
    from web import app, session_manager
    session_manager.active_session = None

    client = TestClient(app)
    resp = client.get("/api/active-document")
    assert resp.status_code == 200
    assert resp.json() == {"file": None}


def test_api_active_document_returns_active_file():
    from web import app, session_manager, Session

    mock_session = MagicMock(spec=Session)
    mock_session.active_file = "assembly.iam"
    session_manager.active_session = mock_session

    client = TestClient(app)
    resp = client.get("/api/active-document")
    assert resp.status_code == 200
    assert resp.json() == {"file": "assembly.iam"}

    session_manager.active_session = None  # cleanup


def test_api_active_document_returns_null_when_no_file_loaded():
    from web import app, session_manager, Session

    mock_session = MagicMock(spec=Session)
    mock_session.active_file = None
    session_manager.active_session = mock_session

    client = TestClient(app)
    resp = client.get("/api/active-document")
    assert resp.status_code == 200
    assert resp.json() == {"file": None}

    session_manager.active_session = None  # cleanup
