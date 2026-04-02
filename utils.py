# utils.py
import json
import csv
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent


def ensure_dirs() -> None:
    """Create input/, output/, and scripts/ directories if they don't exist."""
    for name in ("input", "output", "scripts"):
        (Path.cwd() / name).mkdir(parents=True, exist_ok=True)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def output_path(filename: str) -> Path:
    return Path.cwd() / "output" / filename
