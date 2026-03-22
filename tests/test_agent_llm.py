# tests/test_agent_llm.py
from unittest.mock import MagicMock, patch
import pytest
from agent.llm import ClaudeLLMClient, ClaudeCodeCLIClient, LLMResponse, ToolCall


def make_claude_response(tool_name: str, tool_input: dict):
    """Build a minimal fake Claude API response."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = "toolu_01"
    block.name = tool_name
    block.input = tool_input
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def make_claude_text_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def test_claude_client_calls_tool():
    fake_response = make_claude_response("describe_model", {})
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_response

    with patch("agent.llm.anthropic.Anthropic", return_value=mock_client):
        client = ClaudeLLMClient(api_key="test-key")
        result = client.chat(messages=[{"role": "user", "content": "describe this"}], tools=[])

    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "describe_model"
    assert result.assistant_content == fake_response.content


def test_claude_client_returns_text():
    fake_response = make_claude_text_response("The model has 3 parameters.")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_response

    with patch("agent.llm.anthropic.Anthropic", return_value=mock_client):
        client = ClaudeLLMClient(api_key="test-key")
        result = client.chat(messages=[{"role": "user", "content": "describe"}], tools=[])

    assert result.stop_reason == "end_turn"
    assert result.text == "The model has 3 parameters."
    assert result.tool_calls == []


def test_claude_code_cli_parses_tool_use():
    """ClaudeCodeCLIClient correctly parses a tool_use JSON response."""
    import json
    fake_output = json.dumps({
        "action": "tool_use",
        "tool": "describe_model",
        "input": {},
        "id": "t1"
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
        client = ClaudeCodeCLIClient()
        result = client.chat(messages=[{"role": "user", "content": "describe"}], tools=[])
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "describe_model"


def test_claude_code_cli_parses_text_response():
    """ClaudeCodeCLIClient correctly parses a text response."""
    import json
    fake_output = json.dumps({"action": "text", "content": "Done."})
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
        client = ClaudeCodeCLIClient()
        result = client.chat(messages=[{"role": "user", "content": "hello"}], tools=[])
    assert result.stop_reason == "end_turn"
    assert result.text == "Done."


def test_claude_code_cli_raises_on_nonzero_exit():
    """Non-zero exit code surfaces stderr as RuntimeError with the raw CLI message."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Invalid API key - Fix external API key",
            returncode=1,
        )
        client = ClaudeCodeCLIClient()
        with pytest.raises(RuntimeError, match="Invalid API key"):
            client.chat(messages=[{"role": "user", "content": "hi"}], tools=[])


def test_claude_code_cli_hint_on_auth_error():
    """Auth-related stderr includes a re-authentication hint."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="unauthorized: api key invalid",
            returncode=1,
        )
        client = ClaudeCodeCLIClient()
        with pytest.raises(RuntimeError, match="ri-autenticarti"):
            client.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
