# Piano Transcription GUI

[ByteDance Piano Transcription](https://github.com/bytedance/piano_transcription) の推論パッケージ
[`piano_transcription_inference`](https://github.com/qiuqiangkong/piano_transcription_inference)
を使い、ローカルのピアノ音源を MIDI に変換する Windows 向け GUI アプリです。

## License

本リポジトリは **Apache License 2.0** です（[LICENSE](LICENSE)）。

選定理由:

- 上流の [ByteDance piano_transcription](https://github.com/bytedance/piano_transcription) / `piano_transcription_inference` と同じライセンスで揃えやすい
- 特許条項があり、ML ツールの再配布に向きやすい
- Apache の慣習どおり第三者表記を [NOTICE](NOTICE) にまとめられる

第三者・同梱物の扱いは [NOTICE](NOTICE) を参照してください（上流モデル、Zenodo チェックポイント、任意同梱の ffmpeg など）。  
ffmpeg を同梱する場合は **別実行ファイルとして同梱**しており、アプリ本体に静的リンクはしていません。

## 機能

- wav / mp3 / flac / ogg / m4a など一般的なオーディオ形式に対応
- 変換パラメータを GUI で設定（ラベルにツールチップあり）
  - デバイス (`auto` / `cuda` / `cpu`)
  - セグメント長（秒）
  - Onset / Offset / Frame / Pedal offset 閾値
  - バッチサイズ
  - モデルチェックポイントパス
- **音源から自動設定**（音量・オンセット密度・ノイズっぽさから推定）
- **短い区間のプレビュー変換・再生**
- 説明書 PDF（`docs/manual.md` → ビルド時に `docs/manual.pdf`）
- 初回実行時に事前学習モデル (~165 MB) を自動ダウンロード
- Windows 向け exe（onedir）ビルド

## 既知の互換性修正

上流 `piano_transcription_inference.load_audio` は librosa 0.10+ で
`librosa.core.audio` 参照により失敗します。本アプリは `audio_io.py` の
`librosa.load` ベース実装で回避しています。

## 必要環境

### Python から実行する場合

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/)（mp3 等。PATH に通す）
- （任意）CUDA 対応 GPU + PyTorch CUDA ビルド

### 配布 exe を使う場合

- Windows 10/11 x64
- 初回起動時にモデル自動ダウンロードのためインターネット接続が必要
- リリース zip に ffmpeg を同梱（ビルド時オプション）

## セットアップ（開発）

```powershell
cd D:\work\piano-transcription-gui
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# CPU の例（社内プロキシ等で SSL エラーが出る場合は trusted-host を付与）
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# GPU (CUDA) を使う場合は、先に公式手順で torch を入れ直すのが確実です
# https://pytorch.org/get-started/locally/
```

## 起動

```powershell
python main.py
# または
.\run.bat
```

## Windows exe のビルド

PyInstaller で **onedir** 配布物を作成します（torch 同梱のため onefile より安定）。

```powershell
# 依存インストール + ffmpeg 同梱 + dist 出力
.\build.bat

# ffmpeg 同梱をスキップする場合
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -SkipFfmpeg
```

成果物:

- `dist\PianoTranscriptionGUI\PianoTranscriptionGUI.exe`
- `dist\PianoTranscriptionGUI-windows-x64-vX.Y.Z.zip`

> 配布ビルドは CPU 版 PyTorch を前提にしています。CUDA を使う場合はソースから実行し、CUDA 対応 torch を入れてください。

## 使い方

1. 「入力オーディオ」でピアノ録音ファイルを選択
2. 必要なら出力 MIDI パスやパラメータを調整
3. 「MIDI に変換」をクリック
4. 完了後、同じフォルダに `.mid` が書き出されます

## パラメータの目安

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| デバイス | auto | CUDA があれば GPU、なければ CPU |
| セグメント長 | 10 秒 | 推論時の分割長。長いとメモリ使用量が増える |
| Onset 閾値 | 0.3 | ノート開始検出の厳しさ |
| Offset 閾値 | 0.3 | ノート終了検出の厳しさ |
| Frame 閾値 | 0.1 | フレーム単位のノート有無 |
| Pedal offset 閾値 | 0.2 | サスティンペダル終了検出 |
| バッチサイズ | 1 | GPU メモリに余裕があれば増やせる |

論文・公式実装では推論時の各閾値は概ね 0.3 前後が推奨されています。

## GitHub 公開とリリース

### 前提

- GitHub CLI (`gh`) が使えること（本環境では `C:\Program Files\GitHub CLI\gh.exe` / ログイン済み）
- 作業ツリーがクリーンであること

### 1. リポジトリ作成（初回のみ）

```powershell
cd D:\work\piano-transcription-gui
& "C:\Program Files\GitHub CLI\gh.exe" repo create piano-transcription-gui --public --source=. --remote=origin --push
```

PATH に `gh` が入っているシェルでは `gh repo create ...` でも同じです。

### 2. リリース（推奨フロー）

```powershell
# version.py のバージョンでタグを切り、push → Actions が zip を Release に添付
.\release.bat

# バージョンを上げてリリース
powershell -ExecutionPolicy Bypass -File .\scripts\release.ps1 -Version 0.1.1
```

内部では次を行います。

1. `version.py` を必要なら更新して commit
2. 注釈付きタグ `vX.Y.Z` を作成して push
3. `.github/workflows/build-windows.yml` が Windows ビルドを実行
4. GitHub Release に zip を添付（LICENSE / NOTICE もパッケージ内に同梱）

手動でタグだけ切る場合:

```powershell
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

### 3. Actions の確認

```powershell
gh run list --workflow "Build Windows Release"
gh release list
```

## 参考

- Training / paper repo: https://github.com/bytedance/piano_transcription
- Inference package: https://github.com/qiuqiangkong/piano_transcription_inference
- Paper: Kong et al., "High-resolution Piano Transcription with Pedals by Regressing Onsets and Offsets Times"
