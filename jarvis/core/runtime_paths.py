"""Mutable app data lives outside the source tree when JARVIS_DATA_DIR is set."""
import os
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT = Path(os.environ.get("JARVIS_DATA_DIR", RESOURCE_ROOT)).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
(DATA_ROOT / "data").mkdir(exist_ok=True)
