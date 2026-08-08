"""Resolve resource paths for source runs and frozen (PyInstaller) builds."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        # onedir: exe next to bundled resources
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def manual_pdf_path() -> Path:
    root = app_root()
    candidates = [
        root / "docs" / "manual.pdf",
        root / "manual.pdf",
        root / "_internal" / "docs" / "manual.pdf",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]
