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
