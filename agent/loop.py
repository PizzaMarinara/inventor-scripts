# agent/loop.py
"""
Agent reasoning loop.

Flow per turn:
  1. Send user instruction (+ conversation history) to LLM.
  2. LLM returns tool_use → ToolExecutor dispatches, result appended to history.
  3. Repeat until LLM returns end_turn or max_iterations reached.
  4. Return AgentResult with final text + audit trail.

Two operating modes (resolved by describe_model output, not code branching):
  - Named-parameter mode: model has clear names, agent acts directly.
  - Exploratory mode: agent surfaces candidates in its text response,
    engineer confirms before a second run applies changes.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from agent.llm import LLMClient, LLMResponse, ToolCall
from agent.tools import TOOLS
from agent.describe import describe_model
from extract import extract_parameters, extract_bom, extract_properties
from modify import set_parameter, set_parameters_batch, save_as, open_in_inventor

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    type: str          # "text_delta" | "tool_start" | "tool_result" | "done" | "error"
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    result: Any = None
    iterations: int = 0


SYSTEM_PROMPT = """You are an Autodesk Inventor automation assistant.
You help engineers extract data from and modify Inventor models (.ipt, .iam, .ipn files).

Rules:
- ALWAYS call describe_model first on any new document before making changes.
- Use exact parameter names from describe_model output (case-sensitive).
- If a parameter name is ambiguous, list candidates and ask the engineer to confirm.
- After making parameter changes, always call save_as to persist them.
- After saving, offer to call open_in_inventor so the engineer can verify.
- Be concise. Report what changed, what the old and new values were.
"""


@dataclass
class AgentResult:
    final_text: str
    tool_calls_made: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    iterations: int = 0
    error: str | None = None


class ToolExecutor:
    """
    Executes tool calls against live Inventor objects.
    Decoupled from the loop so it can be mocked in tests.
    """

    def __init__(self, doc: object, conn: object) -> None:
        self.doc = doc
        self.conn = conn

    def execute(self, tool_call: ToolCall) -> Any:
        name = tool_call.name
        inp = tool_call.input

        if name == "describe_model":
            return describe_model(self.doc)

        elif name == "get_parameters":
            return extract_parameters(self.doc)

        elif name == "set_parameter":
            return set_parameter(self.doc, inp["name"], inp["value"])

        elif name == "set_parameters_batch":
            return set_parameters_batch(self.doc, inp["changes"])

        elif name == "get_bom":
            return extract_bom(self.doc)

        elif name == "get_properties":
            return extract_properties(self.doc)

        elif name == "save_as":
            dest = Path.cwd() / "output" / inp["filename"]
            saved_path = save_as(self.doc, dest)
            return {"saved_to": str(saved_path)}

        elif name == "open_in_inventor":
            open_in_inventor(self.conn, inp["file_path"])
            return {"opened": inp["file_path"]}

        else:
            return {"error": f"Unknown tool: {name}"}


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        executor: ToolExecutor,
        max_iterations: int = 10,
    ) -> None:
        self._llm = llm
        self._executor = executor
        self._max_iterations = max_iterations

    def run_streaming(self, instruction: str) -> Iterator[StreamEvent]:
        """
        Yield StreamEvents as they occur.

        Event sequence per tool call:
            tool_start  → emitted immediately when the LLM requests a tool
            tool_result → emitted after the tool returns (or raises)
        Final event is always `done` (or `done` with error text on max_iterations).
        Used by the web layer; also the single source of truth for run().
        """
        messages: list[dict] = [{"role": "user", "content": instruction}]
        iteration = 0

        while iteration < self._max_iterations:
            iteration += 1
            response: LLMResponse = self._llm.chat(
                messages=messages,
                tools=TOOLS,
                system=SYSTEM_PROMPT,
            )

            if response.stop_reason == "end_turn":
                yield StreamEvent(
                    type="done",
                    content=response.text,
                    iterations=iteration,
                )
                return

            if response.stop_reason == "tool_use":
                # Use assistant_content (provider-agnostic) — never response.raw
                messages.append({"role": "assistant", "content": response.assistant_content})

                tool_results_block = []
                for tc in response.tool_calls:
                    yield StreamEvent(
                        type="tool_start",
                        tool_name=tc.name,
                        tool_input=tc.input,
                        iterations=iteration,
                    )
                    try:
                        result = self._executor.execute(tc)
                        logger.debug("Tool %s succeeded: %s", tc.name, result)
                    except Exception as e:
                        result = {"error": str(e)}
                        logger.warning("Tool %s raised: %s", tc.name, e)

                    yield StreamEvent(
                        type="tool_result",
                        tool_name=tc.name,
                        result=result,
                        iterations=iteration,
                    )

                    result_str = (
                        json.dumps(result, default=str)
                        if not isinstance(result, str)
                        else result
                    )
                    tool_results_block.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result_str,
                    })

                messages.append({"role": "user", "content": tool_results_block})

        yield StreamEvent(
            type="done",
            content=(
                f"Reached max iterations ({self._max_iterations}) without completing. "
                "The model may be in an unexpected state. Please review and try again."
            ),
            iterations=iteration,
        )

    def run(self, instruction: str) -> AgentResult:
        """
        Blocking version — delegates to run_streaming() to avoid logic duplication.
        """
        result_text = ""
        all_tool_calls: list[ToolCall] = []
        all_tool_results: list[dict] = []
        iterations = 0

        for event in self.run_streaming(instruction):
            iterations = event.iterations or iterations
            if event.type == "done":
                result_text = event.content
            elif event.type == "tool_start":
                all_tool_calls.append(
                    ToolCall(id="", name=event.tool_name, input=event.tool_input)
                )
            elif event.type == "tool_result":
                all_tool_results.append({"tool": event.tool_name, "result": event.result})

        return AgentResult(
            final_text=result_text,
            tool_calls_made=all_tool_calls,
            tool_results=all_tool_results,
            iterations=iterations,
        )
