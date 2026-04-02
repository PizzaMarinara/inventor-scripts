# script_generator.py
"""
Script generation, validation, saving, and execution for Inventor automation.

Supports two script types:
  - Python: standalone .py scripts using win32com.client to connect to Inventor
  - iLogic: rules that run inside Inventor's iLogic automation interface

Scripts are stored in the scripts/ directory at the project root.
"""
from __future__ import annotations
import ast
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.llm import SAFE_ENV_VARS

BASE_DIR = Path(__file__).parent
SCRIPTS_DIR = BASE_DIR / "scripts"


def ensure_scripts_dir() -> Path:
    """Create the scripts/ directory if it doesn't exist. Returns the path."""
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    return SCRIPTS_DIR


def _generate_filename(description: str, script_type: str) -> str:
    """
    Generate a safe filename from a description and timestamp.

    Produces: <YYYYMMDD_HHMMSS>_<slug>.py
    Slug is lowercased, spaces→underscores, non-alphanumeric stripped.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = description.lower().strip()
    # Replace spaces and common separators with underscores
    for ch in (" ", "-", "/", "\\", ":", ";", ",", ".", "!", "?"):
        slug = slug.replace(ch, "_")
    # Keep only alphanumeric and underscores
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    # Collapse multiple underscores
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")
    if not slug:
        slug = "script"
    # Truncate slug to avoid overly long filenames
    slug = slug[:50]
    ext = "py" if script_type == "python" else "ilogic"
    return f"{timestamp}_{slug}.{ext}"


def _build_header(description: str, script_type: str) -> str:
    """Build a metadata header comment block for the script file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if script_type == "python":
        return textwrap.dedent(f"""\
            #!/usr/bin/env python3
            # ──────────────────────────────────────────────────────────────
            # Description : {description}
            # Type        : Python (win32com)
            # Generated   : {now}
            # ──────────────────────────────────────────────────────────────
        """)
    else:
        return textwrap.dedent(f"""\
            ' ──────────────────────────────────────────────────────────────
            ' Description : {description}
            ' Type        : iLogic Rule
            ' Generated   : {now}
            ' ──────────────────────────────────────────────────────────────
        """)


def validate_python_script(content: str) -> tuple[bool, str | None]:
    """
    Validate Python script syntax using ast.parse().

    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    if not content or not content.strip():
        return False, "Script content is empty"
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        msg = f"Syntax error at line {e.lineno}: {e.msg}"
        if e.text:
            msg += f"\n  {e.text.strip()}"
        return False, msg


def validate_ilogic_rule(content: str) -> tuple[bool, str | None]:
    """
    Validate iLogic rule content (lenient — no standalone parser available).

    Checks:
        - Content is not empty
        - Content has at least one non-whitespace line

    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    if not content or not content.strip():
        return False, "Rule content is empty"
    return True, None


def save_script(
    content: str,
    script_type: str,
    description: str,
    filename: str | None = None,
) -> Path:
    """
    Save a script to the scripts/ directory.

    Args:
        content: The full script/rule text (without header).
        script_type: "python" or "ilogic".
        description: Human-readable description of what the script does.
        filename: Optional filename. Auto-generated if not provided.

    Returns:
        Absolute path to the saved script file.

    Raises:
        ValueError: If script_type is not "python" or "ilogic".
        OSError: If file write fails.
    """
    if script_type not in ("python", "ilogic"):
        raise ValueError(f"Invalid script type: '{script_type}'. Must be 'python' or 'ilogic'.")

    scripts_dir = ensure_scripts_dir()

    if filename is None:
        filename = _generate_filename(description, script_type)

    # Safety: prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename:
        raise ValueError(
            f"Invalid filename '{filename}': directory components are not allowed"
        )

    file_path = scripts_dir / safe_name

    header = _build_header(description, script_type)
    full_content = header + "\n" + content.lstrip("\n")

    file_path.write_text(full_content, encoding="utf-8")
    return file_path.resolve()


def run_python_script(
    script_path: Path,
    file_path: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """
    Execute a Python script as a subprocess.

    Args:
        script_path: Absolute path to the .py script file.
        file_path: Optional Inventor file path to pass via INVENTOR_FILE env var.
        timeout: Maximum execution time in seconds (default: 60).

    Returns:
        dict with keys: exit_code, stdout, stderr, timed_out
    """
    # Use an allowlist to prevent leaking secrets (API keys, credentials) to
    # user-generated scripts. INVENTOR_FILE is the only variable scripts need.
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_VARS}
    if file_path:
        env["INVENTOR_FILE"] = file_path

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Script timed out after {timeout} seconds",
            "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Python interpreter not found at {sys.executable}",
            "timed_out": False,
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution failed: {e}",
            "timed_out": False,
        }


def run_ilogic_rule(
    content: str,
    file_path: str | None = None,
    conn: object | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """
    Execute an iLogic rule inside the connected Inventor instance.

    Uses COM to inject the rule into Inventor's iLogic automation interface
    and trigger execution.

    Args:
        content: The iLogic rule text.
        file_path: Optional path to the document to run the rule against.
        conn: InventorConnection object (provides COM access).
        timeout: Maximum execution time in seconds (default: 60).

    Returns:
        dict with keys: success, output, error
    """
    try:
        if conn is None:
            return {
                "success": False,
                "output": "",
                "error": "No Inventor connection available for iLogic execution",
            }

        app = conn.app
        if app is None:
            return {
                "success": False,
                "output": "",
                "error": "Inventor application is not connected",
            }

        # Get the active document or open the specified file
        if file_path:
            doc = app.Documents.Open(file_path)
        else:
            doc = app.ActiveDocument

        if doc is None:
            return {
                "success": False,
                "output": "",
                "error": "No active document in Inventor",
            }

        # Use iLogic automation to run the rule
        # iLogic provides an Automation interface via COM
        ilogic_auto = app.Automation
        if ilogic_auto is None:
            return {
                "success": False,
                "output": "",
                "error": "iLogic automation interface not available. Ensure iLogic is installed.",
            }

        # Run the rule text directly.
        # NOTE: The exact iLogic COM method name (RunRule / RunRuleExternal /
        # RunExternalRule) varies by Inventor version and has not been verified
        # against live COM documentation. This path is experimental — if it fails
        # the exception is caught below and returned as an error dict.
        result = ilogic_auto.RunRule(doc, "GeneratedRule", content)

        return {
            "success": True,
            "output": str(result) if result else "",
            "error": "",
        }

    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": f"iLogic execution failed: {e}",
        }


def list_scripts() -> list[dict[str, str]]:
    """
    List all scripts in the scripts/ directory with metadata.

    Returns:
        List of dicts with keys: filename, type, description, path
    """
    scripts_dir = ensure_scripts_dir()
    scripts = []

    for f in sorted(scripts_dir.iterdir()):
        if not f.is_file():
            continue

        ext = f.suffix.lower()
        if ext == ".py":
            script_type = "python"
        elif ext == ".ilogic":
            script_type = "ilogic"
        else:
            continue

        # Extract description from header comment
        description = ""
        try:
            content = f.read_text(encoding="utf-8")
            for line in content.split("\n")[:10]:
                stripped = line.strip()
                if stripped.startswith("# Description :") or stripped.startswith("' Description :"):
                    description = stripped.split(":", 1)[1].strip()
                    break
        except Exception:
            pass

        scripts.append({
            "filename": f.name,
            "type": script_type,
            "description": description,
            "path": str(f),
        })

    return scripts


def get_script_content(filename: str) -> tuple[str, str]:
    """
    Get the full content of a script file.

    Args:
        filename: The script filename (must be in scripts/ directory).

    Returns:
        (content, script_type) tuple.

    Raises:
        FileNotFoundError: If the script doesn't exist.
        ValueError: If path traversal is detected.
    """
    scripts_dir = ensure_scripts_dir()
    # Prevent path traversal
    safe_path = (scripts_dir / filename).resolve()
    if not safe_path.is_relative_to(scripts_dir.resolve()):
        raise ValueError(f"Invalid filename: '{filename}'")
    if not safe_path.is_file():
        raise FileNotFoundError(f"Script not found: {filename}")

    content = safe_path.read_text(encoding="utf-8")
    ext = safe_path.suffix.lower()
    script_type = "python" if ext == ".py" else "ilogic"
    return content, script_type
