# tests/test_agent_describe.py
from tests.conftest import make_mock_doc
from agent.describe import describe_model


def test_describe_model_includes_parameter_names(mock_doc):
    result = describe_model(mock_doc)
    assert "Width" in result
    assert "CylinderLength" in result


def test_describe_model_includes_values(mock_doc):
    result = describe_model(mock_doc)
    assert "100 mm" in result
    assert "200 mm" in result


def test_describe_model_includes_comments(mock_doc):
    result = describe_model(mock_doc)
    assert "Main cylinder body" in result


def test_describe_model_includes_filename(mock_doc):
    result = describe_model(mock_doc)
    assert "TestPart" in result


def test_describe_model_notes_empty_bom(mock_doc):
    result = describe_model(mock_doc)
    # Mock doc has no BOM rows — should note that
    assert "BOM" in result or "assembly" in result.lower() or "No BOM" in result
