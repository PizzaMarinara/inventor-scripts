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
    mock_doc.ComponentDefinition.Parameters.ModelParameters.Item.side_effect = Exception("param not found")
    mock_doc.ComponentDefinition.Parameters.ReferenceParameters.Item.side_effect = Exception("param not found")

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
    mock_doc.ComponentDefinition.Parameters.ModelParameters.Item.side_effect = Exception("not found")
    mock_doc.ComponentDefinition.Parameters.ReferenceParameters.Item.side_effect = Exception("not found")
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


def test_max_iterations_does_not_corrupt_history():
    """H3 regression: _history must not be mutated when max iterations is hit."""
    always_tool = LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="t1", name="describe_model", input={})],
        assistant_content=[],
    )
    llm = MagicMock()
    llm.chat.return_value = always_tool

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()), max_iterations=2)
    list(loop.run_streaming("loop forever"))

    assert loop._history == [], (
        f"Expected _history to remain empty on max iterations, got: {loop._history}"
    )


def test_empty_assistant_message_uses_fallback_and_logs_warning():
    """L2 regression: empty assistant content must fall back to '(no response)' and log a warning."""
    empty_response = LLMResponse(
        stop_reason="end_turn",
        text="",
        assistant_content=[],
    )
    llm = make_mock_llm([empty_response])

    loop = AgentLoop(llm=llm, executor=ToolExecutor(doc=make_mock_doc(), conn=MagicMock()))

    with patch("agent.loop.logger") as mock_logger:
        events = list(loop.run_streaming("hello"))

    # The fallback text must be stored in history
    assert any(
        msg.get("content") == "(no response)"
        for msg in loop._history
        if msg.get("role") == "assistant"
    ), f"Expected '(no response)' fallback in history, got: {loop._history}"

    # A warning must have been logged
    mock_logger.warning.assert_called_once()
    assert "empty" in mock_logger.warning.call_args[0][0].lower()


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


from tests.conftest import make_mock_assembly_doc, make_mock_occurrence


def _make_assembly_executor():
    occ = make_mock_occurrence("maincyl:1", "Cylinder_Main", "C:/maincyl.ipt")
    doc = make_mock_assembly_doc(occurrences=[occ])
    # Wire ItemByName so occurrence tools can look up by name
    doc.ComponentDefinition.Occurrences.ItemByName.return_value = occ
    conn = MagicMock()
    return ToolExecutor(doc=doc, conn=conn), doc, occ


def test_executor_dispatches_list_occurrences():
    executor, doc, _ = _make_assembly_executor()
    tc = ToolCall(id="t1", name="list_occurrences", input={})
    result = executor.execute(tc)
    assert isinstance(result, list)


def test_executor_dispatches_add_component():
    executor, doc, _ = _make_assembly_executor()
    new_occ = MagicMock()
    new_occ.Name = "bracket:1"
    doc.ComponentDefinition.Occurrences.Add.return_value = new_occ
    tc = ToolCall(id="t1", name="add_component", input={"file_path": "C:/bracket.ipt"})
    result = executor.execute(tc)
    assert result["occurrence_name"] == "bracket:1"


def test_executor_dispatches_remove_component():
    executor, doc, occ = _make_assembly_executor()
    tc = ToolCall(id="t1", name="remove_component", input={"occurrence_name": "maincyl:1"})
    result = executor.execute(tc)
    assert result == {"removed": "maincyl:1"}
    occ.Delete.assert_called_once()


def test_executor_dispatches_suppress_component():
    executor, doc, occ = _make_assembly_executor()
    tc = ToolCall(id="t1", name="suppress_component", input={"occurrence_name": "maincyl:1"})
    result = executor.execute(tc)
    assert result["suppressed"] is True
    assert occ.Suppressed is True


def test_executor_dispatches_unsuppress_component():
    executor, doc, occ = _make_assembly_executor()
    tc = ToolCall(id="t1", name="unsuppress_component", input={"occurrence_name": "maincyl:1"})
    result = executor.execute(tc)
    assert result["suppressed"] is False


def test_executor_dispatches_get_occurrence_parameters():
    executor, doc, occ = _make_assembly_executor()
    # Wire the sub-doc with a model parameter
    sub_doc = MagicMock()
    occ.Definition.Document = sub_doc
    model_param = MagicMock()
    model_param.Name = "d0"
    model_param.Expression = "500 mm"
    model_param.Units = "mm"
    model_param.Comment = ""
    sub_doc.ComponentDefinition.Parameters.UserParameters.__iter__ = MagicMock(
        side_effect=lambda: iter([])
    )
    sub_doc.ComponentDefinition.Parameters.ModelParameters.__iter__ = MagicMock(
        side_effect=lambda: iter([model_param])
    )
    sub_doc.ComponentDefinition.Parameters.ReferenceParameters.__iter__ = MagicMock(
        side_effect=lambda: iter([])
    )
    tc = ToolCall(id="t1", name="get_occurrence_parameters", input={"occurrence_name": "maincyl:1"})
    result = executor.execute(tc)
    assert "d0" in result
    assert result["d0"]["type"] == "model"


def test_executor_dispatches_set_occurrence_parameter():
    executor, doc, occ = _make_assembly_executor()
    sub_doc = MagicMock()
    occ.Definition.Document = sub_doc
    param = MagicMock()
    param.Expression = "500 mm"
    sub_doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = Exception
    sub_doc.ComponentDefinition.Parameters.ModelParameters.Item.return_value = param
    tc = ToolCall(
        id="t1", name="set_occurrence_parameter",
        input={"occurrence_name": "maincyl:1", "param_name": "d0", "value": "700 mm"}
    )
    result = executor.execute(tc)
    assert result["new_value"] == "700 mm"
    assert param.Expression == "700 mm"


def test_executor_dispatches_save_occurrence_document():
    executor, doc, occ = _make_assembly_executor()
    sub_doc = MagicMock()
    occ.Definition.Document = sub_doc
    tc = ToolCall(
        id="t1", name="save_occurrence_document",
        input={"occurrence_name": "maincyl:1", "filename": "maincyl_modified.ipt"}
    )
    result = executor.execute(tc)
    assert "saved_to" in result
    sub_doc.SaveAs.assert_called_once()


def test_system_prompt_contains_occurrence_guidance():
    from agent.loop import SYSTEM_PROMPT
    assert "occurrence" in SYSTEM_PROMPT.lower()
    assert ":1" in SYSTEM_PROMPT or ":N" in SYSTEM_PROMPT


def test_system_prompt_contains_save_chain_guidance():
    from agent.loop import SYSTEM_PROMPT
    assert "save_occurrence_document" in SYSTEM_PROMPT


def test_system_prompt_contains_pack_and_go_warning():
    from agent.loop import SYSTEM_PROMPT
    assert "pack" in SYSTEM_PROMPT.lower() or "portable" in SYSTEM_PROMPT.lower()


def test_executor_dispatches_get_all_occurrence_parameters(tmp_path, monkeypatch):
    from tests.conftest import (
        make_mock_assembly_doc, make_mock_doc,
        make_mock_parameter, make_occ_with_sub_doc,
    )
    monkeypatch.chdir(tmp_path)

    file_path = str(tmp_path / "input" / "bolt.ipt")
    sub_doc = make_mock_doc(parameters=[make_mock_parameter("Length", "50 mm", "mm")])
    occ = make_occ_with_sub_doc("bolt:1", file_path, sub_doc)
    doc = make_mock_assembly_doc(occurrences=[occ])

    conn = MagicMock()
    executor = ToolExecutor(doc=doc, conn=conn)
    tc = ToolCall(id="t1", name="get_all_occurrence_parameters", input={})

    result = executor.execute(tc)

    assert file_path in result
    assert result[file_path]["out_of_scope"] is False
    assert "Length" in result[file_path]["parameters"]


# ── generate_script tool dispatch ──────────────────────────────────────────────


def test_executor_dispatches_generate_script_python(tmp_path, monkeypatch):
    """ToolExecutor should validate and save a Python script."""
    monkeypatch.chdir(tmp_path)
    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(
        id="t1",
        name="generate_script",
        input={
            "script_content": "print('hello')",
            "script_type": "python",
            "description": "Test script",
        },
    )
    result = executor.execute(tc)
    assert "saved_to" in result
    assert result["script_type"] == "python"
    assert result["description"] == "Test script"
    assert "preview" in result


def test_executor_dispatches_generate_script_ilogic(tmp_path, monkeypatch):
    """ToolExecutor should validate and save an iLogic rule."""
    monkeypatch.chdir(tmp_path)
    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(
        id="t1",
        name="generate_script",
        input={
            "script_content": "Parameter('Width') = 100",
            "script_type": "ilogic",
            "description": "Change width",
        },
    )
    result = executor.execute(tc)
    assert "saved_to" in result
    assert result["script_type"] == "ilogic"


def test_executor_generate_script_rejects_invalid_python(tmp_path, monkeypatch):
    """ToolExecutor should reject Python scripts with syntax errors."""
    monkeypatch.chdir(tmp_path)
    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(
        id="t1",
        name="generate_script",
        input={
            "script_content": "print('missing paren'",
            "script_type": "python",
            "description": "Bad script",
        },
    )
    result = executor.execute(tc)
    assert "error" in result
    assert "validation" in result["error"].lower()


def test_executor_generate_script_rejects_empty_content(tmp_path, monkeypatch):
    """ToolExecutor should reject empty script content."""
    monkeypatch.chdir(tmp_path)
    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(
        id="t1",
        name="generate_script",
        input={
            "script_content": "",
            "script_type": "python",
            "description": "Empty",
        },
    )
    result = executor.execute(tc)
    assert "error" in result


def test_executor_generate_script_rejects_invalid_type(tmp_path, monkeypatch):
    """ToolExecutor should reject unknown script types."""
    monkeypatch.chdir(tmp_path)
    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(
        id="t1",
        name="generate_script",
        input={
            "script_content": "x = 1",
            "script_type": "javascript",
            "description": "Wrong type",
        },
    )
    result = executor.execute(tc)
    assert "error" in result
    assert "javascript" in result["error"]


def test_system_prompt_contains_script_generation_guidance():
    from agent.loop import SYSTEM_PROMPT
    assert "generate_script" in SYSTEM_PROMPT
    assert "must" in SYSTEM_PROMPT.lower()  # Must generate when user asks
    assert "ask" in SYSTEM_PROMPT.lower()   # Ask when unsure


# ── Bug I-3: Path traversal in save_as / save_occurrence_document ─────────────

def test_tool_executor_save_as_rejects_path_traversal(tmp_path, monkeypatch):
    """Bug I-3: save_as with path traversal must return error, not write outside output/."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()

    executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
    tc = ToolCall(id="t1", name="save_as", input={"filename": "../../etc/passwd"})
    result = executor.execute(tc)

    assert "error" in result
    assert not (tmp_path.parent.parent / "etc" / "passwd").exists()


def test_tool_executor_save_occurrence_document_rejects_path_traversal(tmp_path, monkeypatch):
    """Bug I-3: save_occurrence_document with path traversal must return error."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()

    mock_conn = MagicMock()
    # _find_occurrence and _get_or_open_sub_doc are called inside; mock them out
    sub_doc = make_mock_doc()
    with patch("agent.loop._find_occurrence") as mock_find, \
         patch("agent.loop._get_or_open_sub_doc", return_value=sub_doc):
        mock_find.return_value = (MagicMock(), MagicMock())
        executor = ToolExecutor(doc=make_mock_doc(), conn=mock_conn)
        tc = ToolCall(
            id="t1",
            name="save_occurrence_document",
            input={"occurrence_name": "part:1", "filename": "../../evil.ipt"},
        )
        result = executor.execute(tc)

    assert "error" in result


# ── Bug C-3: save_as must use save_copy_as=True ───────────────────────────────

def test_tool_executor_save_as_uses_save_copy_as_true(tmp_path, monkeypatch):
    """Bug C-3: save_as tool handler must pass save_copy_as=True so the live doc
    object is not remapped to the output path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()

    with patch("agent.loop.save_as") as mock_save:
        mock_save.return_value = tmp_path / "output" / "out.ipt"
        executor = ToolExecutor(doc=make_mock_doc(), conn=MagicMock())
        tc = ToolCall(id="t1", name="save_as", input={"filename": "out.ipt"})
        executor.execute(tc)

    _doc_arg, _path_arg, *rest = mock_save.call_args.args
    kwargs = mock_save.call_args.kwargs
    save_copy_as = rest[0] if rest else kwargs.get("save_copy_as", False)
    assert save_copy_as is True, "save_as tool handler must use save_copy_as=True"
