# extract.py
from __future__ import annotations
from typing import Any


def extract_properties(doc: object) -> dict[str, dict[str, Any]]:
    """Extract all property sets from any Inventor document."""
    result: dict[str, dict] = {}
    try:
        for prop_set in doc.PropertySets:
            set_name = prop_set.Name
            result[set_name] = {}
            for prop in prop_set:
                try:
                    result[set_name][prop.Name] = prop.Value
                except Exception:
                    result[set_name][prop.Name] = None
    except Exception:
        pass
    return result


def extract_parameters(doc: object) -> dict[str, dict[str, Any]]:
    """
    Extract parameters from .ipt or .iam documents — all three types.

    Returns a dict keyed by parameter name. Each entry has:
        value   — expression string (e.g. "500 mm")
        units   — unit string (e.g. "mm")
        comment — user comment, may be empty string
        type    — "model" | "user" | "reference"

    Loop order is intentional: model first, then user. A user parameter with
    the same name as a model parameter overwrites the model entry, matching
    Inventor's own precedence rules.

    ReferenceParameters are read-only computed values. They are included in
    the output (type="reference") so the AI can see them, but set_parameter()
    will refuse to write to them.
    """
    result: dict[str, dict] = {}
    collections = [
        ("model",     "ModelParameters"),
        ("user",      "UserParameters"),
        ("reference", "ReferenceParameters"),
    ]
    try:
        params = doc.ComponentDefinition.Parameters
        for type_tag, collection_name in collections:
            try:
                for param in getattr(params, collection_name):
                    result[param.Name] = {
                        "value":   param.Expression,
                        "units":   param.Units,
                        "comment": param.Comment,
                        "type":    type_tag,
                    }
            except Exception:
                pass  # collection absent for this doc type — skip silently
    except Exception:
        pass
    return result


def _get_bom_row_description(row: object) -> str:
    try:
        return str(row.ComponentDefinitions.Item(1).Document.PropertySets
                   .Item("Design Tracking Properties").Item("Description").Value)
    except Exception:
        return ""


def extract_bom(doc: object) -> list[dict[str, Any]]:
    """
    Extract Bill of Materials from .iam (assembly) documents.
    Returns empty list for parts, presentations, or docs without a BOM.
    """
    rows: list[dict] = []
    try:
        for view in doc.ComponentDefinition.BOM.BOMViews:
            for row in view:
                try:
                    part_name = row.ComponentDefinitions.Item(1).Document.DisplayName
                except Exception:
                    part_name = "Unknown"
                rows.append({
                    "item_number": row.ItemNumber,
                    "part_name": part_name,
                    "quantity": row.ItemQuantity,
                    "description": _get_bom_row_description(row),
                })
    except Exception:
        pass
    return rows


def extract_all(doc: object) -> dict[str, Any]:
    """Run all extractors and return a single consolidated dict."""
    return {
        "source_file": getattr(doc, "FullFileName", "unknown"),
        "display_name": getattr(doc, "DisplayName", "unknown"),
        "properties": extract_properties(doc),
        "parameters": extract_parameters(doc),
        "bom": extract_bom(doc),
    }
