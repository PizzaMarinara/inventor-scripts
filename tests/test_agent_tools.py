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


NEW_TOOL_NAMES = {
    "list_occurrences",
    "add_component",
    "remove_component",
    "suppress_component",
    "unsuppress_component",
    "get_occurrence_parameters",
    "set_occurrence_parameter",
    "save_occurrence_document",
    "generate_script",
}

# Tools from NEW_TOOL_NAMES that are assembly-only (excludes general-purpose tools)
ASSEMBLY_ONLY_NEW_TOOLS = NEW_TOOL_NAMES - {"generate_script"}


def test_all_new_tools_present():
    names = {t["name"] for t in TOOLS}
    assert NEW_TOOL_NAMES.issubset(names), f"Missing: {NEW_TOOL_NAMES - names}"


def test_all_new_tools_have_assembly_only_in_description():
    for tool in TOOLS:
        if tool["name"] in ASSEMBLY_ONLY_NEW_TOOLS:
            assert "assembly" in tool["description"].lower(), (
                f"Tool '{tool['name']}' description must note it is assembly-only"
            )


def test_add_component_has_file_path_required():
    tool = get_tool_by_name("add_component")
    assert "file_path" in tool["input_schema"]["required"]


def test_add_component_translation_mm_not_required():
    tool = get_tool_by_name("add_component")
    assert "translation_mm" not in tool["input_schema"].get("required", [])


def test_set_occurrence_parameter_has_three_required_fields():
    tool = get_tool_by_name("set_occurrence_parameter")
    required = tool["input_schema"]["required"]
    assert "occurrence_name" in required
    assert "param_name" in required
    assert "value" in required


def test_occurrence_name_tools_have_occurrence_name_required():
    for name in ("remove_component", "suppress_component", "unsuppress_component",
                 "get_occurrence_parameters"):
        tool = get_tool_by_name(name)
        assert "occurrence_name" in tool["input_schema"]["required"], (
            f"Tool '{name}' must require occurrence_name"
        )


def test_get_all_occurrence_parameters_tool_present():
    names = {t["name"] for t in TOOLS}
    assert "get_all_occurrence_parameters" in names


def test_get_all_occurrence_parameters_has_no_required_inputs():
    tool = get_tool_by_name("get_all_occurrence_parameters")
    assert tool["input_schema"].get("required", []) == []


def test_get_all_occurrence_parameters_description_mentions_assembly_and_out_of_scope():
    tool = get_tool_by_name("get_all_occurrence_parameters")
    desc = tool["description"].lower()
    assert "assembly" in desc
    assert "out_of_scope" in desc or "out of scope" in desc


def test_generate_script_has_required_fields():
    tool = get_tool_by_name("generate_script")
    required = tool["input_schema"]["required"]
    assert "script_content" in required
    assert "script_type" in required
    assert "description" in required
    assert "filename" not in required  # filename is optional


def test_generate_script_type_is_enum():
    tool = get_tool_by_name("generate_script")
    script_type_prop = tool["input_schema"]["properties"]["script_type"]
    assert script_type_prop["enum"] == ["python", "ilogic"]


def test_generate_script_mentions_user_override_in_description():
    tool = get_tool_by_name("generate_script")
    desc = tool["description"].lower()
    assert "must" in desc  # Must generate when user asks
    assert "ask" in desc   # Ask when unsure
