# extract.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
                except Exception as e:
                    logger.debug("Could not read property %s: %s", prop.Name, e)
                    result[set_name][prop.Name] = None
    except Exception as e:
        logger.debug("Could not read property sets: %s", e)
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
            except Exception as e:
                logger.debug("Could not read %s collection: %s", collection_name, e)
    except Exception as e:
        logger.debug("Could not access parameters: %s", e)
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
                    defs = row.ComponentDefinitions
                    if defs.Count >= 1:
                        part_name = defs.Item(1).Document.DisplayName
                    else:
                        part_name = "Unknown"
                except Exception as e:
                    logger.debug("Could not read BOM row part name: %s", e)
                    part_name = "Unknown"
                rows.append({
                    "item_number": row.ItemNumber,
                    "part_name": part_name,
                    "quantity": row.ItemQuantity,
                    "description": _get_bom_row_description(row),
                })
    except Exception as e:
        logger.debug("Could not read BOM: %s", e)
    return rows


def _extract_occurrences_impl(
    doc: object,
    _prefix: str = "",
    _depth: int = 0,
) -> list[dict[str, Any]]:
    """
    Extract all component occurrences from an .iam assembly document, recursively.

    Returns a flat list — one entry per placement at every nesting level.
    Nested occurrence names use '/' as path separator, e.g. "subassy:1/part:1".
    Returns [] for part documents or any doc without an Occurrences collection.

    Each entry:
        occurrence_name  — full path name, e.g. "maincyl:1" or "subassy:1/part:1"
        component_name   — display name of the component definition
        file_path        — full path to the sub-document (works even if unloaded)
        suppressed       — bool
        translation_mm   — [x, y, z] offset from the parent assembly origin in mm
                           (Inventor stores internally in cm; multiplied by 10 here)
    """
    result: list[dict] = []
    try:
        for occ in doc.ComponentDefinition.Occurrences:
            try:
                pt = occ.Transformation.Translation
                translation_mm = [pt.X * 10, pt.Y * 10, pt.Z * 10]
                full_name = f"{_prefix}/{occ.Name}" if _prefix else occ.Name
                result.append({
                    "occurrence_name": full_name,
                    "component_name":  occ.Definition.DisplayName,
                    "file_path":       occ.ReferencedDocumentDescriptor.FullDocumentName,
                    "suppressed":      occ.Suppressed,
                    "translation_mm":  translation_mm,
                })
                # Recurse into sub-assemblies (cap depth to avoid runaway traversal)
                if _depth < 5:
                    try:
                        sub_doc = occ.Definition.Document
                        sub_occs = _extract_occurrences_impl(sub_doc, full_name, _depth + 1)
                        result.extend(sub_occs)
                    except Exception as e:
                        logger.debug("Could not recurse into sub-assembly: %s", e)
            except Exception as e:
                logger.debug("Could not read occurrence: %s", e)
    except Exception as e:
        logger.debug("Could not read occurrences: %s", e)
    return result


def extract_occurrences(doc: object) -> list[dict[str, Any]]:
    """Extract all component occurrences from an .iam assembly document."""
    return _extract_occurrences_impl(doc, _prefix="", _depth=0)


def extract_all(doc: object) -> dict[str, Any]:
    """Run all extractors and return a single consolidated dict."""
    return {
        "source_file": getattr(doc, "FullFileName", "unknown"),
        "display_name": getattr(doc, "DisplayName", "unknown"),
        "properties": extract_properties(doc),
        "parameters": extract_parameters(doc),
        "bom": extract_bom(doc),
        "occurrences": extract_occurrences(doc),
    }


def _collect_all_occurrence_params(
    doc: object,
    app: object,
    _prefix: str,
    _depth: int,
    result: dict[str, dict[str, Any]],
    scope_root: Path,
) -> None:
    try:
        for occ in doc.ComponentDefinition.Occurrences:
            try:
                full_name = f"{_prefix}/{occ.Name}" if _prefix else occ.Name
                file_path = occ.ReferencedDocumentDescriptor.FullDocumentName

                sub_doc = None
                if file_path not in result:
                    try:
                        out_of_scope = not Path(file_path).resolve().is_relative_to(scope_root)
                    except Exception:
                        out_of_scope = True

                    error = None
                    try:
                        sub_doc = occ.Definition.Document
                    except Exception:
                        try:
                            sub_doc = app.Documents.Open(str(file_path))
                        except Exception as e:
                            error = str(e)

                    if sub_doc is not None:
                        result[file_path] = {
                            "occurrences": [],
                            "parameters": extract_parameters(sub_doc),
                            "out_of_scope": out_of_scope,
                        }
                    else:
                        result[file_path] = {
                            "occurrences": [],
                            "parameters": {},
                            "out_of_scope": out_of_scope,
                            "error": error or "sub-document unavailable",
                        }

                result[file_path]["occurrences"].append(full_name)

                if _depth < 5 and sub_doc is not None:
                    try:
                        _collect_all_occurrence_params(
                            sub_doc, app, full_name, _depth + 1, result, scope_root
                        )
                    except Exception:
                        pass

            except Exception:
                pass
    except Exception:
        pass


def extract_all_occurrence_parameters(doc: object, app: object) -> dict[str, dict[str, Any]]:
    """
    For each unique part file referenced in the assembly, return:
      - occurrences: list of full path names using '/' separator for nesting
      - parameters: dict from extract_parameters() — name → {value, units, comment, type}
      - out_of_scope: True if the file is NOT under cwd/input/
      - error: (optional) message if the sub-doc could not be opened

    Traverses sub-assemblies recursively up to depth 5 (same cap as extract_occurrences).
    Parts appearing multiple times are deduplicated — parameters are read once per file path.
    Never raises — all errors are swallowed, partial results always returned.
    """
    scope_root = (Path.cwd() / "input").resolve()
    result: dict[str, dict[str, Any]] = {}
    _collect_all_occurrence_params(doc, app, "", 0, result, scope_root)
    return result
