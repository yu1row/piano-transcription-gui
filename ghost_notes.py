"""Post-process transcribed note events to drop likely ghost notes."""

from __future__ import annotations

from typing import Any


def remove_ghost_notes(
    note_events: list[dict[str, Any]],
    *,
    min_duration_ms: float = 30.0,
    min_velocity: int = 8,
    merge_same_pitch_ms: float = 30.0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter short / weak / near-duplicate same-pitch notes.

    Returns (filtered_events, stats).
    """
    min_dur = max(0.0, float(min_duration_ms)) / 1000.0
    min_vel = max(0, min(127, int(min_velocity)))
    merge_win = max(0.0, float(merge_same_pitch_ms)) / 1000.0

    sorted_notes = sorted(
        note_events,
        key=lambda n: (float(n.get("onset_time", 0.0)), int(n.get("midi_note", 0))),
    )

    kept: list[dict[str, Any]] = []
    removed_short = 0
    removed_soft = 0
    removed_dup = 0

    last_kept_by_pitch: dict[int, dict[str, Any]] = {}

    for note in sorted_notes:
        onset = float(note.get("onset_time", 0.0))
        offset = float(note.get("offset_time", onset))
        velocity = int(note.get("velocity", 0))
        pitch = int(note.get("midi_note", 0))
        duration = max(0.0, offset - onset)

        if duration < min_dur:
            removed_short += 1
            continue
        if velocity < min_vel:
            removed_soft += 1
            continue

        prev = last_kept_by_pitch.get(pitch)
        if prev is not None and merge_win > 0:
            prev_onset = float(prev.get("onset_time", 0.0))
            if abs(onset - prev_onset) <= merge_win:
                # Keep the louder (or longer) note; drop the other as a ghost double-hit.
                prev_vel = int(prev.get("velocity", 0))
                prev_dur = max(
                    0.0, float(prev.get("offset_time", prev_onset)) - prev_onset
                )
                prefer_new = (velocity, duration) > (prev_vel, prev_dur)
                if prefer_new:
                    kept.remove(prev)
                    kept.append(note)
                    last_kept_by_pitch[pitch] = note
                removed_dup += 1
                continue

        kept.append(note)
        last_kept_by_pitch[pitch] = note

    # Stable chronological order for MIDI write
    kept.sort(key=lambda n: (float(n["onset_time"]), int(n["midi_note"])))
    stats = {
        "input": len(note_events),
        "output": len(kept),
        "removed_short": removed_short,
        "removed_soft": removed_soft,
        "removed_duplicate": removed_dup,
    }
    return kept, stats
