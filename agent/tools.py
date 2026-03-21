# agent/tools.py
"""
Provider-agnostic tool schema definitions.

Each tool is a dict with:
  name        — unique identifier called by the LLM
  description — natural language description (the LLM reads this)
  input_schema — JSON Schema dict for the input parameters

The LLM client (llm.py) translates these to provider-specific formats.
"""
from __future__ import annotations
from enum import StrEnum


class ToolName(StrEnum):
    DESCRIBE_MODEL = "describe_model"
    GET_PARAMETERS = "get_parameters"
    SET_PARAMETER = "set_parameter"
    SET_PARAMETERS_BATCH = "set_parameters_batch"
    GET_BOM = "get_bom"
    GET_PROPERTIES = "get_properties"
    SAVE_AS = "save_as"
    OPEN_IN_INVENTOR = "open_in_inventor"


TOOLS: list[dict] = [
    {
        "name": ToolName.DESCRIBE_MODEL,
        "description": (
            "Get a full semantic summary of the currently open Inventor document. "
            "Returns file name, document type (.ipt/.iam/.ipn), all user parameters "
            "with names/values/units/comments, BOM summary (for assemblies), and "
            "document properties. ALWAYS call this first before making any changes "
            "so you understand what you are working with."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": ToolName.GET_PARAMETERS,
        "description": "Get all user parameters from the open document as a name→value dict.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": ToolName.SET_PARAMETER,
        "description": (
            "Set a single parameter to a new value. "
            "Use the exact parameter name from describe_model or get_parameters. "
            "Value must be an expression string Inventor understands, e.g. '150 mm' or '2 * Width'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact parameter name (case-sensitive)",
                },
                "value": {
                    "type": "string",
                    "description": "New value expression, e.g. '150 mm'",
                },
            },
            "required": ["name", "value"],
        },
    },
    {
        "name": ToolName.SET_PARAMETERS_BATCH,
        "description": (
            "Set multiple parameters at once. More efficient than repeated set_parameter calls. "
            "Provide a dict of {parameter_name: new_value_expression}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "description": "Dict mapping parameter names to new value expressions",
                    "additionalProperties": {"type": "string"},
                }
            },
            "required": ["changes"],
        },
    },
    {
        "name": ToolName.GET_BOM,
        "description": "Get the Bill of Materials from the open assembly (.iam) document.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": ToolName.GET_PROPERTIES,
        "description": "Get all document property sets (title, description, author, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": ToolName.SAVE_AS,
        "description": (
            "Save a copy of the current document to the output directory. "
            "Always call this after making parameter changes to persist them. "
            "Returns the full path of the saved file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Output filename (e.g. 'assembly_modified.iam'). Saved to output/ dir.",
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": ToolName.OPEN_IN_INVENTOR,
        "description": "Open a file in the connected Inventor instance so the engineer can inspect it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path to the file to open",
                }
            },
            "required": ["file_path"],
        },
    },
]


def get_tool_by_name(name: str) -> dict:
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    raise KeyError(f"No tool with name '{name}'")
