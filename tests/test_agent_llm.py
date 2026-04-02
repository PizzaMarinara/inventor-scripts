# tests/test_agent_llm.py
from unittest.mock import MagicMock, patch
import pytest
from agent.llm import ClaudeLLMClient, ClaudeCodeCLIClient, OpenAICompatibleClient, PROVIDER_PRESETS, LLMResponse, ToolCall


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


def test_claude_code_cli_includes_tool_results_in_prompt():
    """Tool result content must appear verbatim in the prompt — not as a placeholder."""
    import json
    fake_text = json.dumps({"action": "text", "content": "Done."})
    captured = {}

    def fake_run(cmd, *, input, **kwargs):
        captured["prompt"] = input
        return MagicMock(stdout=fake_text, stderr="", returncode=0)

    messages = [
        {"role": "user", "content": "describe this"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "describe_model", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                       "content": "=== Inventor Document: assembly.iam ===\nParameters: Width=100"}]},
    ]

    with patch("subprocess.run", side_effect=fake_run):
        client = ClaudeCodeCLIClient()
        client.chat(messages=messages, tools=[])

    prompt = captured["prompt"]
    assert "assembly.iam" in prompt, "Tool result content must be in prompt"
    assert "Width=100" in prompt, "Tool result details must be in prompt"
    assert "[Previous tool results received]" not in prompt, "Old placeholder must not appear"


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


def test_claude_code_cli_error_shows_raw_stderr():
    """RuntimeError on non-zero exit includes the raw stderr content."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="unauthorized: api key invalid",
            returncode=1,
        )
        client = ClaudeCodeCLIClient()
        with pytest.raises(RuntimeError, match="unauthorized: api key invalid"):
            client.chat(messages=[{"role": "user", "content": "hi"}], tools=[])


# ── OpenAICompatibleClient tests ──────────────────────────────────────────────


def make_openai_response(tool_name: str, tool_input: dict, tool_id: str = "call_abc123"):
    """Build a minimal fake OpenAI API response with a tool call."""
    import json
    tool_call = MagicMock()
    tool_call.id = tool_id
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(tool_input)

    message = MagicMock()
    message.content = None
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def make_openai_text_response(text: str):
    """Build a minimal fake OpenAI API text response."""
    message = MagicMock()
    message.content = text
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def test_openai_client_calls_tool():
    fake_response = make_openai_response("describe_model", {})
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_response

    with patch("agent.llm.openai.OpenAI", return_value=mock_client):
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="gpt-4o",
        )
        result = client.chat(
            messages=[{"role": "user", "content": "describe this"}],
            tools=[],
        )

    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "describe_model"
    assert result.assistant_content[0]["type"] == "tool_use"


def test_openai_client_returns_text():
    fake_response = make_openai_text_response("The model has 3 parameters.")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_response

    with patch("agent.llm.openai.OpenAI", return_value=mock_client):
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="gpt-4o",
        )
        result = client.chat(
            messages=[{"role": "user", "content": "describe"}],
            tools=[],
        )

    assert result.stop_reason == "end_turn"
    assert result.text == "The model has 3 parameters."
    assert result.tool_calls == []


def test_openai_client_prepends_system_prompt():
    """System prompt should be prepended as a system message."""
    fake_response = make_openai_text_response("OK")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_response

    with patch("agent.llm.openai.OpenAI", return_value=mock_client):
        client = OpenAICompatibleClient(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="gpt-4o",
        )
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            system="You are a helpful assistant.",
        )

    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a helpful assistant."
    assert messages[1]["role"] == "user"


def test_provider_presets_contains_openrouter():
    assert "openrouter" in PROVIDER_PRESETS
    base_url, model = PROVIDER_PRESETS["openrouter"]
    assert "openrouter.ai" in base_url


def test_provider_presets_contains_openai():
    assert "openai" in PROVIDER_PRESETS
    base_url, model = PROVIDER_PRESETS["openai"]
    assert "api.openai.com" in base_url
