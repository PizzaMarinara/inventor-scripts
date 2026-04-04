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


def test_describe_model_labels_user_parameters(mock_doc):
    result = describe_model(mock_doc)
    assert "[user" in result


def test_describe_model_shows_parameter_count_breakdown():
    from tests.conftest import make_mock_parameter, make_mock_doc
    doc = make_mock_doc(
        parameters=[make_mock_parameter("Length", "100 mm", "mm")],
        model_parameters=[make_mock_parameter("d0", "25 mm", "mm")],
        reference_parameters=[make_mock_parameter("Volume", "1000 mm3", "mm3")],
    )
    result = describe_model(doc)
    assert "1 user" in result
    assert "1 model" in result
    assert "1 reference" in result


def test_describe_model_marks_reference_params_as_read_only():
    from tests.conftest import make_mock_parameter, make_mock_doc
    doc = make_mock_doc(
        parameters=[],
        reference_parameters=[make_mock_parameter("FaceArea", "5000 mm2", "mm2")],
    )
    result = describe_model(doc)
    assert "FaceArea" in result
    assert "read-only" in result.lower()


def test_describe_model_shows_parameters_none_found_when_empty():
    from tests.conftest import make_mock_doc
    doc = make_mock_doc(parameters=[], model_parameters=[], reference_parameters=[])
    result = describe_model(doc)
    assert "PARAMETERS: none found" in result


def test_describe_model_includes_occurrences_for_assembly():
    from tests.conftest import make_mock_occurrence, make_mock_assembly_doc
    occ = make_mock_occurrence("maincyl:1", "Cylinder_Main", "C:/models/maincyl.ipt")
    doc = make_mock_assembly_doc(occurrences=[occ])
    result = describe_model(doc)
    assert "maincyl:1" in result
    assert "OCCURRENCES" in result


def test_describe_model_no_occurrences_section_for_part(mock_doc):
    """A plain part document should not have an OCCURRENCES section."""
    result = describe_model(mock_doc)
    assert "OCCURRENCES" not in result


def test_describe_model_occurrences_show_suppressed_state():
    from tests.conftest import make_mock_occurrence, make_mock_assembly_doc
    occ = make_mock_occurrence("lid:1", "Lid", "C:/lid.ipt", suppressed=True)
    doc = make_mock_assembly_doc(occurrences=[occ])
    result = describe_model(doc)
    assert "suppressed=True" in result


# ── Bug S-2: describe_model must pass app through to extract_occurrences ───────

from unittest.mock import MagicMock, patch


def test_describe_model_passes_app_to_extract_occurrences():
    """Bug S-2: describe_model must forward app to extract_occurrences so that
    unloaded sub-assembly documents can be opened for recursive traversal."""
    from tests.conftest import make_mock_assembly_doc, make_mock_occurrence
    doc = make_mock_assembly_doc(occurrences=[])
    app = MagicMock()

    with patch("agent.describe.extract_all") as mock_extract_all:
        mock_extract_all.return_value = {
            "display_name": "test.iam",
            "source_file": "C:/test.iam",
            "parameters": {},
            "bom": [],
            "occurrences": [],
            "properties": {},
        }
        describe_model(doc, app=app)

    mock_extract_all.assert_called_once_with(doc, app=app)


def test_describe_model_app_forwarded_to_extract_occurrences_real_call():
    """Bug S-2: extract_all must pass app down to extract_occurrences."""
    from tests.conftest import make_mock_assembly_doc
    doc = make_mock_assembly_doc(occurrences=[])
    app = MagicMock()

    with patch("extract.extract_occurrences") as mock_extract_occ:
        mock_extract_occ.return_value = []
        from extract import extract_all
        extract_all(doc, app=app)

    mock_extract_occ.assert_called_once_with(doc, app)
