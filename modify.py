# modify.py
from __future__ import annotations
from pathlib import Path
from typing import Any


def set_parameter(doc: object, name: str, value: str) -> dict[str, Any]:
    """
    Set a single user parameter by name.

    Args:
        doc: Open Inventor document object
        name: Parameter name (case-sensitive, must match model)
        value: New expression string, e.g. "150 mm" or "2 * Width"

    Returns:
        Dict with name, old_value, new_value, error=None

    Raises:
        ValueError: If the parameter is not found in the document
    """
    try:
        param = doc.ComponentDefinition.Parameters.UserParameters.Item(name)
    except Exception:
        raise ValueError(f"Parameter '{name}' not found in document")

    old_value = param.Expression
    param.Expression = value
    return {"name": name, "old_value": old_value, "new_value": value, "error": None}


def set_parameters_batch(
    doc: object,
    changes: dict[str, str],
    raise_on_error: bool = True,
) -> list[dict[str, Any]]:
    """
    Apply multiple parameter changes in one call.

    Args:
        doc: Open Inventor document object
        changes: {parameter_name: new_expression_string}
        raise_on_error: If True, first error raises; if False, errors are collected

    Returns:
        List of result dicts (one per parameter, with optional 'error' key)
    """
    results = []
    for name, value in changes.items():
        try:
            result = set_parameter(doc, name, value)
        except ValueError as e:
            if raise_on_error:
                raise
            result = {"name": name, "old_value": None, "new_value": value, "error": str(e)}
        results.append(result)
    return results


def save_as(doc: object, dest_path: str | Path, save_copy_as: bool = False) -> Path:
    """
    Save the document to a new path via Inventor's SaveAs COM method.

    Args:
        doc: Open Inventor document object
        dest_path: Full destination path (must include filename and extension)
        save_copy_as: Maps directly to Inventor's SaveAs(FileName, SaveCopyAs).
                      False (default) — document object is remapped to the new
                        path; subsequent saves write to the new location.
                      True  — saves a copy; the document object stays mapped to
                        the original path.

    Returns:
        Resolved destination Path
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.SaveAs(str(dest), save_copy_as)
    return dest


def open_in_inventor(conn: object, file_path: str | Path) -> object:
    """
    Open an existing file in the connected Inventor instance.

    Args:
        conn: InventorConnection instance (already connected)
        file_path: Path to the file to open

    Returns:
        Opened Document object
    """
    return conn.open_document(str(file_path))
