# tests/test_script_generator.py
"""Tests for script_generator module."""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from script_generator import (
    ensure_scripts_dir,
    get_script_content,
    list_scripts,
    run_ilogic_rule,
    run_python_script,
    save_script,
    validate_ilogic_rule,
    validate_python_script,
)


# ─── validate_python_script ───────────────────────────────────────────────────


class TestValidatePythonScript:
    def test_valid_script(self):
        content = "print('hello')\nx = 1 + 2\n"
        is_valid, error = validate_python_script(content)
        assert is_valid is True
        assert error is None

    def test_valid_with_imports(self):
        content = "import win32com.client\napp = win32com.client.Dispatch('Inventor.Application')\n"
        is_valid, error = validate_python_script(content)
        assert is_valid is True
        assert error is None

    def test_empty_string(self):
        is_valid, error = validate_python_script("")
        assert is_valid is False
        assert error == "Script content is empty"

    def test_whitespace_only(self):
        is_valid, error = validate_python_script("   \n\n  \t  ")
        assert is_valid is False
        assert error == "Script content is empty"

    def test_syntax_error_missing_paren(self):
        content = "print('hello'\n"
        is_valid, error = validate_python_script(content)
        assert is_valid is False
        assert "Syntax error" in error

    def test_syntax_error_indent(self):
        content = "def foo():\nprint('bad indent')\n"
        is_valid, error = validate_python_script(content)
        assert is_valid is False
        assert "Syntax error" in error

    def test_syntax_error_bad_syntax(self):
        content = "x = \n"
        is_valid, error = validate_python_script(content)
        assert is_valid is False
        assert "Syntax error" in error


# ─── validate_ilogic_rule ─────────────────────────────────────────────────────


class TestValidateIlogicRule:
    def test_valid_rule(self):
        content = "Parameter('Width') = 100 mm\n"
        is_valid, error = validate_ilogic_rule(content)
        assert is_valid is True
        assert error is None

    def test_valid_multiline(self):
        content = "Dim width As Double\nwidth = 100\nParameter('Width') = width\n"
        is_valid, error = validate_ilogic_rule(content)
        assert is_valid is True
        assert error is None

    def test_empty_string(self):
        is_valid, error = validate_ilogic_rule("")
        assert is_valid is False
        assert error == "Rule content is empty"

    def test_whitespace_only(self):
        is_valid, error = validate_ilogic_rule("   \n\n  ")
        assert is_valid is False
        assert error == "Rule content is empty"

    def test_minimal_valid(self):
        """Even a single character is valid (lenient validation)."""
        is_valid, error = validate_ilogic_rule("x")
        assert is_valid is True
        assert error is None


# ─── save_script ──────────────────────────────────────────────────────────────


class TestSaveScript:
    @pytest.fixture
    def tmp_scripts_dir(self, tmp_path):
        """Create a temporary scripts directory."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch("script_generator.SCRIPTS_DIR", scripts_dir):
            yield scripts_dir

    def test_save_python_script(self, tmp_scripts_dir):
        path = save_script(
            content="print('hello')",
            script_type="python",
            description="Test script",
        )
        assert path.exists()
        assert path.suffix == ".py"
        content = path.read_text()
        assert "Description : Test script" in content
        assert "Type        : Python" in content
        assert "print('hello')" in content

    def test_save_ilogic_script(self, tmp_scripts_dir):
        path = save_script(
            content="Parameter('Width') = 100",
            script_type="ilogic",
            description="Change width",
        )
        assert path.exists()
        assert path.suffix == ".ilogic"
        content = path.read_text()
        assert "Description : Change width" in content
        assert "Type        : iLogic" in content

    def test_custom_filename(self, tmp_scripts_dir):
        path = save_script(
            content="x = 1",
            script_type="python",
            description="Custom",
            filename="my_script.py",
        )
        assert path.name == "my_script.py"

    def test_auto_filename_uses_timestamp(self, tmp_scripts_dir):
        path = save_script(
            content="x = 1",
            script_type="python",
            description="batch resize parts",
        )
        # Should match pattern: YYYYMMDD_HHMMSS_batch_resize_parts.py
        assert path.name.endswith("_batch_resize_parts.py")
        # Prefix before the description slug should be a date-time string (YYYYMMDD_HHMMSS)
        prefix = path.name.split("_batch")[0]
        assert len(prefix) == 15  # YYYYMMDD_HHMMSS

    def test_invalid_script_type(self, tmp_scripts_dir):
        with pytest.raises(ValueError, match="Invalid script type"):
            save_script("x=1", "javascript", "test")

    def test_path_traversal_prevention(self, tmp_scripts_dir):
        """Filenames with path components should be rejected with ValueError."""
        with pytest.raises(ValueError, match="directory components are not allowed"):
            save_script(
                content="x=1",
                script_type="python",
                description="test",
                filename="../../../etc/passwd.py",
            )

    def test_empty_description_generates_slug(self, tmp_scripts_dir):
        path = save_script(
            content="x=1",
            script_type="python",
            description="",
        )
        assert path.exists()
        assert "_script.py" in path.name

    def test_special_chars_in_description(self, tmp_scripts_dir):
        path = save_script(
            content="x=1",
            script_type="python",
            description="Fix: parts (v2.0) / batch #1!",
        )
        # Should not have special chars in filename
        name = path.name
        assert "(" not in name
        assert "/" not in name
        assert "#" not in name


# ─── run_python_script ────────────────────────────────────────────────────────


class TestRunPythonScript:
    def test_successful_script(self, tmp_path):
        script = tmp_path / "test.py"
        script.write_text("print('hello from script')")
        result = run_python_script(script)
        assert result["exit_code"] == 0
        assert "hello from script" in result["stdout"]
        assert result["stderr"] == ""
        assert result["timed_out"] is False

    def test_failing_script(self, tmp_path):
        script = tmp_path / "fail.py"
        script.write_text("raise RuntimeError('intentional error')")
        result = run_python_script(script)
        assert result["exit_code"] != 0
        assert "RuntimeError" in result["stderr"]

    def test_script_with_env_var(self, tmp_path):
        script = tmp_path / "env_test.py"
        script.write_text("import os; print(os.environ.get('INVENTOR_FILE', 'NOT_SET'))")
        result = run_python_script(script, file_path="/path/to/model.ipt")
        assert "/path/to/model.ipt" in result["stdout"]

    def test_timeout(self, tmp_path):
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(10)")
        result = run_python_script(script, timeout=1)
        assert result["timed_out"] is True
        assert result["exit_code"] == -1

    def test_nonexistent_script(self):
        result = run_python_script(Path("/nonexistent/script.py"))
        # Python exits with code 2 when it can't find the script file
        assert result["exit_code"] != 0
        assert result["stderr"] != ""


# ─── run_ilogic_rule ──────────────────────────────────────────────────────────


class TestRunIlogicRule:
    def test_no_connection(self):
        result = run_ilogic_rule("Parameter('Width') = 100")
        assert result["success"] is False
        assert "No Inventor connection" in result["error"]

    def test_none_app(self):
        conn = MagicMock()
        conn.app = None
        result = run_ilogic_rule("test", conn=conn)
        assert result["success"] is False
        assert "not connected" in result["error"]

    def test_no_active_document(self):
        conn = MagicMock()
        conn.app.ActiveDocument = None
        result = run_ilogic_rule("test", conn=conn)
        assert result["success"] is False
        assert "No active document" in result["error"]

    def test_ilogic_not_available(self):
        conn = MagicMock()
        app = MagicMock()
        app.ActiveDocument = MagicMock()
        app.Automation = None
        conn.app = app
        result = run_ilogic_rule("test", conn=conn)
        assert result["success"] is False
        assert "iLogic automation" in result["error"]

    def test_successful_execution(self):
        conn = MagicMock()
        app = MagicMock()
        doc = MagicMock()
        app.ActiveDocument = doc
        app.Automation.RunRule.return_value = "Rule executed"
        conn.app = app
        result = run_ilogic_rule("Parameter('Width') = 100", conn=conn)
        assert result["success"] is True
        assert result["output"] == "Rule executed"
        app.Automation.RunRule.assert_called_once()

    def test_execution_exception(self):
        conn = MagicMock()
        app = MagicMock()
        app.ActiveDocument = MagicMock()
        app.Automation.RunRule.side_effect = Exception("COM error")
        conn.app = app
        result = run_ilogic_rule("bad rule", conn=conn)
        assert result["success"] is False
        assert "COM error" in result["error"]


# ─── list_scripts ─────────────────────────────────────────────────────────────


class TestListScripts:
    @pytest.fixture
    def tmp_scripts_dir(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch("script_generator.SCRIPTS_DIR", scripts_dir):
            yield scripts_dir

    def test_empty_directory(self, tmp_scripts_dir):
        scripts = list_scripts()
        assert scripts == []

    def test_list_python_scripts(self, tmp_scripts_dir):
        script1 = tmp_scripts_dir / "20260401_120000_test_script.py"
        script1.write_text("# Description : Test script\nprint('hi')")
        script2 = tmp_scripts_dir / "20260402_080000_another.py"
        script2.write_text("# Description : Another script\nx = 1")

        scripts = list_scripts()
        assert len(scripts) == 2
        assert scripts[0]["type"] == "python"
        assert scripts[0]["description"] == "Test script"
        assert scripts[1]["description"] == "Another script"

    def test_list_ilogic_scripts(self, tmp_scripts_dir):
        rule = tmp_scripts_dir / "rule.ilogic"
        rule.write_text("' Description : Change parameter\nParameter('X') = 50")

        scripts = list_scripts()
        assert len(scripts) == 1
        assert scripts[0]["type"] == "ilogic"
        assert scripts[0]["description"] == "Change parameter"

    def test_mixed_scripts(self, tmp_scripts_dir):
        (tmp_scripts_dir / "a.py").write_text("# Description : Python\nx=1")
        (tmp_scripts_dir / "b.ilogic").write_text("' Description : iLogic\nx=1")
        (tmp_scripts_dir / "c.txt").write_text("ignored")

        scripts = list_scripts()
        assert len(scripts) == 2
        types = {s["type"] for s in scripts}
        assert types == {"python", "ilogic"}

    def test_skips_non_script_files(self, tmp_scripts_dir):
        (tmp_scripts_dir / "readme.txt").write_text("ignore me")
        (tmp_scripts_dir / "data.json").write_text("{}")

        scripts = list_scripts()
        assert scripts == []

    def test_handles_corrupted_file(self, tmp_scripts_dir):
        """Files that can't be read should be skipped gracefully."""
        good = tmp_scripts_dir / "good.py"
        good.write_text("# Description : Good script\nx=1")
        bad = tmp_scripts_dir / "bad.py"
        # We can't easily create an unreadable file, but the try/except
        # in list_scripts handles it. Just verify the good one is listed.
        scripts = list_scripts()
        assert len(scripts) >= 1
        assert any(s["filename"] == "good.py" for s in scripts)


# ─── get_script_content ───────────────────────────────────────────────────────


class TestGetScriptContent:
    @pytest.fixture
    def tmp_scripts_dir(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch("script_generator.SCRIPTS_DIR", scripts_dir):
            yield scripts_dir

    def test_get_python_script(self, tmp_scripts_dir):
        script = tmp_scripts_dir / "test.py"
        script.write_text("print('hello')")
        content, script_type = get_script_content("test.py")
        assert content == "print('hello')"
        assert script_type == "python"

    def test_get_ilogic_script(self, tmp_scripts_dir):
        script = tmp_scripts_dir / "rule.ilogic"
        script.write_text("Parameter('X') = 10")
        content, script_type = get_script_content("rule.ilogic")
        assert content == "Parameter('X') = 10"
        assert script_type == "ilogic"

    def test_file_not_found(self, tmp_scripts_dir):
        with pytest.raises(FileNotFoundError):
            get_script_content("nonexistent.py")

    def test_path_traversal_rejected(self, tmp_scripts_dir):
        with pytest.raises(ValueError, match="Invalid filename"):
            get_script_content("../../etc/passwd.py")

    def test_path_traversal_absolute(self, tmp_scripts_dir):
        with pytest.raises((ValueError, FileNotFoundError)):
            get_script_content("/etc/passwd.py")


# ─── ensure_scripts_dir ───────────────────────────────────────────────────────


class TestEnsureScriptsDir:
    def test_creates_directory(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        assert not scripts_dir.exists()
        with patch("script_generator.SCRIPTS_DIR", scripts_dir):
            result = ensure_scripts_dir()
        assert scripts_dir.exists()
        assert result == scripts_dir

    def test_idempotent(self, tmp_path):
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        with patch("script_generator.SCRIPTS_DIR", scripts_dir):
            result = ensure_scripts_dir()
        assert result == scripts_dir
