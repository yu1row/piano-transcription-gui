"""MIDI preview synthesis and playback helpers."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class PreviewPlayer:
    """Play synthesized MIDI audio; safe to stop from another thread."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    def play_midi_file(
        self,
        midi_path: str,
        sample_rate: int = 22050,
        on_done: Optional[Callable[[], None]] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.stop()
        self._stop = threading.Event()
        stop_flag = self._stop

        def _worker() -> None:
            try:
                import numpy as np
                import pretty_midi
                import sounddevice as sd

                pm = pretty_midi.PrettyMIDI(midi_path)
                audio = np.asarray(pm.synthesize(fs=sample_rate), dtype=np.float32)
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                if peak > 1e-6:
                    audio = audio * (0.8 / peak)
                if audio.size == 0:
                    if log:
                        log("プレビュー: 無音の MIDI です（ノートが検出されていない可能性）")
                    return
                if log:
                    log(f"プレビュー再生: {midi_path} ({len(audio) / sample_rate:.1f} 秒)")
                sd.play(audio, sample_rate, blocking=False)
                while not stop_flag.is_set():
                    stream = sd.get_stream()
                    if stream is None or not getattr(stream, "active", False):
                        break
                    time.sleep(0.05)
                if stop_flag.is_set():
                    sd.stop()
            except Exception as exc:
                if log:
                    log(f"プレビュー再生エラー: {exc}")
            finally:
                if on_done:
                    on_done()

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()


def make_temp_preview_paths(prefix: str = "ptg_preview") -> tuple[Path, Path]:
    tmp = Path(tempfile.gettempdir())
    return tmp / f"{prefix}.mid", tmp / f"{prefix}.wav"
