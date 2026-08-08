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

from transcriber import (
    AUDIO_EXTENSIONS,
    TranscriptionParams,
    default_checkpoint_path,
    transcribe_file,
)
from version import APP_DISPLAY_NAME, __version__

APP_TITLE = f"{APP_DISPLAY_NAME} v{__version__}"
SUPPORTED_GLOBS = " ".join(f"*{ext}" for ext in AUDIO_EXTENSIONS)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("780x720")
        self.minsize(680, 640)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._busy = False

        self._build_ui()
        self.after(100, self._drain_log_queue)

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

        subtitle = ctk.CTkLabel(
            self,
            text="ByteDance Piano Transcription (piano_transcription_inference)  |  Apache-2.0",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        # --- Files ---
        files = ctk.CTkFrame(self)
        files.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        files.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(files, text="入力オーディオ").grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w"
        )
        self.audio_var = ctk.StringVar()
        ctk.CTkEntry(files, textvariable=self.audio_var).grid(
            row=0, column=1, padx=6, pady=(12, 6), sticky="ew"
        )
        ctk.CTkButton(files, text="参照…", width=90, command=self._pick_audio).grid(
            row=0, column=2, padx=(6, 12), pady=(12, 6)
        )

        ctk.CTkLabel(files, text="出力 MIDI").grid(
            row=1, column=0, padx=12, pady=(6, 12), sticky="w"
        )
        self.midi_var = ctk.StringVar()
        ctk.CTkEntry(files, textvariable=self.midi_var).grid(
            row=1, column=1, padx=6, pady=(6, 12), sticky="ew"
        )
        ctk.CTkButton(files, text="参照…", width=90, command=self._pick_midi).grid(
            row=1, column=2, padx=(6, 12), pady=(6, 12)
        )

        # --- Parameters ---
        params = ctk.CTkFrame(self)
        params.grid(row=3, column=0, padx=20, pady=6, sticky="nsew")
        params.grid_columnconfigure((1, 3), weight=1)
        params.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(
            params, text="変換パラメータ", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, columnspan=4, padx=12, pady=(12, 8), sticky="w")

        # Device
        ctk.CTkLabel(params, text="デバイス").grid(
            row=1, column=0, padx=12, pady=6, sticky="w"
        )
        self.device_var = ctk.StringVar(value="auto")
        ctk.CTkOptionMenu(
            params,
            variable=self.device_var,
            values=["auto", "cuda", "cpu"],
            width=140,
        ).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(params, text="バッチサイズ").grid(
            row=1, column=2, padx=12, pady=6, sticky="w"
        )
        self.batch_var = ctk.StringVar(value="1")
        ctk.CTkEntry(params, textvariable=self.batch_var, width=80).grid(
            row=1, column=3, padx=6, pady=6, sticky="w"
        )

        # Segment seconds
        ctk.CTkLabel(params, text="セグメント長 (秒)").grid(
            row=2, column=0, padx=12, pady=6, sticky="w"
        )
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

        # Thresholds
        self.onset_var = ctk.DoubleVar(value=0.3)
        self.offset_var = ctk.DoubleVar(value=0.3)
        self.frame_var = ctk.DoubleVar(value=0.1)
        self.pedal_var = ctk.DoubleVar(value=0.2)
        self._threshold_labels: dict[str, ctk.CTkLabel] = {}

        self._add_threshold_row(params, 3, "Onset 閾値", self.onset_var, "onset")
        self._add_threshold_row(params, 4, "Offset 閾値", self.offset_var, "offset")
        self._add_threshold_row(params, 5, "Frame 閾値", self.frame_var, "frame")
        self._add_threshold_row(params, 6, "Pedal offset 閾値", self.pedal_var, "pedal")

        # Checkpoint
        ctk.CTkLabel(params, text="チェックポイント").grid(
            row=7, column=0, padx=12, pady=6, sticky="w"
        )
        self.checkpoint_var = ctk.StringVar(value=str(default_checkpoint_path()))
        ctk.CTkEntry(params, textvariable=self.checkpoint_var).grid(
            row=7, column=1, columnspan=2, padx=6, pady=6, sticky="ew"
        )
        ctk.CTkButton(params, text="参照…", width=90, command=self._pick_checkpoint).grid(
            row=7, column=3, padx=6, pady=6, sticky="w"
        )

        hint = ctk.CTkLabel(
            params,
            text=(
                "初回実行時は事前学習モデル (~165 MB) を自動ダウンロードします。"
                " 閾値を上げると検出が厳しく、下げると敏感になります。"
            ),
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
            wraplength=700,
            justify="left",
        )
        hint.grid(row=8, column=0, columnspan=4, padx=12, pady=(4, 12), sticky="nw")

        # --- Actions / log ---
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=4, column=0, padx=20, pady=(6, 16), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(bottom, fg_color="transparent")
        actions.grid(row=0, column=0, sticky="ew")
        actions.grid_columnconfigure(2, weight=1)

        self.run_btn = ctk.CTkButton(
            actions,
            text="MIDI に変換",
            width=140,
            height=36,
            command=self._start_transcription,
        )
        self.run_btn.grid(row=0, column=0, padx=(0, 8), pady=4)

        self.open_btn = ctk.CTkButton(
            actions,
            text="出力フォルダを開く",
            width=140,
            height=36,
            fg_color=("gray70", "gray35"),
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_btn.grid(row=0, column=1, padx=8, pady=4)

        self.status_var = ctk.StringVar(value="待機中")
        ctk.CTkLabel(actions, textvariable=self.status_var).grid(
            row=0, column=2, padx=12, pady=4, sticky="e"
        )

        self.log_box = ctk.CTkTextbox(bottom, height=160, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.log_box.insert("end", "ログ出力\n")
        self.log_box.configure(state="disabled")

    def _add_threshold_row(
        self,
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: ctk.DoubleVar,
        key: str,
    ) -> None:
        ctk.CTkLabel(parent, text=label).grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        slider = ctk.CTkSlider(
            parent,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=variable,
            command=lambda v, k=key: self._on_threshold_slide(k, v),
        )
        slider.grid(row=row, column=1, columnspan=2, padx=6, pady=6, sticky="ew")
        value_label = ctk.CTkLabel(parent, text=f"{variable.get():.2f}")
        value_label.grid(row=row, column=3, padx=6, pady=6, sticky="w")
        self._threshold_labels[key] = value_label

    def _on_segment_slide(self, value: float) -> None:
        self.segment_label.configure(text=f"{float(value):.1f}")

    def _on_threshold_slide(self, key: str, value: float) -> None:
        label = self._threshold_labels.get(key)
        if label is not None:
            label.configure(text=f"{float(value):.2f}")

    # --------------------------------------------------------------- pickers
    def _pick_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="ピアノ音源を選択",
            filetypes=[
                ("Audio", SUPPORTED_GLOBS),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.audio_var.set(path)
        if not self.midi_var.get().strip():
            self.midi_var.set(str(Path(path).with_suffix(".mid")))

    def _pick_midi(self) -> None:
        initial = self.midi_var.get().strip() or self.audio_var.get().strip()
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
            self.midi_var.set(path)

    def _pick_checkpoint(self) -> None:
        path = filedialog.askopenfilename(
            title="モデルチェックポイントを選択",
            filetypes=[("PyTorch checkpoint", "*.pth *.pt"), ("All files", "*.*")],
        )
        if path:
            self.checkpoint_var.set(path)

    # ----------------------------------------------------------------- run
    def _collect_params(self) -> TranscriptionParams:
        try:
            batch_size = int(self.batch_var.get().strip() or "1")
        except ValueError as exc:
            raise ValueError("バッチサイズは整数で指定してください。") from exc
        if batch_size < 1:
            raise ValueError("バッチサイズは 1 以上にしてください。")

        checkpoint = self.checkpoint_var.get().strip() or None
        return TranscriptionParams(
            device=self.device_var.get(),
            checkpoint_path=checkpoint,
            segment_seconds=float(self.segment_var.get()),
            onset_threshold=float(self.onset_var.get()),
            offset_threshold=float(self.offset_var.get()),
            frame_threshold=float(self.frame_var.get()),
            pedal_offset_threshold=float(self.pedal_var.get()),
            batch_size=batch_size,
        )

    def _start_transcription(self) -> None:
        if self._busy:
            return

        audio = self.audio_var.get().strip()
        midi = self.midi_var.get().strip()
        if not audio:
            messagebox.showwarning(APP_TITLE, "入力オーディオを選択してください。")
            return
        if not os.path.isfile(audio):
            messagebox.showerror(APP_TITLE, f"入力ファイルが見つかりません:\n{audio}")
            return
        if not midi:
            midi = str(Path(audio).with_suffix(".mid"))
            self.midi_var.set(midi)

        try:
            params = self._collect_params()
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return

        self._busy = True
        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.status_var.set("変換中…")
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

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                if msg.startswith("SUCCESS\t"):
                    parts = msg.split("\t")
                    midi_path = parts[1]
                    notes = parts[2]
                    pedals = parts[3]
                    elapsed = parts[4]
                    self._on_finished(True, midi_path, notes, pedals, elapsed)
                elif msg.startswith("ERROR\t"):
                    err = msg.split("\t", 1)[1]
                    self._append_log(f"エラー: {err}")
                    self._on_finished(False, "", "", "", "")
                else:
                    self._append_log(msg)
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
        self._busy = False
        self.run_btn.configure(state="normal")
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
        folder = str(Path(midi).resolve().parent)
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)


def main() -> None:
    # Ensure local imports work when launched as `python main.py`
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
