# agent/describe.py
"""
Builds a natural-language-friendly summary of an open Inventor document.

This is the primary tool the agent calls first — it gives the LLM
the context it needs to make grounded decisions about what to modify.
"""
from __future__ import annotations
from extract import extract_all


def describe_model(doc: object) -> str:
    """
    Return a human-and-LLM-readable summary of the open document.

    The output is plain text, structured for easy parsing by an LLM:
    - File info
    - Document type hint
    - All parameters with value, unit, comment
    - BOM summary (if assembly)
    - Key properties
    """
    data = extract_all(doc)
    lines: list[str] = []

    lines.append(f"=== Inventor Document: {data['display_name']} ===")
    lines.append(f"File: {data['source_file']}")
    lines.append("")

    # ── Parameters ──────────────────────────────────────────────────────────
    params = data["parameters"]
    if params:
        lines.append(f"USER PARAMETERS ({len(params)} total):")
        for name, info in params.items():
            comment = f"  # {info['comment']}" if info.get("comment") else ""
            lines.append(f"  {name} = {info['value']}  [{info['units']}]{comment}")
    else:
        lines.append("USER PARAMETERS: none found")
    lines.append("")

    # ── BOM ─────────────────────────────────────────────────────────────────
    bom = data["bom"]
    if bom:
        lines.append(f"BOM ({len(bom)} rows):")
        for row in bom:
            lines.append(
                f"  [{row['item_number']}] {row['part_name']}  qty={row['quantity']}"
                + (f"  ({row['description']})" if row.get("description") else "")
            )
    else:
        lines.append("BOM: No BOM data (not an assembly, or BOM is empty)")
    lines.append("")

    # ── Properties ──────────────────────────────────────────────────────────
    properties = data["properties"]
    if properties:
        lines.append("DOCUMENT PROPERTIES:")
        for set_name, props in properties.items():
            for key, val in props.items():
                if val:
                    lines.append(f"  [{set_name}] {key}: {val}")
    lines.append("")

    lines.append(
        "NOTE: To modify a parameter, use set_parameter with the exact name shown above. "
        "Parameter names are case-sensitive. After changes, call save_as to persist."
    )

    return "\n".join(lines)
