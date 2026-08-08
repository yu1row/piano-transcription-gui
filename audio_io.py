"""Audio loading compatible with modern librosa (0.10+).

Upstream piano_transcription_inference.load_audio calls
`librosa.core.audio.util.buf_to_float`, which breaks on librosa>=0.10
where `librosa.core.audio` is no longer exposed.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def load_audio(
    path: str,
    sr: int = 16000,
    mono: bool = True,
    offset: float = 0.0,
    duration: Optional[float] = None,
) -> Tuple[np.ndarray, int]:
    """Load audio as float32 mono (or original channels if mono=False)."""
    import librosa

    audio, native_sr = librosa.load(
        path,
        sr=sr,
        mono=mono,
        offset=offset,
        duration=duration,
        res_type="soxr_hq",
    )
    audio = np.asarray(audio, dtype=np.float32)
    return audio, int(native_sr if sr is None else sr)
