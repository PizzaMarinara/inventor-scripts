# agent/describe.py
"""
Builds a natural-language-friendly summary of an open Inventor document.

This is the primary tool the agent calls first — it gives the LLM
the context it needs to make grounded decisions about what to modify.
"""
from __future__ import annotations
from extract import extract_all


def describe_model(doc: object, app: object = None) -> str:
    """
    Return a human-and-LLM-readable summary of the open document.

    The output is plain text, structured for easy parsing by an LLM:
    - File info
    - All parameters (user, model, reference) with type labels
    - BOM summary (for assemblies)
    - Occurrences list (for assemblies)
    - Key properties
    """
    data = extract_all(doc, app=app)
    lines: list[str] = []

    lines.append(f"=== Inventor Document: {data['display_name']} ===")
    lines.append(f"File: {data['source_file']}")
    lines.append("")

    # ── Parameters ──────────────────────────────────────────────────────────
    params = data["parameters"]
    if params:
        by_type: dict[str, list] = {"user": [], "model": [], "reference": []}
        for name, info in params.items():
            by_type[info.get("type", "user")].append((name, info))

        counts = {t: len(v) for t, v in by_type.items()}
        total = len(params)
        breakdown = (
            f"{counts['user']} user, {counts['model']} model, "
            f"{counts['reference']} reference"
        )
        lines.append(f"PARAMETERS ({total} total — {breakdown}):")

        for type_tag in ("user", "model", "reference"):
            for name, info in by_type[type_tag]:
                ro = "  (read-only)" if type_tag == "reference" else ""
                comment = f"  # {info['comment']}" if info.get("comment") else ""
                lines.append(
                    f"  [{type_tag:<9}] {name} = {info['value']}  "
                    f"[{info['units']}]{ro}{comment}"
                )

        lines.append(
            "NOTE: Reference parameters are read-only. "
            "Use exact names (case-sensitive) with set_parameter. "
            "Model parameters (d0, d1, …) are writable."
        )
    else:
        lines.append("PARAMETERS: none found")
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

    # ── Occurrences (assembly only) ──────────────────────────────────────────
    occurrences = data.get("occurrences", [])
    if occurrences:
        lines.append(f"OCCURRENCES ({len(occurrences)} total):")
        for occ in occurrences:
            pos = occ["translation_mm"]
            pos_str = f"[{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f} mm]"
            lines.append(
                f"  {occ['occurrence_name']:<20} [{occ['file_path']}]"
                f"  pos={pos_str}  suppressed={occ['suppressed']}"
            )
        lines.append(
            "NOTE: Occurrence names (e.g. \"maincyl:1\") are required by occurrence tools. "
            "Parameters above are assembly-level only. "
            "Use get_occurrence_parameters to inspect a sub-component's parameters."
        )
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
