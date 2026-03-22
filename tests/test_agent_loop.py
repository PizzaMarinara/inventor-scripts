# tests/test_agent_loop.py
from unittest.mock import MagicMock, patch, call
import pytest
from agent.loop import AgentLoop, ToolExecutor, StreamEvent
from agent.llm import LLMResponse, ToolCall
from agent.tools import TOOLS
from tests.conftest import make_mock_doc


def make_mock_llm(responses: list) -> MagicMock:
    llm = MagicMock()
    llm.chat.side_effect = responses
    return llm


def test_agent_loop_calls_describe_then_finishes():
    """Agent should call describe_model first, then return a text response."""
    describe_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Done.")
    llm = make_mock_llm([describe_response, final_response])

    mock_doc = make_mock_doc()
    executor = ToolExecutor(doc=mock_doc, conn=MagicMock())
    loop = AgentLoop(llm=llm, executor=executor)

    result = loop.run("describe this model")

    assert result.final_text == "Done."
    assert any(tc.name == "describe_model" for tc in result.tool_calls_made)


def test_agent_loop_executes_set_parameter():
    set_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t2", name="set_parameter", input={"name": "Width", "value": "150 mm"})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Width updated to 150 mm.")
    llm = make_mock_llm([set_response, final_response])

    mock_doc = make_mock_doc()
    param = MagicMock()
    param.Expression = "100 mm"
    mock_doc.ComponentDefinition.Parameters.UserParameters.Item.return_value = param

    executor = ToolExecutor(doc=mock_doc, conn=MagicMock())
    loop = AgentLoop(llm=llm, executor=executor)

    result = loop.run("set Width to 150 mm")
    assert "150 mm" in result.final_text
    assert param.Expression == "150 mm"


def test_agent_loop_respects_max_iterations():
    # LLM always wants to call a tool — loop should stop after max_iterations
    always_tool = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    llm = MagicMock()
    llm.chat.return_value = always_tool

    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    loop = AgentLoop(llm=llm, executor=executor, max_iterations=3)

    result = loop.run("loop forever")
    assert result.iterations == 3
    assert "max iterations" in result.final_text.lower()


def test_agent_loop_continues_after_tool_error():
    """
    If a tool raises, the loop should NOT crash — it should record the error
    in tool_results and continue so the LLM can respond to the failure.
    """
    bad_tool_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t3", name="set_parameter", input={"name": "Missing", "value": "1 mm"})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Parameter not found, please check the name.")
    llm = make_mock_llm([bad_tool_response, final_response])

    mock_doc = make_mock_doc()
    mock_doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = Exception("param not found")

    executor = ToolExecutor(doc=mock_doc, conn=MagicMock())
    loop = AgentLoop(llm=llm, executor=executor)

    result = loop.run("set Missing to 1 mm")

    # Loop must complete without raising
    assert result.final_text == "Parameter not found, please check the name."
    # Error must appear in the audit trail
    assert any("error" in str(r["result"]) for r in result.tool_results)


# ── run_streaming() tests ──────────────────────────────────────────────────────


def test_run_streaming_yields_tool_start_then_result_then_done():
    """Events must arrive in order: tool_start → tool_result → done."""
    describe_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Model described.")
    llm = make_mock_llm([describe_response, final_response])

    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    loop = AgentLoop(llm=llm, executor=executor)

    events = list(loop.run_streaming("describe this model"))
    types = [e.type for e in events]

    assert "tool_start" in types
    assert "tool_result" in types
    assert types[-1] == "done"
    # tool_start must precede its matching tool_result
    assert types.index("tool_start") < types.index("tool_result")


def test_run_streaming_done_event_carries_final_text():
    final_response = LLMResponse(stop_reason="end_turn", text="All done.")
    llm = make_mock_llm([final_response])

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()))
    events = list(loop.run_streaming("noop"))
    done_events = [e for e in events if e.type == "done"]

    assert len(done_events) == 1
    assert done_events[0].content == "All done."


def test_run_streaming_emits_error_event_on_tool_exception():
    bad_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="set_parameter", input={"name": "Ghost", "value": "1 mm"})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Could not find parameter.")
    llm = make_mock_llm([bad_response, final_response])

    mock_doc = make_mock_doc()
    mock_doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = Exception("not found")
    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=mock_doc, conn=MagicMock()))

    events = list(loop.run_streaming("set Ghost to 1 mm"))
    tool_result_events = [e for e in events if e.type == "tool_result"]

    # tool_result should still be emitted even when the tool raises
    assert len(tool_result_events) == 1
    assert "not found" in str(tool_result_events[0].result).lower()


def test_run_streaming_max_iterations_emits_done():
    always_tool = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    llm = MagicMock()
    llm.chat.return_value = always_tool

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()), max_iterations=2)
    events = list(loop.run_streaming("loop forever"))

    done_events = [e for e in events if e.type == "done"]
    assert len(done_events) == 1
    assert done_events[0].iterations == 2


def test_history_persists_between_run_streaming_calls():
    """Second call to run_streaming must include the first turn in the messages list."""
    first_response = LLMResponse(stop_reason="end_turn", text="First reply.")
    second_response = LLMResponse(stop_reason="end_turn", text="Second reply.")
    llm = make_mock_llm([first_response, second_response])

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()))

    list(loop.run_streaming("First message"))
    list(loop.run_streaming("Second message"))

    # The second call must pass at least 3 messages: history user, history assistant, new user
    second_call_messages = llm.chat.call_args_list[1].kwargs["messages"]
    roles = [m["role"] for m in second_call_messages]
    assert roles == ["user", "assistant", "user"], (
        f"Expected history + new user message, got: {roles}"
    )
    assert second_call_messages[0]["content"] == "First message"
    assert second_call_messages[2]["content"] == "Second message"


def test_run_delegates_to_run_streaming():
    """run() must produce the same final_text and tool audit as run_streaming()."""
    describe_response = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    final_response = LLMResponse(stop_reason="end_turn", text="Delegated.")
    llm = make_mock_llm([describe_response, final_response])

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()))
    result = loop.run("describe")

    assert result.final_text == "Delegated."
    assert any(tc.name == "describe_model" for tc in result.tool_calls_made)
