"""Runtime hook for frozen builds: put bundled ffmpeg on PATH."""

from __future__ import annotations

import os
import sys


def _prepend_meipass_to_path() -> None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        # onedir: ffmpeg.exe sits next to the executable
        base = os.path.dirname(sys.executable)
    if base and os.path.isdir(base):
        os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")


_prepend_meipass_to_path()
