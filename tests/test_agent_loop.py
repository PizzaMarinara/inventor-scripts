# tests/test_agent_loop.py
from unittest.mock import MagicMock, patch, call
import pytest
from agent.loop import AgentLoop, ToolExecutor
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
