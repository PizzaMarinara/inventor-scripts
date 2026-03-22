# tests/conftest.py
"""
Shared test fixtures and COM stubs.

IMPORTANT — win32com stub loading order:
  The pytest_configure hook fires before any test module is collected or
  imported. This guarantees that sys.modules["win32com"] is patched before
  inventor_api.py (or any other module) tries to import it, even on
  non-Windows CI machines.
"""
import sys
from unittest.mock import MagicMock
import pytest


def pytest_configure(config):
    """Stub win32com so the test suite runs on any OS."""
    sys.modules.setdefault("win32com", MagicMock())
    sys.modules.setdefault("win32com.client", MagicMock())


# ─────────────────────────────────────────────────────────────────────────────
# Factory helpers (importable by test modules via `from tests.conftest import …`)
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_parameter(name: str, expression: str, units: str, comment: str = "") -> MagicMock:
    p = MagicMock()
    p.Name = name
    p.Expression = expression
    p.Units = units
    p.Comment = comment
    return p


def make_mock_bom_row(item_number: str, part_name: str, quantity: int) -> MagicMock:
    """
    Build a BOM row mock where the DisplayName chain resolves to a real string.

    The key issue: `row.ComponentDefinitions.Item(1).Document.DisplayName`
    involves a *call* (Item(1)), so a simple attribute assignment on the mock
    chain won't work — each call returns a fresh MagicMock. We must configure
    the return_value explicitly at each call site.
    """
    row = MagicMock()
    row.ItemNumber = item_number
    row.ItemQuantity = quantity
    # Wire the call chain so Item(1) always returns the same sub-mock
    comp_def = MagicMock()
    comp_def.Document.DisplayName = part_name
    row.ComponentDefinitions.Item.return_value = comp_def
    return row


def make_mock_doc(
    doc_type: str = "ipt",
    parameters: list | None = None,
    model_parameters: list | None = None,
    reference_parameters: list | None = None,
    bom_rows: list | None = None,
) -> MagicMock:
    """Build a mock Inventor document object."""
    doc = MagicMock()
    doc.DisplayName = f"TestPart.{doc_type}"
    doc.FullFileName = f"C:/models/TestPart.{doc_type}"

    # ── Properties ───────────────────────────────────────────────────────────
    prop_set = MagicMock()
    prop_set.Name = "Design Tracking Properties"
    prop = MagicMock()
    prop.Name = "Description"
    prop.Value = "Test component"
    prop_set.__iter__ = MagicMock(side_effect=lambda: iter([prop]))
    doc.PropertySets.__iter__ = MagicMock(side_effect=lambda: iter([prop_set]))

    # ── Parameters ───────────────────────────────────────────────────────────
    user_params = parameters if parameters is not None else [
        make_mock_parameter("Width", "100 mm", "mm"),
        make_mock_parameter("Height", "50 mm", "mm"),
        make_mock_parameter("CylinderLength", "200 mm", "mm", "Main cylinder body"),
    ]
    model_params = model_parameters if model_parameters is not None else []
    ref_params = reference_parameters if reference_parameters is not None else []

    doc.ComponentDefinition.Parameters.UserParameters.__iter__ = MagicMock(
        side_effect=lambda p=user_params: iter(p)
    )
    doc.ComponentDefinition.Parameters.ModelParameters.__iter__ = MagicMock(
        side_effect=lambda p=model_params: iter(p)
    )
    doc.ComponentDefinition.Parameters.ReferenceParameters.__iter__ = MagicMock(
        side_effect=lambda p=ref_params: iter(p)
    )

    # ── BOM (empty by default; pass bom_rows to populate) ────────────────────
    rows = bom_rows or []
    view = MagicMock()
    view.__iter__ = MagicMock(side_effect=lambda r=rows: iter(r))
    doc.ComponentDefinition.BOM.BOMViews.__iter__ = MagicMock(side_effect=lambda: iter([view]))

    return doc


# ─────────────────────────────────────────────────────────────────────────────
# pytest fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_doc():
    return make_mock_doc()


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.Visible = False
    return app


@pytest.fixture
def mock_conn():
    """InventorConnection stand-in with a pre-wired open_document."""
    conn = MagicMock()
    conn.app = MagicMock()
    conn.open_document.return_value = MagicMock()
    return conn
