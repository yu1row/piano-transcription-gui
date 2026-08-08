"""Piano Transcription GUI — local audio → MIDI converter."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from analyze import suggest_params_from_audio
from paths_util import manual_pdf_path
from preview import PreviewPlayer, make_temp_preview_paths
from tooltip import ToolTip
from transcriber import (
    AUDIO_EXTENSIONS,
    TranscriptionParams,
    default_checkpoint_path,
    transcribe_file,
)
from version import APP_DISPLAY_NAME, __version__

APP_TITLE = f"{APP_DISPLAY_NAME} v{__version__}"
SUPPORTED_GLOBS = " ".join(f"*{ext}" for ext in AUDIO_EXTENSIONS)

TOOLTIPS = {
    "audio": "変換したいピアノ音源ファイルです。wav / mp3 / flac など一般的な形式に対応します。",
    "midi": "書き出す MIDI ファイルの保存先です。未指定なら入力と同じ名前の .mid になります。",
    "device": "推論に使う計算デバイス。auto は CUDA があれば GPU、なければ CPU を選びます。",
    "batch": "一度に処理するセグメント数。GPU メモリに余裕があれば増やせますが、通常は 1 で十分です。",
    "segment": "長い音声を分割して推論する長さ（秒）。長いほど境界が減りますがメモリ使用量が増えます。",
    "onset": "ノート開始の検出閾値。上げると誤検出が減り、下げると弱いアタックも拾いやすくなります。",
    "offset": "ノート終了の検出閾値。上げると早めに切る傾向、下げると余韻を長く残す傾向になります。",
    "frame": "各フレームで「音が鳴っている」とみなす閾値。持続音の検出感度に影響します。",
    "pedal": "サスティンペダル終了の検出閾値。上げるとペダルを短めに、下げると長めに推定します。",
    "checkpoint": "事前学習モデル (.pth)。未配置なら初回に自動ダウンロードします。",
    "auto": "音量・オンセット密度・ノイズっぽさから閾値やセグメント長を自動推定して反映します。",
    "reset": "デバイス・閾値・セグメント長などを論文推奨に近い初期値へ戻します。",
    "ghost": "極端に短い／弱いノートや、同音の近接二重検出を MIDI 書き出し前に取り除きます。",
    "ghost_dur": "これより短いノート（ミリ秒）をゴーストとして削除します。スタッカートを消したくない場合は下げてください。",
    "ghost_vel": "これより弱いベロシティのノートを削除します（0–127）。",
    "ghost_merge": "同じ音高がこの時間（ミリ秒）以内に連続開始したら、強い方だけ残します。",
    "preview_start": "プレビュー変換を始める位置（秒）。曲の冒頭以外を試したいときに使います。",
    "preview_dur": "プレビュー用に切り出す長さ（秒）。短いほど速く試せます。",
    "preview": "指定区間だけ MIDI 変換し、簡易ピアノ音で再生します（パラメータ確認用）。",
    "manual": "説明書 PDF（docs/manual.pdf）を開きます。ビルド時に Markdown から生成されます。",
}


def normalize_display_path(path: str) -> str:
    """Normalize path separators for display (Windows uses '\\')."""
    if not path or not str(path).strip():
        return ""
    return os.path.normpath(os.path.expanduser(str(path).strip()))


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("860x860")
        self.minsize(760, 780)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._busy = False
        self._player = PreviewPlayer()
        self._last_preview_midi: str | None = None

        self._build_ui()
        self.after(100, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkLabel(
            self,
            text="ピアノ音源 → MIDI 変換",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        header.grid(row=0, column=0, padx=20, pady=(18, 4), sticky="w")

        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        subtitle = ctk.CTkLabel(
            top_row,
            text="ByteDance Piano Transcription  |  Apache-2.0",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        subtitle.grid(row=0, column=0, sticky="w")

        self.manual_btn = ctk.CTkButton(
            top_row, text="説明書 PDF", width=110, command=self._open_manual
        )
        self.manual_btn.grid(row=0, column=1, sticky="e")
        ToolTip(self.manual_btn, TOOLTIPS["manual"])

        # --- Files ---
        files = ctk.CTkFrame(self)
        files.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        files.grid_columnconfigure(1, weight=1)

        audio_lbl = ctk.CTkLabel(files, text="入力オーディオ")
        audio_lbl.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        ToolTip(audio_lbl, TOOLTIPS["audio"])
        self.audio_var = ctk.StringVar()
        ctk.CTkEntry(files, textvariable=self.audio_var).grid(
            row=0, column=1, padx=6, pady=(12, 6), sticky="ew"
        )
        ctk.CTkButton(files, text="参照…", width=90, command=self._pick_audio).grid(
            row=0, column=2, padx=(6, 12), pady=(12, 6)
        )

        midi_lbl = ctk.CTkLabel(files, text="出力 MIDI")
        midi_lbl.grid(row=1, column=0, padx=12, pady=(6, 12), sticky="w")
        ToolTip(midi_lbl, TOOLTIPS["midi"])
        self.midi_var = ctk.StringVar()
        ctk.CTkEntry(files, textvariable=self.midi_var).grid(
            row=1, column=1, padx=6, pady=(6, 12), sticky="ew"
        )
        ctk.CTkButton(files, text="参照…", width=90, command=self._pick_midi).grid(
            row=1, column=2, padx=(6, 12), pady=(6, 12)
        )

        # --- Parameters ---
        params = ctk.CTkScrollableFrame(self)
        params.grid(row=3, column=0, padx=20, pady=6, sticky="nsew")
        params.grid_columnconfigure((1, 3), weight=1)

        title_row = ctk.CTkFrame(params, fg_color="transparent")
        title_row.grid(row=0, column=0, columnspan=4, padx=4, pady=(4, 8), sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            title_row, text="変換パラメータ", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        btn_row = ctk.CTkFrame(title_row, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e")
        self.reset_btn = ctk.CTkButton(
            btn_row,
            text="デフォルトに戻す",
            width=130,
            fg_color=("gray75", "gray35"),
            command=self._reset_params,
        )
        self.reset_btn.grid(row=0, column=0, padx=(0, 8))
        ToolTip(self.reset_btn, TOOLTIPS["reset"])
        self.auto_btn = ctk.CTkButton(
            btn_row,
            text="音源から自動設定",
            width=140,
            command=self._auto_params,
        )
        self.auto_btn.grid(row=0, column=1)
        ToolTip(self.auto_btn, TOOLTIPS["auto"])

        device_lbl = ctk.CTkLabel(params, text="デバイス")
        device_lbl.grid(row=1, column=0, padx=12, pady=6, sticky="w")
        ToolTip(device_lbl, TOOLTIPS["device"])
        self.device_var = ctk.StringVar(value="auto")
        ctk.CTkOptionMenu(
            params, variable=self.device_var, values=["auto", "cuda", "cpu"], width=140
        ).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        batch_lbl = ctk.CTkLabel(params, text="バッチサイズ")
        batch_lbl.grid(row=1, column=2, padx=12, pady=6, sticky="w")
        ToolTip(batch_lbl, TOOLTIPS["batch"])
        self.batch_var = ctk.StringVar(value="1")
        ctk.CTkEntry(params, textvariable=self.batch_var, width=80).grid(
            row=1, column=3, padx=6, pady=6, sticky="w"
        )

        seg_lbl = ctk.CTkLabel(params, text="セグメント長 (秒)")
        seg_lbl.grid(row=2, column=0, padx=12, pady=6, sticky="w")
        ToolTip(seg_lbl, TOOLTIPS["segment"])
        self.segment_var = ctk.DoubleVar(value=10.0)
        self.segment_slider = ctk.CTkSlider(
            params,
            from_=2.0,
            to=20.0,
            number_of_steps=36,
            variable=self.segment_var,
            command=self._on_segment_slide,
        )
        self.segment_slider.grid(row=2, column=1, columnspan=2, padx=6, pady=6, sticky="ew")
        self.segment_label = ctk.CTkLabel(params, text="10.0")
        self.segment_label.grid(row=2, column=3, padx=6, pady=6, sticky="w")

        self.onset_var = ctk.DoubleVar(value=0.3)
        self.offset_var = ctk.DoubleVar(value=0.3)
        self.frame_var = ctk.DoubleVar(value=0.1)
        self.pedal_var = ctk.DoubleVar(value=0.2)
        self._threshold_labels: dict[str, ctk.CTkLabel] = {}

        self._add_threshold_row(params, 3, "Onset 閾値", self.onset_var, "onset", TOOLTIPS["onset"])
        self._add_threshold_row(params, 4, "Offset 閾値", self.offset_var, "offset", TOOLTIPS["offset"])
        self._add_threshold_row(params, 5, "Frame 閾値", self.frame_var, "frame", TOOLTIPS["frame"])
        self._add_threshold_row(
            params, 6, "Pedal offset 閾値", self.pedal_var, "pedal", TOOLTIPS["pedal"]
        )

        ck_lbl = ctk.CTkLabel(params, text="チェックポイント")
        ck_lbl.grid(row=7, column=0, padx=12, pady=6, sticky="w")
        ToolTip(ck_lbl, TOOLTIPS["checkpoint"])
        self.checkpoint_var = ctk.StringVar(
            value=normalize_display_path(str(default_checkpoint_path()))
        )
        ctk.CTkEntry(params, textvariable=self.checkpoint_var).grid(
            row=7, column=1, columnspan=2, padx=6, pady=6, sticky="ew"
        )
        ctk.CTkButton(params, text="参照…", width=90, command=self._pick_checkpoint).grid(
            row=7, column=3, padx=6, pady=6, sticky="w"
        )

        # Ghost-note cleanup
        ghost = ctk.CTkFrame(params)
        ghost.grid(row=8, column=0, columnspan=4, padx=8, pady=(10, 4), sticky="ew")
        ghost.grid_columnconfigure(1, weight=1)

        self.ghost_enabled_var = ctk.BooleanVar(value=False)
        self.ghost_check = ctk.CTkCheckBox(
            ghost,
            text="ゴーストノートを削除",
            variable=self.ghost_enabled_var,
            command=self._on_ghost_toggle,
        )
        self.ghost_check.grid(row=0, column=0, columnspan=4, padx=12, pady=(10, 6), sticky="w")
        ToolTip(self.ghost_check, TOOLTIPS["ghost"])

        ghost_bar = ctk.CTkFrame(ghost, fg_color="transparent")
        ghost_bar.grid(row=1, column=0, columnspan=4, padx=12, pady=(0, 10), sticky="ew")

        dur_g = ctk.CTkLabel(ghost_bar, text="最短長(ms)")
        dur_g.pack(side="left", padx=(0, 4))
        ToolTip(dur_g, TOOLTIPS["ghost_dur"])
        self.ghost_dur_var = ctk.StringVar(value="30")
        self.ghost_dur_entry = ctk.CTkEntry(ghost_bar, textvariable=self.ghost_dur_var, width=56)
        self.ghost_dur_entry.pack(side="left", padx=(0, 12))

        vel_g = ctk.CTkLabel(ghost_bar, text="最小Vel")
        vel_g.pack(side="left", padx=(0, 4))
        ToolTip(vel_g, TOOLTIPS["ghost_vel"])
        self.ghost_vel_var = ctk.StringVar(value="8")
        self.ghost_vel_entry = ctk.CTkEntry(ghost_bar, textvariable=self.ghost_vel_var, width=48)
        self.ghost_vel_entry.pack(side="left", padx=(0, 12))

        merge_g = ctk.CTkLabel(ghost_bar, text="同音マージ(ms)")
        merge_g.pack(side="left", padx=(0, 4))
        ToolTip(merge_g, TOOLTIPS["ghost_merge"])
        self.ghost_merge_var = ctk.StringVar(value="30")
        self.ghost_merge_entry = ctk.CTkEntry(
            ghost_bar, textvariable=self.ghost_merge_var, width=56
        )
        self.ghost_merge_entry.pack(side="left")
        self._on_ghost_toggle()

        # Preview controls — single compact toolbar row
        preview = ctk.CTkFrame(params)
        preview.grid(row=9, column=0, columnspan=4, padx=8, pady=(10, 8), sticky="ew")
        preview.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview, text="プレビュー（短区間）", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")
        ctk.CTkLabel(
            preview,
            text="開始位置と長さを指定して、変換結果をすぐ聴いて確認します。",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        bar = ctk.CTkFrame(preview, fg_color="transparent")
        bar.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")

        start_lbl = ctk.CTkLabel(bar, text="開始(秒)")
        start_lbl.pack(side="left", padx=(0, 4))
        ToolTip(start_lbl, TOOLTIPS["preview_start"])
        self.preview_start_var = ctk.StringVar(value="0")
        start_entry = ctk.CTkEntry(bar, textvariable=self.preview_start_var, width=64)
        start_entry.pack(side="left", padx=(0, 12))
        ToolTip(start_entry, TOOLTIPS["preview_start"])

        dur_lbl = ctk.CTkLabel(bar, text="長さ(秒)")
        dur_lbl.pack(side="left", padx=(0, 4))
        ToolTip(dur_lbl, TOOLTIPS["preview_dur"])
        self.preview_dur_var = ctk.StringVar(value="12")
        dur_entry = ctk.CTkEntry(bar, textvariable=self.preview_dur_var, width=64)
        dur_entry.pack(side="left", padx=(0, 16))
        ToolTip(dur_entry, TOOLTIPS["preview_dur"])

        self.preview_btn = ctk.CTkButton(
            bar, text="区間を変換して再生", width=150, command=self._start_preview
        )
        self.preview_btn.pack(side="left", padx=(0, 8))
        ToolTip(self.preview_btn, TOOLTIPS["preview"])

        self.stop_preview_btn = ctk.CTkButton(
            bar,
            text="再生停止",
            width=90,
            fg_color=("gray70", "gray35"),
            command=self._stop_preview,
        )
        self.stop_preview_btn.pack(side="left")

        hint = ctk.CTkLabel(
            params,
            text=(
                "初回実行時は事前学習モデル (~165 MB) を自動ダウンロードします。"
                " 各ラベルにマウスを乗せると説明が表示されます。"
            ),
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
            wraplength=760,
            justify="left",
        )
        hint.grid(row=10, column=0, columnspan=4, padx=12, pady=(4, 12), sticky="nw")

        # --- Actions / log ---
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=4, column=0, padx=20, pady=(14, 18), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(bottom, fg_color="transparent")
        actions.grid(row=0, column=0, padx=14, pady=(14, 8), sticky="ew")
        actions.grid_columnconfigure(3, weight=1)

        self.run_btn = ctk.CTkButton(
            actions, text="MIDI に変換", width=140, height=36, command=self._start_transcription
        )
        self.run_btn.grid(row=0, column=0, padx=(0, 10), pady=2)

        self.open_btn = ctk.CTkButton(
            actions,
            text="出力フォルダを開く",
            width=140,
            height=36,
            fg_color=("gray70", "gray35"),
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_btn.grid(row=0, column=1, padx=(0, 10), pady=2)

        self.status_var = ctk.StringVar(value="待機中")
        ctk.CTkLabel(actions, textvariable=self.status_var).grid(
            row=0, column=3, padx=(12, 0), pady=2, sticky="e"
        )

        self.log_box = ctk.CTkTextbox(
            bottom, height=150, font=ctk.CTkFont(family="Consolas", size=12)
        )
        self.log_box.grid(row=1, column=0, padx=14, pady=(4, 14), sticky="ew")
        self.log_box.insert("end", "ログ出力\n")
        self.log_box.configure(state="disabled")

    def _add_threshold_row(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: ctk.DoubleVar,
        key: str,
        tip: str,
    ) -> None:
        lbl = ctk.CTkLabel(parent, text=label)
        lbl.grid(row=row, column=0, padx=12, pady=6, sticky="w")
        ToolTip(lbl, tip)
        slider = ctk.CTkSlider(
            parent,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=variable,
            command=lambda v, k=key: self._on_threshold_slide(k, v),
        )
        slider.grid(row=row, column=1, columnspan=2, padx=6, pady=6, sticky="ew")
        ToolTip(slider, tip)
        value_label = ctk.CTkLabel(parent, text=f"{variable.get():.2f}")
        value_label.grid(row=row, column=3, padx=6, pady=6, sticky="w")
        self._threshold_labels[key] = value_label

    def _on_segment_slide(self, value: float) -> None:
        self.segment_label.configure(text=f"{float(value):.1f}")

    def _on_threshold_slide(self, key: str, value: float) -> None:
        label = self._threshold_labels.get(key)
        if label is not None:
            label.configure(text=f"{float(value):.2f}")

    def _on_ghost_toggle(self) -> None:
        state = "normal" if self.ghost_enabled_var.get() else "disabled"
        self.ghost_dur_entry.configure(state=state)
        self.ghost_vel_entry.configure(state=state)
        self.ghost_merge_entry.configure(state=state)

    def _apply_params_to_ui(self, params: TranscriptionParams) -> None:
        self.device_var.set(params.device)
        self.batch_var.set(str(params.batch_size))
        self.segment_var.set(params.segment_seconds)
        self.segment_label.configure(text=f"{params.segment_seconds:.1f}")
        self.onset_var.set(params.onset_threshold)
        self.offset_var.set(params.offset_threshold)
        self.frame_var.set(params.frame_threshold)
        self.pedal_var.set(params.pedal_offset_threshold)
        for key, var in (
            ("onset", self.onset_var),
            ("offset", self.offset_var),
            ("frame", self.frame_var),
            ("pedal", self.pedal_var),
        ):
            self._on_threshold_slide(key, var.get())
        if params.checkpoint_path:
            self.checkpoint_var.set(normalize_display_path(params.checkpoint_path))
        self.ghost_enabled_var.set(bool(params.remove_ghost_notes))
        self.ghost_dur_var.set(str(int(params.ghost_min_duration_ms)))
        self.ghost_vel_var.set(str(int(params.ghost_min_velocity)))
        self.ghost_merge_var.set(str(int(params.ghost_merge_same_pitch_ms)))
        self._on_ghost_toggle()

    def _reset_params(self) -> None:
        if self._busy:
            return
        defaults = TranscriptionParams()
        defaults.checkpoint_path = str(default_checkpoint_path())
        self._apply_params_to_ui(defaults)
        self._append_log("パラメータをデフォルトに戻しました")
        self.status_var.set("デフォルト設定")

    # --------------------------------------------------------------- pickers
    def _pick_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="ピアノ音源を選択",
            filetypes=[("Audio", SUPPORTED_GLOBS), ("All files", "*.*")],
        )
        if not path:
            return
        path = normalize_display_path(path)
        self.audio_var.set(path)
        if not self.midi_var.get().strip():
            self.midi_var.set(normalize_display_path(str(Path(path).with_suffix(".mid"))))

    def _pick_midi(self) -> None:
        initial = self.midi_var.get().strip() or self.audio_var.get().strip()
        initial = normalize_display_path(initial) if initial else ""
        initial_dir = str(Path(initial).parent) if initial else None
        initial_file = Path(initial).name if initial else "output.mid"
        path = filedialog.asksaveasfilename(
            title="出力 MIDI の保存先",
            defaultextension=".mid",
            initialdir=initial_dir,
            initialfile=initial_file,
            filetypes=[("MIDI", "*.mid *.midi"), ("All files", "*.*")],
        )
        if path:
            self.midi_var.set(normalize_display_path(path))

    def _pick_checkpoint(self) -> None:
        path = filedialog.askopenfilename(
            title="モデルチェックポイントを選択",
            filetypes=[("PyTorch checkpoint", "*.pth *.pt"), ("All files", "*.*")],
        )
        if path:
            self.checkpoint_var.set(normalize_display_path(path))

    # ----------------------------------------------------------------- run
    def _collect_params(self) -> TranscriptionParams:
        try:
            batch_size = int(self.batch_var.get().strip() or "1")
        except ValueError as exc:
            raise ValueError("バッチサイズは整数で指定してください。") from exc
        if batch_size < 1:
            raise ValueError("バッチサイズは 1 以上にしてください。")

        try:
            ghost_dur = float(self.ghost_dur_var.get().strip() or "30")
            ghost_vel = int(float(self.ghost_vel_var.get().strip() or "8"))
            ghost_merge = float(self.ghost_merge_var.get().strip() or "30")
        except ValueError as exc:
            raise ValueError("ゴースト除去の数値が不正です。") from exc
        if ghost_dur < 0 or ghost_merge < 0:
            raise ValueError("ゴースト除去の時間は 0 以上にしてください。")
        if not (0 <= ghost_vel <= 127):
            raise ValueError("最小ベロシティは 0〜127 にしてください。")

        checkpoint = self.checkpoint_var.get().strip() or None
        if checkpoint:
            checkpoint = normalize_display_path(checkpoint)
            self.checkpoint_var.set(checkpoint)
        return TranscriptionParams(
            device=self.device_var.get(),
            checkpoint_path=checkpoint,
            segment_seconds=float(self.segment_var.get()),
            onset_threshold=float(self.onset_var.get()),
            offset_threshold=float(self.offset_var.get()),
            frame_threshold=float(self.frame_var.get()),
            pedal_offset_threshold=float(self.pedal_var.get()),
            batch_size=batch_size,
            remove_ghost_notes=bool(self.ghost_enabled_var.get()),
            ghost_min_duration_ms=ghost_dur,
            ghost_min_velocity=ghost_vel,
            ghost_merge_same_pitch_ms=ghost_merge,
        )

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.run_btn.configure(state=state)
        self.preview_btn.configure(state=state)
        self.auto_btn.configure(state=state)
        self.reset_btn.configure(state=state)
        if status is not None:
            self.status_var.set(status)

    def _auto_params(self) -> None:
        if self._busy:
            return
        audio = normalize_display_path(self.audio_var.get())
        if audio:
            self.audio_var.set(audio)
        if not audio or not os.path.isfile(audio):
            messagebox.showwarning(APP_TITLE, "先に入力オーディオを選択してください。")
            return
        try:
            base = self._collect_params()
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return

        self._set_busy(True, "音源を解析中…")
        self._append_log("—" * 48)
        self._append_log(f"自動パラメータ推定: {audio}")

        def worker() -> None:
            try:
                suggestion = suggest_params_from_audio(audio, base=base)
                payload = {
                    "params": suggestion.params,
                    "reasons": suggestion.reasons,
                    "stats": suggestion.stats,
                }
                self._log_queue.put(("AUTO_OK", payload))
            except Exception as exc:
                self._log_queue.put(f"ERROR\t{exc}")
                self._log_queue.put(traceback.format_exc())

        threading.Thread(target=worker, daemon=True).start()

    def _start_transcription(self) -> None:
        if self._busy:
            return
        audio = normalize_display_path(self.audio_var.get())
        midi = normalize_display_path(self.midi_var.get())
        if audio:
            self.audio_var.set(audio)
        if not audio:
            messagebox.showwarning(APP_TITLE, "入力オーディオを選択してください。")
            return
        if not os.path.isfile(audio):
            messagebox.showerror(APP_TITLE, f"入力ファイルが見つかりません:\n{audio}")
            return
        if not midi:
            midi = normalize_display_path(str(Path(audio).with_suffix(".mid")))
        self.midi_var.set(midi)
        try:
            params = self._collect_params()
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return

        self._set_busy(True, "変換中…")
        self.open_btn.configure(state="disabled")
        self._append_log("—" * 48)
        self._append_log(f"開始: {audio}")

        def worker() -> None:
            try:
                result = transcribe_file(
                    audio_path=audio,
                    midi_path=midi,
                    params=params,
                    log=lambda msg: self._log_queue.put(msg),
                )
                self._log_queue.put(
                    f"SUCCESS\t{result.midi_path}\t{result.note_count}\t"
                    f"{result.pedal_count}\t{result.elapsed_sec:.1f}"
                )
            except Exception as exc:
                self._log_queue.put(f"ERROR\t{exc}")
                self._log_queue.put(traceback.format_exc())

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _start_preview(self) -> None:
        if self._busy:
            return
        audio = normalize_display_path(self.audio_var.get())
        if audio:
            self.audio_var.set(audio)
        if not audio or not os.path.isfile(audio):
            messagebox.showwarning(APP_TITLE, "入力オーディオを選択してください。")
            return
        try:
            params = self._collect_params()
            start = float(self.preview_start_var.get().strip() or "0")
            dur = float(self.preview_dur_var.get().strip() or "12")
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, f"プレビュー区間の数値が不正です: {exc}")
            return
        if start < 0 or dur <= 0.5:
            messagebox.showwarning(APP_TITLE, "開始は 0 以上、長さは 0.5 秒超にしてください。")
            return

        midi_path, _ = make_temp_preview_paths()
        self._set_busy(True, "プレビュー変換中…")
        self._append_log("—" * 48)
        self._append_log(f"プレビュー変換: {start:.1f}s から {dur:.1f}s")

        def worker() -> None:
            try:
                result = transcribe_file(
                    audio_path=audio,
                    midi_path=str(midi_path),
                    params=params,
                    log=lambda msg: self._log_queue.put(msg),
                    offset_sec=start,
                    duration_sec=dur,
                )
                self._log_queue.put(("PREVIEW_OK", result.midi_path, result.note_count))
            except Exception as exc:
                self._log_queue.put(f"ERROR\t{exc}")
                self._log_queue.put(traceback.format_exc())

        threading.Thread(target=worker, daemon=True).start()

    def _stop_preview(self) -> None:
        self._player.stop()
        self._append_log("プレビュー再生を停止しました")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if isinstance(msg, tuple) and msg and msg[0] == "AUTO_OK":
                    payload = msg[1]
                    self._apply_params_to_ui(payload["params"])
                    for reason in payload["reasons"]:
                        self._append_log(f"推定: {reason}")
                    stats = payload["stats"]
                    self._append_log(
                        "統計: "
                        f"RMS={stats['mean_rms']:.3f}, "
                        f"onset_rate={stats['onset_rate']:.2f}/s, "
                        f"flatness={stats['spectral_flatness']:.3f}"
                    )
                    self._set_busy(False, "自動設定完了")
                    messagebox.showinfo(APP_TITLE, "音源解析に基づくパラメータを反映しました。")
                elif isinstance(msg, tuple) and msg and msg[0] == "PREVIEW_OK":
                    midi_path, notes = msg[1], msg[2]
                    self._last_preview_midi = midi_path
                    self._set_busy(False, f"プレビュー準備完了 (notes={notes})")
                    self._append_log(f"プレビュー MIDI: {midi_path} (notes={notes})")
                    self._player.play_midi_file(
                        midi_path,
                        log=lambda m: self._log_queue.put(m),
                        on_done=lambda: self._log_queue.put("プレビュー再生が終了しました"),
                    )
                elif isinstance(msg, str) and msg.startswith("SUCCESS\t"):
                    parts = msg.split("\t")
                    self._on_finished(True, parts[1], parts[2], parts[3], parts[4])
                elif isinstance(msg, str) and msg.startswith("ERROR\t"):
                    err = msg.split("\t", 1)[1]
                    self._append_log(f"エラー: {err}")
                    self._on_finished(False, "", "", "", "")
                else:
                    self._append_log(str(msg))
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _on_finished(
        self,
        ok: bool,
        midi_path: str,
        notes: str,
        pedals: str,
        elapsed: str,
    ) -> None:
        self._set_busy(False)
        if ok:
            self.status_var.set(f"完了 ({elapsed}s) — notes={notes}, pedals={pedals}")
            self.open_btn.configure(state="normal")
            messagebox.showinfo(
                APP_TITLE,
                f"変換が完了しました。\n\n{midi_path}\n\n"
                f"notes={notes}, pedals={pedals}, 所要 {elapsed} 秒",
            )
        else:
            self.status_var.set("エラー")
            messagebox.showerror(APP_TITLE, "変換に失敗しました。ログを確認してください。")

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _open_output_folder(self) -> None:
        midi = self.midi_var.get().strip()
        if not midi:
            return
        self._open_path(str(Path(midi).resolve().parent))

    def _open_manual(self) -> None:
        path = manual_pdf_path()
        if not path.is_file():
            messagebox.showwarning(
                APP_TITLE,
                "説明書 PDF が見つかりません。\n"
                "ビルド時に scripts\\build_manual_pdf.py を実行するか、\n"
                "docs\\manual.md を参照してください。\n\n"
                f"探したパス: {path}",
            )
            # Fallback: open markdown if present
            md = path.with_suffix(".md")
            if md.is_file():
                self._open_path(str(md))
            return
        self._open_path(str(path))

    def _open_path(self, path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def _on_close(self) -> None:
        self._player.stop()
        self.destroy()


def main() -> None:
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
