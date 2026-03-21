# tests/test_modify.py
from unittest.mock import MagicMock, patch, call
import pytest
from tests.conftest import make_mock_doc, make_mock_parameter
from modify import set_parameter, set_parameters_batch, save_as, open_in_inventor


def test_set_parameter_updates_expression():
    param = make_mock_parameter("Width", "100 mm", "mm")
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.UserParameters.Item.return_value = param
    result = set_parameter(doc, "Width", "150 mm")
    assert result["name"] == "Width"
    assert result["old_value"] == "100 mm"
    assert result["new_value"] == "150 mm"
    assert param.Expression == "150 mm"


def test_set_parameter_raises_on_unknown_param():
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = Exception("not found")
    with pytest.raises(ValueError, match="Parameter 'NoSuchParam' not found"):
        set_parameter(doc, "NoSuchParam", "10 mm")


def test_set_parameters_batch_applies_all():
    params = {
        "Width": make_mock_parameter("Width", "100 mm", "mm"),
        "Height": make_mock_parameter("Height", "50 mm", "mm"),
    }
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = (
        lambda name: params[name]
    )
    results = set_parameters_batch(doc, {"Width": "120 mm", "Height": "60 mm"})
    assert len(results) == 2
    assert params["Width"].Expression == "120 mm"
    assert params["Height"].Expression == "60 mm"


def test_set_parameters_batch_collects_errors():
    doc = MagicMock()
    doc.ComponentDefinition.Parameters.UserParameters.Item.side_effect = Exception("not found")
    results = set_parameters_batch(doc, {"Bad": "1 mm"}, raise_on_error=False)
    assert results[0]["error"] is not None


def test_save_as_calls_saveas(tmp_path):
    doc = MagicMock()
    dest = tmp_path / "modified.ipt"
    result = save_as(doc, dest)
    # save_copy_as=False means the doc object is remapped to the new path (Inventor API semantics)
    doc.SaveAs.assert_called_once_with(str(dest), False)
    assert result == dest


def test_open_in_inventor_calls_open():
    mock_conn = MagicMock()
    mock_doc = MagicMock()
    mock_conn.open_document.return_value = mock_doc
    result = open_in_inventor(mock_conn, "/output/modified.ipt")
    mock_conn.open_document.assert_called_once_with("/output/modified.ipt")
    assert result is mock_doc
