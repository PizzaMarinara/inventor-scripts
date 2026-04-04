"""
Provider-agnostic LLM client.

To add a new provider:
  1. Implement a class with a .chat() method matching the LLMClient protocol.
  2. Return LLMResponse from every call — populate assistant_content so the
     agent loop can reconstruct multi-turn history without touching .raw.
  3. Pass it to AgentLoop (agent/loop.py).

Current providers: Claude (API), Claude Code CLI, OpenAI-compatible (OpenRouter, OpenAI, Groq, etc.)
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
import anthropic
import openai

# Provider presets: name → (base_url, default_model)
PROVIDER_PRESETS = {
    "openrouter": ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4-20250514"),
    "openai":     ("https://api.openai.com/v1",     "gpt-4o"),
    "groq":       ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "together":   ("https://api.together.xyz/v1",    "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "ollama":     ("http://localhost:11434/v1",      "llama3"),
}

logger = logging.getLogger(__name__)

# Allowlist of environment variables safe to pass to subprocess calls.
# Using an allowlist (rather than a denylist) prevents leaking secrets like
# API keys, database passwords, or cloud credentials to child processes.
SAFE_ENV_VARS = frozenset({
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_CTYPE", "LC_ALL",
    "TMPDIR", "TEMP", "TERM", "USERPROFILE", "PATHEXT", "SYSTEMROOT",
    "COMSPEC", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "NODE_PATH",
})


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    stop_reason: str                  # "tool_use" | "end_turn"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Provider-agnostic assistant message content for multi-turn history.
    # Each provider client serialises its response into this format so that
    # AgentLoop never needs to touch `.raw` for message history construction.
    # Format: list of content block dicts that the provider's API accepts as
    # the "assistant" role content (e.g. Anthropic content blocks).
    assistant_content: list = field(default_factory=list)
    raw: Any = None                   # original provider response, for debugging only


@runtime_checkable
class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
    ) -> LLMResponse: ...


class ClaudeLLMClient:
    """Anthropic Claude client (default provider)."""

    DEFAULT_MODEL = "claude-opus-4-5"

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: int | None = None) -> None:
        import os
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL
        self._max_tokens = max_tokens if max_tokens is not None else int(os.getenv("MAX_TOKENS", "4096"))

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
    ) -> LLMResponse:
        """
        Send messages to Claude and return a normalised LLMResponse.

        tools: list of provider-agnostic tool dicts (agent/tools.py format).
               Translated to Anthropic format here.
        """
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in tools
        ]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if system:
            kwargs["system"] = system

        logger.info(
            "Anthropic request: model=%s messages=%d tools=%d max_tokens=%d",
            self._model, len(messages), len(tools), self._max_tokens,
        )
        raw = self._client.messages.create(**kwargs)
        logger.info(
            "Anthropic response: stop_reason=%s input_tokens=%d output_tokens=%d",
            raw.stop_reason,
            raw.usage.input_tokens,
            raw.usage.output_tokens,
        )

        tool_calls = []
        text = ""
        # assistant_content preserves the original content block list so that
        # multi-turn message history can be reconstructed without touching .raw.
        # This is what gets appended as {"role": "assistant", "content": ...}
        # in the agent loop.
        assistant_content = raw.content  # Anthropic SDK returns a list of blocks

        for block in raw.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
            elif block.type == "text":
                text += block.text

        return LLMResponse(
            stop_reason=raw.stop_reason,
            text=text,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            raw=raw,
        )


class ClaudeCodeCLIClient:
    """
    LLM client that delegates to the Claude Code CLI (`claude -p`).

    Use this when Claude Code is installed on the machine and you don't want
    to manage a separate ANTHROPIC_API_KEY. Authentication is handled by the
    Claude Code installation itself.

    Limitations vs ClaudeLLMClient:
    - Tool calling is implemented via prompt engineering (not native API tool-use).
      The system prompt embeds the tool schemas as JSON and asks Claude to respond
      with a structured JSON action. This is less reliable than native tool-use
      for complex multi-step operations.
    - No streaming support (claude -p waits for the full response).
    - Requires `claude` CLI to be on PATH.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model  # if None, claude CLI uses its default

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
    ) -> LLMResponse:
        """
        Run a single turn via `claude -p`.

        Builds a self-contained prompt that includes the system instructions,
        tool schemas, and conversation history, then parses Claude's JSON response.
        """
        import subprocess
        import json as _json

        tool_schema_str = _json.dumps(tools, indent=2) if tools else "[]"

        # Serialize the full conversation so Claude has complete context: user turns,
        # assistant tool calls, and — critically — the actual tool result content.
        def _serialize_messages(msgs: list[dict]) -> str:
            parts: list[str] = []
            for msg in msgs:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "user":
                    if isinstance(content, str):
                        parts.append(f"USER: {content}")
                    elif isinstance(content, list):
                        # tool_result blocks — include the actual content
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                parts.append(f"TOOL RESULT:\n{block.get('content', '')}")

                elif role == "assistant":
                    if isinstance(content, str) and content:
                        parts.append(f"ASSISTANT: {content}")
                    elif isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text" and block.get("text"):
                                parts.append(f"ASSISTANT: {block['text']}")
                            elif btype == "tool_use":
                                # Native API tool call block — represent as text
                                parts.append(
                                    f"ASSISTANT called tool '{block.get('name')}' "
                                    f"with: {_json.dumps(block.get('input', {}))}"
                                )
            return "\n\n".join(parts)

        conversation = _serialize_messages(messages)

        full_prompt = f"""{system}

AVAILABLE TOOLS (JSON schemas):
{tool_schema_str}

To call a tool, respond with ONLY a JSON object in this exact format (no other text):
{{"action": "tool_use", "tool": "<tool_name>", "input": {{...}}, "id": "t1"}}

To give a final text response (no more tools needed), respond with ONLY:
{{"action": "text", "content": "<your response>"}}

CONVERSATION SO FAR:
{conversation}

Your response (JSON only):"""

        # On Windows, npm installs a `claude.cmd` wrapper; shutil.which resolves
        # the correct executable name via PATHEXT without needing shell=True.
        import shutil
        executable = shutil.which("claude") or "claude"

        # Pass the prompt via stdin to avoid Windows command-line length limits
        # and shell-escaping issues with JSON content embedded in the prompt.
        cmd = [executable, "-p", "--output-format", "text"]
        if self._model:
            cmd.extend(["--model", self._model])

        import os as _os

        # Use an allowlist to pass only safe environment variables to the subprocess.
        # This prevents leaking sensitive variables (API keys, database passwords, cloud
        # credentials) from the parent process into the claude CLI subprocess.
        subprocess_env = {k: v for k, v in _os.environ.items() if k in SAFE_ENV_VARS}

        logger.info(
            "Claude Code CLI request: messages=%d tools=%d",
            len(messages), len(tools),
        )
        _TIMEOUT = 300
        _MAX_RETRIES = 2
        proc = None
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    input=full_prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=_TIMEOUT,
                    env=subprocess_env,
                )
                break
            except FileNotFoundError:
                raise RuntimeError(
                    "Claude Code CLI not found. "
                    "Install with: npm install -g @anthropic-ai/claude-code\n"
                    "After installation, restart your terminal and try again.\n"
                    "Alternatively, use ClaudeLLMClient with ANTHROPIC_API_KEY."
                )
            except subprocess.TimeoutExpired:
                if _attempt < _MAX_RETRIES:
                    logger.warning(
                        "Claude Code CLI timeout (attempt %d/%d), retrying...",
                        _attempt + 1, _MAX_RETRIES + 1,
                    )
                else:
                    raise RuntimeError(
                        f"Claude Code CLI timed out after {_MAX_RETRIES + 1} attempts "
                        f"({_TIMEOUT}s each)."
                    )

        logger.info("Claude Code CLI response: exit_code=%d", proc.returncode)

        # Surface stderr / non-zero exit as a clear RuntimeError so callers
        # (web UI, CLI) can display the real message from the Claude Code CLI.
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            raise RuntimeError(
                f"Claude Code CLI failed (exit {proc.returncode}).\n"
                f"  stderr: {stderr or '(empty)'}\n"
                f"  stdout: {stdout or '(empty)'}"
            )

        output = proc.stdout.strip()

        # Parse JSON response from Claude.
        # Claude sometimes outputs reasoning text alongside (or before) the JSON action.
        # Scan ALL JSON objects in the output and prioritise any tool_use action over
        # a text action, so that a tool call is never silently dropped.
        parsed = None
        try:
            clean = output.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            parsed = _json.loads(clean)
        except _json.JSONDecodeError:
            parsed = None

        # If full parse failed OR yielded only a text action, scan for a tool_use block.
        if parsed is None or parsed.get("action") != "tool_use":
            tool_use_candidate = None
            text_candidate = parsed  # keep the already-found text action if any
            pos = 0
            while pos < len(output):
                brace_start = output.find('{', pos)
                if brace_start == -1:
                    break
                try:
                    candidate, end_pos = _json.JSONDecoder().raw_decode(output, brace_start)
                    if isinstance(candidate, dict):
                        if candidate.get("action") == "tool_use":
                            tool_use_candidate = candidate
                            break  # tool_use takes priority — stop scanning
                        elif candidate.get("action") == "text" and text_candidate is None:
                            text_candidate = candidate
                    pos = end_pos
                except _json.JSONDecodeError:
                    pos = brace_start + 1
            parsed = tool_use_candidate if tool_use_candidate is not None else text_candidate

        if parsed is None:
            # Truly no parseable JSON — treat as plain text response
            return LLMResponse(
                stop_reason="end_turn",
                text=output,
                assistant_content=[],
            )

        if parsed.get("action") == "tool_use":
            tc = ToolCall(
                id=parsed.get("id", "tc_1"),
                name=parsed["tool"],
                input=parsed.get("input", {}),
            )
            # assistant_content mirrors what the API would return for multi-turn continuity
            assistant_content = [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}]
            return LLMResponse(
                stop_reason="tool_use",
                tool_calls=[tc],
                assistant_content=assistant_content,
            )
        else:
            return LLMResponse(
                stop_reason="end_turn",
                text=parsed.get("content", output),
                assistant_content=[],
            )


class OpenAICompatibleClient:
    """
    OpenAI-compatible API client (works with OpenRouter, OpenAI, Groq,
    Together, Ollama, LM Studio, and any provider exposing the
    OpenAI Chat Completions API format).
    """

    def __init__(self, api_key: str, base_url: str, model: str, max_tokens: int | None = None) -> None:
        import os as _os
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens if max_tokens is not None else int(_os.getenv("MAX_TOKENS", "4096"))

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
    ) -> LLMResponse:
        """
        Send messages to an OpenAI-compatible endpoint.

        tools: list of provider-agnostic tool dicts (agent/tools.py format).
               Translated to OpenAI format here.
        """
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

        # If system prompt is provided, prepend it as a system message.
        # OpenAI-compatible APIs expect the system message in the messages list.
        api_messages = messages
        if system:
            api_messages = [{"role": "system", "content": system}] + list(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": api_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        logger.info(
            "OpenAI-compatible request: model=%s messages=%d tools=%d max_tokens=%d",
            self._model, len(api_messages), len(tools), self._max_tokens,
        )
        raw = self._client.chat.completions.create(**kwargs)
        usage = raw.usage
        logger.info(
            "OpenAI-compatible response: finish_reason=%s prompt_tokens=%s completion_tokens=%s",
            raw.choices[0].finish_reason,
            usage.prompt_tokens if usage else "?",
            usage.completion_tokens if usage else "?",
        )

        choice = raw.choices[0]
        message = choice.message

        tool_calls = []
        text = message.content or ""

        # Build assistant_content in a format compatible with multi-turn history.
        # We mirror the Anthropic content block structure for consistency across providers.
        assistant_content: list = []
        if text:
            assistant_content.append({"type": "text", "text": text})

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=tool_input))
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tool_input,
                })

        stop_reason = "tool_use" if tool_calls else "end_turn"

        return LLMResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            assistant_content=assistant_content,
            raw=raw,
        )
