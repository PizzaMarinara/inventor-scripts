# tests/test_inventor_api.py
from unittest.mock import MagicMock, patch
import pytest
from inventor_api import InventorConnection


def test_connect_attaches_to_running_instance():
    mock_app = MagicMock()
    with patch("inventor_api.win32com.client.GetActiveObject", return_value=mock_app):
        conn = InventorConnection()
        app = conn.connect(launch_if_not_running=False)
    assert app is mock_app
    assert conn.app is mock_app


def test_connect_launches_when_not_running():
    mock_app = MagicMock()
    with patch("inventor_api.win32com.client.GetActiveObject", side_effect=Exception("not running")):
        with patch("inventor_api.win32com.client.Dispatch", return_value=mock_app) as mock_dispatch:
            conn = InventorConnection()
            conn.connect(launch_if_not_running=True)
    mock_dispatch.assert_called_once_with("Inventor.Application")
    assert mock_app.Visible is True


def test_connect_raises_when_not_running_and_no_launch():
    with patch("inventor_api.win32com.client.GetActiveObject", side_effect=Exception("not running")):
        conn = InventorConnection()
        with pytest.raises(ConnectionError, match="Inventor is not running"):
            conn.connect(launch_if_not_running=False)


def test_app_raises_before_connect():
    conn = InventorConnection()
    with pytest.raises(RuntimeError, match="Not connected"):
        _ = conn.app


def test_open_document_calls_open(mock_app):
    mock_doc = MagicMock()
    mock_app.Documents.Open.return_value = mock_doc
    with patch("inventor_api.win32com.client.GetActiveObject", return_value=mock_app):
        conn = InventorConnection()
        conn.connect()
        doc = conn.open_document("C:/models/part.ipt")
    mock_app.Documents.Open.assert_called_once_with("C:/models/part.ipt")
    assert doc is mock_doc


def test_close_document_without_save(mock_app):
    mock_doc = MagicMock()
    with patch("inventor_api.win32com.client.GetActiveObject", return_value=mock_app):
        conn = InventorConnection()
        conn.connect()
        conn.close_document(mock_doc, save=False)
    mock_doc.Close.assert_called_once_with(False)
