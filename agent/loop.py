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
from extract import (
    extract_parameters, extract_bom, extract_properties,
    extract_occurrences, extract_all_occurrence_parameters,
)
from modify import (
    set_parameter, set_parameters_batch, save_as, open_in_inventor,
    add_component, remove_component, set_suppressed,
    _get_or_open_sub_doc, _find_occurrence,
)

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
- Call describe_model at the START of a session (before the first action) or whenever
  the document context is not yet available in the conversation history. Do NOT call it
  again if the document has already been described earlier in this same conversation.
- Use exact parameter names from describe_model output (case-sensitive).
- Parameters are labelled [user], [model], or [reference]. Model parameters (d0, d1, …)
  are writable. Reference parameters are read-only — attempting to write them returns an error.
- If a parameter name is ambiguous, list candidates and ask the engineer to confirm.
- After making parameter changes, always call save_as to persist them.
- After saving, offer to call open_in_inventor so the engineer can verify.
- Be concise. Report what changed, what the old and new values were.
- If describe_model returns "unknown" for the file name or reports no parameters,
  warn the engineer that Inventor may not have an active document open.

Script generation (generate_script tool):
- Use generate_script when: the task is complex, involves multiple steps,
  might need to be repeated, or involves conditional logic.
- If the user explicitly asks for a script, you MUST generate one regardless of task simplicity.
- If unsure whether to generate a script or execute directly, ask the user:
  "Would you like me to create a reusable script for this, or just do it now?"
- Python scripts must be complete standalone programs: include win32com.client imports,
  COM connection setup (Dispatch('Inventor.Application')), error handling (try/except),
  and cleanup (app.Quit() or proper release). Use the INVENTOR_FILE environment variable
  to determine which file to operate on if available.
- iLogic rules are simpler — write the rule body directly without imports or COM setup.
- After generating a script, inform the user of the filename and what it does.

Occurrence tools (assembly only):
- Occurrence names include a :N suffix (e.g. "maincyl:1", not "maincyl"). Always use
  the full name exactly as shown in describe_model output. Do not strip the suffix.
- To inspect or edit a sub-component's parameters, use get_occurrence_parameters first,
  then set_occurrence_parameter. Sub-component parameters are NOT visible in describe_model.
- After set_occurrence_parameter, you MUST call both:
    1. save_occurrence_document — persists the modified sub-part to disk
    2. save_as — persists the parent assembly
  Skipping either leaves changes in memory only.
- Before calling remove_component, state in your response which occurrence will be deleted
  and confirm intent with the engineer. Never call remove_component speculatively.
- When an engineer asks to "save a copy of the whole project" (assembly + all sub-parts),
  warn that save_as saves only the assembly file. Sub-part references still point to their
  original paths in the saved copy. A fully portable copy requires Pack-and-Go,
  which is not yet implemented in this tool.
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

        elif name == "list_occurrences":
            return extract_occurrences(self.doc, getattr(self.conn, "app", None))

        elif name == "add_component":
            return add_component(
                self.doc,
                self.conn.app,
                inp["file_path"],
                inp.get("translation_mm"),
            )

        elif name == "remove_component":
            occ, parent_doc = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            last_segment = inp["occurrence_name"].split("/")[-1]
            return remove_component(parent_doc, last_segment)

        elif name == "suppress_component":
            occ, parent_doc = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            last_segment = inp["occurrence_name"].split("/")[-1]
            return set_suppressed(parent_doc, last_segment, True)

        elif name == "unsuppress_component":
            occ, parent_doc = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            last_segment = inp["occurrence_name"].split("/")[-1]
            return set_suppressed(parent_doc, last_segment, False)

        elif name == "get_occurrence_parameters":
            occ, _ = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            sub_doc = _get_or_open_sub_doc(occ, self.conn.app)
            return extract_parameters(sub_doc)

        elif name == "set_occurrence_parameter":
            occ, _ = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            sub_doc = _get_or_open_sub_doc(occ, self.conn.app)
            return set_parameter(sub_doc, inp["param_name"], inp["value"])

        elif name == "save_occurrence_document":
            occ, _ = _find_occurrence(
                self.doc, inp["occurrence_name"], self.conn.app
            )
            sub_doc = _get_or_open_sub_doc(occ, self.conn.app)
            dest = Path.cwd() / "output" / inp["filename"]
            saved_path = save_as(sub_doc, dest)
            return {"saved_to": str(saved_path)}

        elif name == "get_all_occurrence_parameters":
            return extract_all_occurrence_parameters(self.doc, self.conn.app)

        elif name == "generate_script":
            from script_generator import (
                validate_python_script,
                validate_ilogic_rule,
                save_script,
            )
            script_type = inp.get("script_type", "python")
            script_content = inp.get("script_content", "")
            description = inp.get("description", "Generated script")
            filename = inp.get("filename", None)

            if script_type == "python":
                is_valid, error_msg = validate_python_script(script_content)
            elif script_type == "ilogic":
                is_valid, error_msg = validate_ilogic_rule(script_content)
            else:
                return {"error": f"Invalid script type: '{script_type}'. Must be 'python' or 'ilogic'."}

            if not is_valid:
                return {"error": f"Script validation failed: {error_msg}"}

            try:
                saved_path = save_script(script_content, script_type, description, filename)
                preview_lines = script_content.split("\n")[:5]
                preview = "\n".join(preview_lines)
                if len(script_content.split("\n")) > 5:
                    preview += "\n... (truncated)"
                return {
                    "saved_to": str(saved_path),
                    "script_type": script_type,
                    "description": description,
                    "preview": preview,
                }
            except Exception as e:
                return {"error": f"Failed to save script: {e}"}

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
        # Persists the full conversation across multiple run_streaming() calls so
        # the web UI chat has memory between user messages.
        self._history: list[dict] = []

    def run_streaming(self, instruction: str) -> Iterator[StreamEvent]:
        """
        Yield StreamEvents as they occur.

        Event sequence per tool call:
            tool_start  → emitted immediately when the LLM requests a tool
            tool_result → emitted after the tool returns (or raises)
        Final event is always `done` (or `done` with error text on max_iterations).
        Used by the web layer; also the single source of truth for run().

        Conversation history from previous calls is prepended automatically so
        the agent remembers what was discussed earlier in the same session.
        """
        # Prepend history so the model has full context of the current session.
        messages: list[dict] = list(self._history) + [
            {"role": "user", "content": instruction}
        ]
        iteration = 0

        while iteration < self._max_iterations:
            iteration += 1
            logger.info(
                "Iteration %d/%d — sending %d message(s) to LLM",
                iteration, self._max_iterations, len(messages),
            )
            response: LLMResponse = self._llm.chat(
                messages=messages,
                tools=TOOLS,
                system=SYSTEM_PROMPT,
            )
            logger.info(
                "Iteration %d — LLM responded: stop_reason=%s",
                iteration, response.stop_reason,
            )

            if response.stop_reason == "end_turn":
                # Persist: add the user turn + assistant reply to history.
                assistant_msg = (
                    response.assistant_content
                    if response.assistant_content
                    else response.text
                )
                if not assistant_msg:
                    logger.warning("LLM returned empty assistant content on iteration %d", iteration)
                    assistant_msg = "(no response)"
                self._history = messages + [
                    {"role": "assistant", "content": assistant_msg}
                ]
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
                    logger.info("Tool call: %s %s", tc.name, tc.input)
                    yield StreamEvent(
                        type="tool_start",
                        tool_name=tc.name,
                        tool_input=tc.input,
                        iterations=iteration,
                    )
                    try:
                        result = self._executor.execute(tc)
                        logger.info("Tool result: %s → %s", tc.name, result)
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

        # On max iterations, do NOT save in-progress messages to history.
        # The next run_streaming() call will rebuild from the last successful
        # end_turn baseline + the new user instruction, avoiding corruption.
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
