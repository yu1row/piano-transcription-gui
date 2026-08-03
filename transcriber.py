"""Wrapper around piano_transcription_inference with configurable parameters."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests

DEFAULT_CHECKPOINT_URL = (
    "https://zenodo.org/record/4034264/files/"
    "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)
DEFAULT_CHECKPOINT_NAME = "note_F1=0.9677_pedal_F1=0.9186.pth"
MIN_CHECKPOINT_BYTES = int(1.6e8)

AUDIO_EXTENSIONS = (
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".aiff",
    ".aif",
    ".wma",
)


@dataclass
class TranscriptionParams:
    device: str = "auto"  # auto | cuda | cpu
    checkpoint_path: Optional[str] = None
    segment_seconds: float = 10.0
    onset_threshold: float = 0.3
    offset_threshold: float = 0.3
    frame_threshold: float = 0.1
    pedal_offset_threshold: float = 0.2
    batch_size: int = 1


@dataclass
class TranscriptionResult:
    midi_path: str
    note_count: int
    pedal_count: int
    duration_sec: float
    device_used: str
    elapsed_sec: float
    messages: list[str] = field(default_factory=list)


def default_checkpoint_path() -> Path:
    return Path.home() / "piano_transcription_inference_data" / DEFAULT_CHECKPOINT_NAME


def resolve_device(preference: str) -> str:
    import torch

    pref = (preference or "auto").lower().strip()
    if pref == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if pref == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA が利用できません。CPU を選択するか、GPU/ドライバを確認してください。"
            )
        return "cuda"
    if pref == "cpu":
        return "cpu"
    raise ValueError(f"不明な device: {preference}")


def ensure_checkpoint(
    checkpoint_path: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Path:
    """Ensure the pretrained checkpoint exists (Windows-friendly HTTP download)."""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    path = Path(checkpoint_path) if checkpoint_path else default_checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.stat().st_size >= MIN_CHECKPOINT_BYTES:
        _log(f"チェックポイントを使用: {path}")
        return path

    _log("事前学習モデル (~165 MB) をダウンロードします…")
    _log(DEFAULT_CHECKPOINT_URL)

    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        with requests.get(DEFAULT_CHECKPOINT_URL, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded * 100 / total)
                        if pct >= last_pct + 5:
                            last_pct = pct
                            _log(
                                f"ダウンロード中… {pct}% "
                                f"({downloaded / 1e6:.1f} / {total / 1e6:.1f} MB)"
                            )
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    if not path.exists() or path.stat().st_size < MIN_CHECKPOINT_BYTES:
        raise RuntimeError(f"チェックポイントのダウンロードに失敗しました: {path}")

    _log(f"ダウンロード完了: {path}")
    return path


def _build_transcriptor(checkpoint: Path, segment_samples: int, device: str):
    from piano_transcription_inference import PianoTranscription

    return PianoTranscription(
        checkpoint_path=str(checkpoint),
        segment_samples=segment_samples,
        device=device,
    )


def _run_transcription(
    transcriptor,
    audio,
    midi_path: str,
    batch_size: int,
):
    """Same pipeline as PianoTranscription.transcribe, with configurable batch_size."""
    import numpy as np
    from piano_transcription_inference.pytorch_utils import forward
    from piano_transcription_inference.utilities import (
        RegressionPostProcessor,
        write_events_to_midi,
    )

    audio = audio[None, :]
    audio_len = audio.shape[1]
    pad_len = (
        int(np.ceil(audio_len / transcriptor.segment_samples)) * transcriptor.segment_samples
        - audio_len
    )
    audio = np.concatenate((audio, np.zeros((1, pad_len))), axis=1)
    segments = transcriptor.enframe(audio, transcriptor.segment_samples)

    output_dict = forward(transcriptor.model, segments, batch_size=batch_size)
    for key in list(output_dict.keys()):
        output_dict[key] = transcriptor.deframe(output_dict[key])[0:audio_len]

    post_processor = RegressionPostProcessor(
        transcriptor.frames_per_second,
        classes_num=transcriptor.classes_num,
        onset_threshold=transcriptor.onset_threshold,
        offset_threshold=transcriptor.offset_threshod,  # upstream typo
        frame_threshold=transcriptor.frame_threshold,
        pedal_offset_threshold=transcriptor.pedal_offset_threshold,
    )
    est_note_events, est_pedal_events = post_processor.output_dict_to_midi_events(output_dict)

    if midi_path:
        write_events_to_midi(
            start_time=0,
            note_events=est_note_events,
            pedal_events=est_pedal_events,
            midi_path=midi_path,
        )

    return {
        "output_dict": output_dict,
        "est_note_events": est_note_events,
        "est_pedal_events": est_pedal_events,
    }


def transcribe_file(
    audio_path: str,
    midi_path: str,
    params: TranscriptionParams,
    log: Optional[Callable[[str], None]] = None,
) -> TranscriptionResult:
    """Load audio, run piano transcription, write MIDI."""
    from piano_transcription_inference import load_audio, sample_rate

    def _log(msg: str) -> None:
        if log:
            log(msg)

    audio_path = os.path.abspath(audio_path)
    midi_path = os.path.abspath(midi_path)

    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"入力ファイルが見つかりません: {audio_path}")

    out_dir = os.path.dirname(midi_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    device = resolve_device(params.device)
    _log(f"デバイス: {device}")

    checkpoint = ensure_checkpoint(params.checkpoint_path, log=_log)
    segment_samples = max(int(sample_rate * float(params.segment_seconds)), sample_rate)
    batch_size = max(1, int(params.batch_size))
    _log(f"segment_samples = {segment_samples} ({params.segment_seconds:.1f} 秒)")
    _log(f"batch_size = {batch_size}")

    _log(f"音声を読み込み中: {audio_path}")
    audio, _ = load_audio(audio_path, sr=sample_rate, mono=True)
    duration_sec = float(len(audio)) / float(sample_rate)
    _log(f"長さ: {duration_sec:.2f} 秒 / sample_rate={sample_rate}")

    _log("モデルを初期化中…")
    transcriptor = _build_transcriptor(checkpoint, segment_samples, device)

    # Post-processing thresholds (instance attributes read by the pipeline)
    transcriptor.onset_threshold = float(params.onset_threshold)
    transcriptor.offset_threshod = float(params.offset_threshold)  # upstream typo
    transcriptor.frame_threshold = float(params.frame_threshold)
    transcriptor.pedal_offset_threshold = float(params.pedal_offset_threshold)

    _log(
        "閾値: "
        f"onset={transcriptor.onset_threshold}, "
        f"offset={transcriptor.offset_threshod}, "
        f"frame={transcriptor.frame_threshold}, "
        f"pedal_offset={transcriptor.pedal_offset_threshold}"
    )

    _log("変換を開始します…")
    t0 = time.perf_counter()
    result = _run_transcription(transcriptor, audio, midi_path, batch_size=batch_size)
    elapsed = time.perf_counter() - t0

    note_count = len(result.get("est_note_events") or [])
    pedal_count = len(result.get("est_pedal_events") or [])
    _log(f"完了: notes={note_count}, pedals={pedal_count}, 所要 {elapsed:.1f} 秒")
    _log(f"MIDI 出力: {midi_path}")

    return TranscriptionResult(
        midi_path=midi_path,
        note_count=note_count,
        pedal_count=pedal_count,
        duration_sec=duration_sec,
        device_used=device,
        elapsed_sec=elapsed,
    )
