"""
Provider-agnostic LLM client.

To add a new provider:
  1. Implement a class with a .chat() method matching the LLMClient protocol.
  2. Return LLMResponse from every call — populate assistant_content so the
     agent loop can reconstruct multi-turn history without touching .raw.
  3. Pass it to AgentLoop (agent/loop.py).

Current providers: Claude (default), Claude Code CLI
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
import anthropic


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

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

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
            "max_tokens": 4096,
            "messages": messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if system:
            kwargs["system"] = system

        raw = self._client.messages.create(**kwargs)

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

        # Build prompt: embed tool schemas + history + last user message
        tool_schema_str = _json.dumps(tools, indent=2) if tools else "[]"

        # Extract just the last user message for the prompt
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg["content"]
                if isinstance(content, str):
                    last_user_msg = content
                elif isinstance(content, list):
                    # tool_result blocks — summarize
                    last_user_msg = "[Previous tool results received]"
                break

        full_prompt = f"""{system}

AVAILABLE TOOLS (JSON schemas):
{tool_schema_str}

To call a tool, respond with ONLY a JSON object in this format:
{{"action": "tool_use", "tool": "<tool_name>", "input": {{...}}, "id": "t1"}}

To give a final text response (no more tools needed), respond with:
{{"action": "text", "content": "<your response>"}}

USER REQUEST: {last_user_msg}"""

        # On Windows, npm installs a `claude.cmd` wrapper; shutil.which resolves
        # the correct executable name via PATHEXT without needing shell=True.
        import shutil
        executable = shutil.which("claude") or "claude"

        # Pass the prompt via stdin to avoid Windows command-line length limits
        # and shell-escaping issues with JSON content embedded in the prompt.
        cmd = [executable, "-p", "--output-format", "text"]
        if self._model:
            cmd.extend(["--model", self._model])

        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Claude Code CLI non trovato. "
                "Installarlo con: npm install -g @anthropic-ai/claude-code\n"
                "Dopo l'installazione riavviare PowerShell/terminale e riprovare.\n"
                "In alternativa usare ClaudeLLMClient con ANTHROPIC_API_KEY."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code CLI timed out after 120 seconds.")

        # Surface stderr / non-zero exit as a clear RuntimeError so callers
        # (web UI, CLI) can display the real message from the Claude Code CLI.
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            raise RuntimeError(
                f"Claude Code CLI fallito (exit {proc.returncode}).\n"
                f"  stderr: {stderr or '(vuoto)'}\n"
                f"  stdout: {stdout or '(vuoto)'}"
            )

        output = proc.stdout.strip()

        # Parse JSON response from Claude
        try:
            # Claude may wrap the JSON in markdown code fences — strip them
            clean = output.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            parsed = _json.loads(clean)
        except _json.JSONDecodeError:
            # If it can't be parsed as JSON, treat as plain text response
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
