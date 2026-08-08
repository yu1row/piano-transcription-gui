"""Suggest transcription parameters from a short audio analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from audio_io import load_audio
from transcriber import TranscriptionParams


@dataclass
class ParamSuggestion:
    params: TranscriptionParams
    reasons: List[str]
    stats: dict


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


def suggest_params_from_audio(
    audio_path: str,
    base: Optional[TranscriptionParams] = None,
    analyze_seconds: float = 45.0,
) -> ParamSuggestion:
    """Heuristic parameter suggestion for piano solo recordings.

    Uses loudness, onset density, and spectral flatness (noise-ish) of the
    beginning of the file to nudge thresholds away from defaults.
    """
    import librosa

    base = base or TranscriptionParams()
    # Analyze up to analyze_seconds from the start (fast enough for GUI)
    y, sr = load_audio(audio_path, sr=16000, mono=True, duration=analyze_seconds)
    if y.size < sr // 2:
        raise ValueError("音声が短すぎて解析できません。")

    duration = float(len(y)) / float(sr)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    mean_rms = float(np.mean(rms) + 1e-12)
    peak = float(np.max(np.abs(y)) + 1e-12)
    crest = peak / mean_rms

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
    onset_rate = float(len(onsets) / max(duration, 1e-6))

    flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))
    # High-frequency energy ratio as a rough "brightness / noise" cue
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = float(np.mean(S[freqs < 1000])) + 1e-12
    high = float(np.mean(S[freqs >= 3000])) + 1e-12
    high_ratio = high / low

    onset = 0.30
    offset = 0.30
    frame = 0.10
    pedal = 0.20
    segment = 10.0
    reasons: list[str] = []

    if mean_rms < 0.04:
        onset -= 0.06
        frame -= 0.03
        pedal -= 0.04
        reasons.append(f"音量が小さめ (RMS={mean_rms:.3f}) → 閾値を下げて拾いやすく")
    elif mean_rms > 0.18:
        onset += 0.04
        frame += 0.02
        reasons.append(f"音量が大きめ (RMS={mean_rms:.3f}) → 閾値を上げて誤検出を抑制")

    if onset_rate >= 7.0:
        onset += 0.05
        offset += 0.03
        segment = 8.0
        reasons.append(
            f"オンセットが密 (約 {onset_rate:.1f}/秒) → Onset/Offset を上げ、セグメントを短めに"
        )
    elif onset_rate <= 1.5:
        onset -= 0.03
        frame -= 0.02
        reasons.append(f"オンセットが疎 (約 {onset_rate:.1f}/秒) → 閾値を下げて取りこぼし低減")

    if flatness > 0.12 or high_ratio > 0.85:
        onset += 0.07
        frame += 0.04
        offset += 0.04
        pedal += 0.03
        reasons.append(
            f"ノイズ/残響っぽさ (flatness={flatness:.3f}, high_ratio={high_ratio:.2f}) → 閾値を上げる"
        )

    if crest > 12:
        frame = min(frame, 0.08)
        reasons.append(f"ダイナミクスが大きい (crest={crest:.1f}) → Frame を少し下げて持続を拾う")

    if not reasons:
        reasons.append("特徴が標準的なため、論文推奨に近いデフォルトを採用")

    # Noisy / dense material often benefits from ghost cleanup
    remove_ghost = base.remove_ghost_notes
    if flatness > 0.12 or high_ratio > 0.85 or onset_rate >= 7.0:
        remove_ghost = True
        reasons.append("誤検出が出やすい特徴のため、ゴーストノート除去を推奨 ON")

    params = TranscriptionParams(
        device=base.device,
        checkpoint_path=base.checkpoint_path,
        segment_seconds=_clamp(segment, 2.0, 20.0),
        onset_threshold=_clamp(onset, 0.05, 0.90),
        offset_threshold=_clamp(offset, 0.05, 0.90),
        frame_threshold=_clamp(frame, 0.02, 0.80),
        pedal_offset_threshold=_clamp(pedal, 0.05, 0.90),
        batch_size=base.batch_size,
        remove_ghost_notes=remove_ghost,
        ghost_min_duration_ms=base.ghost_min_duration_ms,
        ghost_min_velocity=base.ghost_min_velocity,
        ghost_merge_same_pitch_ms=base.ghost_merge_same_pitch_ms,
    )

    stats = {
        "duration_analyzed_sec": duration,
        "mean_rms": mean_rms,
        "peak": peak,
        "crest": crest,
        "onset_rate": onset_rate,
        "spectral_flatness": flatness,
        "high_ratio": high_ratio,
    }
    return ParamSuggestion(params=params, reasons=reasons, stats=stats)
