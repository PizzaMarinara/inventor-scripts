# tests/test_utils.py
from pathlib import Path
import pytest
from utils import ensure_dirs, write_json, write_csv

def test_ensure_dirs_creates_input_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ensure_dirs()
    assert (tmp_path / "input").exists()
    assert (tmp_path / "output").exists()

def test_write_json_round_trip(tmp_path):
    data = {"key": "value", "nested": {"a": 1}}
    dest = tmp_path / "out.json"
    write_json(data, dest)
    import json
    assert json.loads(dest.read_text()) == data

def test_write_csv_creates_rows(tmp_path):
    rows = [{"name": "Width", "value": "100 mm"}, {"name": "Height", "value": "50 mm"}]
    dest = tmp_path / "params.csv"
    write_csv(rows, dest)
    lines = dest.read_text().splitlines()
    assert lines[0] == "name,value"
    assert len(lines) == 3  # header + 2 rows
