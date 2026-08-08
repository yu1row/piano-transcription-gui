# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Windows onedir build (CPU torch)."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH)  # type: ignore[name-defined]

datas: list = []
binaries: list = []
hiddenimports: list = [
    "customtkinter",
    "darkdetect",
    "PIL",
    "PIL._tkinter_finder",
    "sklearn.utils._cython_blas",
    "pkg_resources.py2_warn",
]

# Collect package data / binaries that PyInstaller often misses
for pkg in (
    "customtkinter",
    "piano_transcription_inference",
    "librosa",
    "resampy",
    "sklearn",
    "torchaudio",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # pragma: no cover
        print(f"[spec] warn: collect_all({pkg}) failed: {exc}", file=sys.stderr)

# torch is large; collect_all is the practical approach for inference apps
try:
    torch_datas, torch_binaries, torch_hidden = collect_all("torch")
    datas += torch_datas
    binaries += torch_binaries
    hiddenimports += torch_hidden
except Exception as exc:  # pragma: no cover
    print(f"[spec] warn: collect_all(torch) failed: {exc}", file=sys.stderr)

datas += collect_data_files("customtkinter")

# Optional bundled ffmpeg.exe placed by scripts/build_windows.ps1
ffmpeg_src = ROOT / "third_party" / "ffmpeg" / "ffmpeg.exe"
if ffmpeg_src.is_file():
    datas.append((str(ffmpeg_src), "."))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["hooks/runtime_path.py"],
    excludes=[
        # Prefer a leaner CPU redistributable (install CPU torch wheels before building)
        "torchvision",
        "torchaudio.datasets",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "tensorboard",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    module_collection_mode={
        # TorchScript / some torch internals expect .py sources
        "torch": "pyz+py",
        "piano_transcription_inference": "pyz+py",
    },
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PianoTranscriptionGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app; set True temporarily for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PianoTranscriptionGUI",
)
