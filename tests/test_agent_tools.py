# tests/test_agent_tools.py
import pytest
from agent.tools import TOOLS, get_tool_by_name, ToolName


def test_all_expected_tools_defined():
    names = {t["name"] for t in TOOLS}
    expected = {
        "describe_model",
        "get_parameters",
        "set_parameter",
        "set_parameters_batch",
        "get_bom",
        "get_properties",
        "save_as",
        "open_in_inventor",
    }
    assert expected.issubset(names)


def test_each_tool_has_required_keys():
    for tool in TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert "properties" in tool["input_schema"]


def test_get_tool_by_name_returns_correct():
    tool = get_tool_by_name("describe_model")
    assert tool["name"] == "describe_model"


def test_get_tool_by_name_raises_on_unknown():
    with pytest.raises(KeyError):
        get_tool_by_name("nonexistent_tool")
