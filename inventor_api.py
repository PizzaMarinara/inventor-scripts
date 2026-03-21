# inventor_api.py
from __future__ import annotations
import win32com.client
from pathlib import Path


class InventorConnection:
    """
    Manages a single connection to an Autodesk Inventor instance.

    Strategy:
      1. Try to attach to a running Inventor (GetActiveObject).
      2. If not running and launch_if_not_running=True, launch a new instance.
      3. Raises ConnectionError if neither succeeds.
    """

    def __init__(self) -> None:
        self._app = None

    def connect(self, launch_if_not_running: bool = True) -> object:
        """Attach to running Inventor or launch a new instance."""
        try:
            self._app = win32com.client.GetActiveObject("Inventor.Application")
        except Exception:
            if not launch_if_not_running:
                raise ConnectionError(
                    "Inventor is not running and launch_if_not_running=False"
                )
            self._app = win32com.client.Dispatch("Inventor.Application")
            self._app.Visible = True
        return self._app

    @property
    def app(self) -> object:
        if self._app is None:
            raise RuntimeError(
                "Not connected to Inventor. Call connect() first."
            )
        return self._app

    def open_document(self, file_path: str | Path) -> object:
        """Open an Inventor document and return the Document object."""
        return self.app.Documents.Open(str(file_path))

    def close_document(self, doc: object, save: bool = False) -> None:
        doc.Close(save)

    def quit(self) -> None:
        """Close the Inventor application (use carefully — closes ALL open docs)."""
        if self._app is not None:
            self._app.Quit()
            self._app = None
