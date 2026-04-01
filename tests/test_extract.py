# tests/test_extract.py
from unittest.mock import MagicMock
import pytest
from tests.conftest import (
    make_mock_doc,
    make_mock_parameter,
    make_mock_bom_row,
    make_mock_occurrence,
    make_mock_assembly_doc,
    make_occ_with_sub_doc,
)
from extract import (
    extract_properties, extract_parameters, extract_bom,
    extract_occurrences, extract_all, extract_all_occurrence_parameters,
)


def test_extract_properties_returns_dict(mock_doc):
    result = extract_properties(mock_doc)
    assert isinstance(result, dict)
    assert "Design Tracking Properties" in result
    assert result["Design Tracking Properties"]["Description"] == "Test component"


def test_extract_parameters_returns_named_params(mock_doc):
    result = extract_parameters(mock_doc)
    assert "Width" in result
    assert result["Width"]["value"] == "100 mm"
    assert result["Width"]["units"] == "mm"
    assert "CylinderLength" in result
    assert result["CylinderLength"]["comment"] == "Main cylinder body"


def test_extract_parameters_empty_on_no_parameters():
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.UserParameters.__iter__.side_effect = AttributeError
    doc.ComponentDefinition.Parameters.ModelParameters.__iter__.side_effect = AttributeError
    doc.ComponentDefinition.Parameters.ReferenceParameters.__iter__.side_effect = AttributeError
    result = extract_parameters(doc)
    assert result == {}


def test_extract_bom_returns_rows():
    from tests.conftest import make_mock_bom_row
    row = make_mock_bom_row(item_number="1", part_name="BoltM8", quantity=4)
    doc = make_mock_doc(bom_rows=[row])
    result = extract_bom(doc)
    assert len(result) == 1
    assert result[0]["item_number"] == "1"
    assert result[0]["quantity"] == 4
    assert result[0]["part_name"] == "BoltM8"  # verifies the call-chain mock is correct


def test_extract_bom_returns_empty_for_non_assembly():
    doc = MagicMock()
    doc.ComponentDefinition.BOM.BOMViews.__iter__.side_effect = Exception("no BOM")
    result = extract_bom(doc)
    assert result == []


def test_extract_all_returns_full_structure(mock_doc):
    result = extract_all(mock_doc)
    assert "properties" in result
    assert "parameters" in result
    assert "bom" in result
    assert "occurrences" in result
    assert "source_file" in result
    assert isinstance(result["parameters"], dict)
    assert isinstance(result["bom"], list)
    assert isinstance(result["occurrences"], list)


def test_extract_parameters_includes_type_field(mock_doc):
    result = extract_parameters(mock_doc)
    assert result["Width"]["type"] == "user"
    assert result["Height"]["type"] == "user"


def test_extract_parameters_returns_model_params():
    doc = make_mock_doc(
        parameters=[],
        model_parameters=[
            make_mock_parameter("d0", "500 mm", "mm"),
            make_mock_parameter("d1", "80 mm", "mm"),
        ],
    )
    result = extract_parameters(doc)
    assert "d0" in result
    assert result["d0"]["value"] == "500 mm"
    assert result["d0"]["type"] == "model"
    assert "d1" in result
    assert result["d1"]["type"] == "model"


def test_extract_parameters_returns_reference_params():
    doc = make_mock_doc(
        parameters=[],
        reference_parameters=[
            make_mock_parameter("FaceArea", "5026 mm2", "mm2"),
        ],
    )
    result = extract_parameters(doc)
    assert "FaceArea" in result
    assert result["FaceArea"]["type"] == "reference"


def test_extract_parameters_user_wins_on_name_collision():
    """If a model param and user param share the same name, user param wins."""
    doc = make_mock_doc(
        parameters=[make_mock_parameter("Length", "user_val mm", "mm")],
        model_parameters=[make_mock_parameter("Length", "model_val mm", "mm")],
    )
    result = extract_parameters(doc)
    assert result["Length"]["value"] == "user_val mm"
    assert result["Length"]["type"] == "user"


def test_extract_parameters_empty_when_all_collections_absent():
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.ModelParameters.__iter__.side_effect = Exception
    doc.ComponentDefinition.Parameters.UserParameters.__iter__.side_effect = Exception
    doc.ComponentDefinition.Parameters.ReferenceParameters.__iter__.side_effect = Exception
    result = extract_parameters(doc)
    assert result == {}


def test_extract_occurrences_returns_flat_list():
    occ1 = make_mock_occurrence("maincyl:1", "Cylinder_Main", "C:/models/maincyl.ipt")
    occ2 = make_mock_occurrence("base:1", "Baseplate", "C:/models/base.ipt")
    doc = make_mock_assembly_doc(occurrences=[occ1, occ2])
    result = extract_occurrences(doc)
    assert len(result) == 2
    assert result[0]["occurrence_name"] == "maincyl:1"
    assert result[0]["component_name"] == "Cylinder_Main"
    assert result[0]["file_path"] == "C:/models/maincyl.ipt"
    assert result[0]["suppressed"] is False


def test_extract_occurrences_converts_cm_to_mm():
    occ = make_mock_occurrence("part:1", "Part", "C:/p.ipt", translation_cm=(1.0, 2.0, 3.0))
    doc = make_mock_assembly_doc(occurrences=[occ])
    result = extract_occurrences(doc)
    assert result[0]["translation_mm"] == [10.0, 20.0, 30.0]


def test_extract_occurrences_includes_suppressed_flag():
    occ = make_mock_occurrence("lid:1", "Lid", "C:/lid.ipt", suppressed=True)
    doc = make_mock_assembly_doc(occurrences=[occ])
    result = extract_occurrences(doc)
    assert result[0]["suppressed"] is True


def test_extract_occurrences_returns_empty_for_non_assembly():
    """A part document does not have an Occurrences collection — return []."""
    doc = MagicMock()
    doc.ComponentDefinition.Occurrences.__iter__.side_effect = Exception("no Occurrences")
    result = extract_occurrences(doc)
    assert result == []


def test_extract_occurrences_returns_empty_for_zero_occurrences():
    doc = make_mock_assembly_doc(occurrences=[])
    result = extract_occurrences(doc)
    assert result == []


# ── helpers ──────────────────────────────────────────────────────────────────

class _UnloadedDef:
    @property
    def Document(self):
        raise Exception("not loaded")
    DisplayName = "part"


# ── tests ────────────────────────────────────────────────────────────────────

def test_extract_all_occurrence_parameters_in_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path / "input" / "bolt.ipt")
    sub_doc = make_mock_doc(parameters=[make_mock_parameter("Length", "50 mm", "mm")])
    occ = make_occ_with_sub_doc("bolt:1", file_path, sub_doc)
    doc = make_mock_assembly_doc(occurrences=[occ])

    result = extract_all_occurrence_parameters(doc, MagicMock())

    assert file_path in result
    assert result[file_path]["out_of_scope"] is False
    assert result[file_path]["occurrences"] == ["bolt:1"]
    assert "Length" in result[file_path]["parameters"]


def test_extract_all_occurrence_parameters_out_of_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path.parent / "other_project" / "washer.ipt")
    sub_doc = make_mock_doc(parameters=[make_mock_parameter("Thickness", "2 mm", "mm")])
    occ = make_occ_with_sub_doc("washer:1", file_path, sub_doc)
    doc = make_mock_assembly_doc(occurrences=[occ])

    result = extract_all_occurrence_parameters(doc, MagicMock())

    assert result[file_path]["out_of_scope"] is True


def test_extract_all_occurrence_parameters_deduplicates_file_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path / "input" / "bolt.ipt")
    sub_doc = make_mock_doc(parameters=[make_mock_parameter("Length", "50 mm", "mm")])
    occ1 = make_occ_with_sub_doc("bolt:1", file_path, sub_doc)
    occ2 = make_occ_with_sub_doc("bolt:2", file_path, sub_doc)
    doc = make_mock_assembly_doc(occurrences=[occ1, occ2])

    result = extract_all_occurrence_parameters(doc, MagicMock())

    assert len(result) == 1
    assert set(result[file_path]["occurrences"]) == {"bolt:1", "bolt:2"}
    assert "Length" in result[file_path]["parameters"]


def test_extract_all_occurrence_parameters_falls_back_to_open_when_doc_unloaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path / "input" / "part.ipt")
    sub_doc = make_mock_doc(parameters=[make_mock_parameter("Width", "100 mm", "mm")])

    occ = make_mock_occurrence("part:1", "part", file_path)
    occ.Definition = _UnloadedDef()
    doc = make_mock_assembly_doc(occurrences=[occ])
    app = MagicMock()
    app.Documents.Open.return_value = sub_doc

    result = extract_all_occurrence_parameters(doc, app)

    app.Documents.Open.assert_called_once_with(file_path)
    assert "Width" in result[file_path]["parameters"]


def test_extract_all_occurrence_parameters_error_when_doc_cannot_open(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path / "input" / "missing.ipt")

    occ = make_mock_occurrence("missing:1", "missing", file_path)
    occ.Definition = _UnloadedDef()
    doc = make_mock_assembly_doc(occurrences=[occ])
    app = MagicMock()
    app.Documents.Open.side_effect = Exception("file not found")

    result = extract_all_occurrence_parameters(doc, app)

    assert "error" in result[file_path]
    assert result[file_path]["parameters"] == {}
    assert result[file_path]["occurrences"] == ["missing:1"]


def test_extract_all_occurrence_parameters_returns_empty_for_non_assembly():
    doc = MagicMock()
    doc.ComponentDefinition.Occurrences.__iter__.side_effect = Exception("no occurrences")
    result = extract_all_occurrence_parameters(doc, MagicMock())
    assert result == {}


def test_extract_all_occurrence_parameters_recurses_into_sub_assembly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    part_path = str(tmp_path / "input" / "bolt.ipt")
    part_doc = make_mock_doc(parameters=[make_mock_parameter("Length", "50 mm", "mm")])
    part_occ = make_occ_with_sub_doc("bolt:1", part_path, part_doc)

    sub_asm_path = str(tmp_path / "input" / "bracket.iam")
    sub_asm_doc = make_mock_assembly_doc(occurrences=[part_occ])
    sub_asm_occ = make_occ_with_sub_doc("bracket:1", sub_asm_path, sub_asm_doc)

    top_doc = make_mock_assembly_doc(occurrences=[sub_asm_occ])

    result = extract_all_occurrence_parameters(top_doc, MagicMock())

    assert sub_asm_path in result
    assert part_path in result
    assert "bracket:1/bolt:1" in result[part_path]["occurrences"]
