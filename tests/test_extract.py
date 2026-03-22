# tests/test_extract.py
from unittest.mock import MagicMock
import pytest
from tests.conftest import make_mock_doc, make_mock_parameter, make_mock_bom_row
from extract import extract_properties, extract_parameters, extract_bom, extract_all


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
    assert "source_file" in result
    assert isinstance(result["parameters"], dict)
    assert isinstance(result["bom"], list)


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
