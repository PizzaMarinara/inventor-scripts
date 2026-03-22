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
    # Assembly occurrence management
    LIST_OCCURRENCES       = "list_occurrences"
    ADD_COMPONENT          = "add_component"
    REMOVE_COMPONENT       = "remove_component"
    SUPPRESS_COMPONENT     = "suppress_component"
    UNSUPPRESS_COMPONENT   = "unsuppress_component"
    # Sub-component parametric editing
    GET_OCCURRENCE_PARAMETERS  = "get_occurrence_parameters"
    SET_OCCURRENCE_PARAMETER   = "set_occurrence_parameter"
    SAVE_OCCURRENCE_DOCUMENT   = "save_occurrence_document"


TOOLS: list[dict] = [
    {
        "name": ToolName.DESCRIBE_MODEL,
        "description": (
            "Get a full semantic summary of the currently open Inventor document. "
            "Returns file name, document type (.ipt/.iam/.ipn), all parameters "
            "(user, model, reference) with names/values/units/type labels, "
            "BOM summary and occurrences list (for assemblies), and "
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
        "description": "Get all parameters (user, model, reference) from the open document as a name→value dict with type tags.",
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
    {
        "name": ToolName.LIST_OCCURRENCES,
        "description": (
            "List all component occurrences in the open assembly. (assembly only) "
            "Returns occurrence name (e.g. 'maincyl:1'), file path, suppressed state, "
            "and XYZ position in mm. In most cases, prefer describe_model which already "
            "includes this information — use list_occurrences only for a lightweight refresh."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": ToolName.ADD_COMPONENT,
        "description": (
            "Add a .ipt or .iam file as a new occurrence in the open assembly. (assembly only) "
            "Inventor auto-assigns the occurrence name (e.g. 'bracket:1'). "
            "Optional translation_mm places it at an offset from the assembly origin. "
            "Rotation is not supported — constrain manually in Inventor if needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the .ipt or .iam file to insert",
                },
                "translation_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Optional [x, y, z] offset from assembly origin in mm",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": ToolName.REMOVE_COMPONENT,
        "description": (
            "Permanently delete an occurrence from the assembly. (assembly only) "
            "⚠️ IRREVERSIBLE — always confirm the occurrence name and state intent "
            "in your response before calling this tool. Never call speculatively."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name including :N suffix, e.g. 'maincyl:1'",
                }
            },
            "required": ["occurrence_name"],
        },
    },
    {
        "name": ToolName.SUPPRESS_COMPONENT,
        "description": (
            "Suppress an occurrence: makes it invisible and excludes it from BOM and mass. (assembly only) "
            "Safe and fully reversible with unsuppress_component."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name, e.g. 'maincyl:1'",
                }
            },
            "required": ["occurrence_name"],
        },
    },
    {
        "name": ToolName.UNSUPPRESS_COMPONENT,
        "description": (
            "Restore a suppressed occurrence to its normal visible state. (assembly only)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name, e.g. 'maincyl:1'",
                }
            },
            "required": ["occurrence_name"],
        },
    },
    {
        "name": ToolName.GET_OCCURRENCE_PARAMETERS,
        "description": (
            "Get all parameters (model, user, reference) from a specific occurrence's "
            "sub-document. (assembly only) "
            "Use this to inspect the writable dimensions of a sub-component — "
            "e.g. before calling set_occurrence_parameter to change a dimension."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name, e.g. 'maincyl:1'",
                }
            },
            "required": ["occurrence_name"],
        },
    },
    {
        "name": ToolName.SET_OCCURRENCE_PARAMETER,
        "description": (
            "Set a parameter (user or model) inside a specific occurrence's sub-document. (assembly only) "
            "After calling this, you MUST call save_occurrence_document to persist the sub-part, "
            "then save_as to persist the parent assembly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name, e.g. 'maincyl:1'",
                },
                "param_name": {
                    "type": "string",
                    "description": "Exact parameter name (case-sensitive), e.g. 'Length' or 'd0'",
                },
                "value": {
                    "type": "string",
                    "description": "New value expression, e.g. '700 mm' or 'Length + 200 mm'",
                },
            },
            "required": ["occurrence_name", "param_name", "value"],
        },
    },
    {
        "name": ToolName.SAVE_OCCURRENCE_DOCUMENT,
        "description": (
            "Save the sub-document of a specific occurrence to the output/ directory. (assembly only) "
            "Call this after set_occurrence_parameter to persist sub-part changes. "
            "Note: the parent assembly will still reference the original file path — "
            "for a fully portable project copy, Pack-and-Go is required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "occurrence_name": {
                    "type": "string",
                    "description": "Full occurrence name, e.g. 'maincyl:1'",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename, e.g. 'maincyl_modified.ipt'. Saved to output/ dir.",
                },
            },
            "required": ["occurrence_name", "filename"],
        },
    },
]


def get_tool_by_name(name: str) -> dict:
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    raise KeyError(f"No tool with name '{name}'")
