# Piano Transcription GUI

[ByteDance Piano Transcription](https://github.com/bytedance/piano_transcription) の推論パッケージ
[`piano_transcription_inference`](https://github.com/qiuqiangkong/piano_transcription_inference)
を使い、ローカルのピアノ音源を MIDI に変換する GUI アプリです。

## 機能

- wav / mp3 / flac / ogg / m4a など一般的なオーディオ形式に対応
- 変換パラメータを GUI で設定
  - デバイス (`auto` / `cuda` / `cpu`)
  - セグメント長（秒）
  - Onset / Offset / Frame / Pedal offset 閾値
  - バッチサイズ
  - モデルチェックポイントパス
- 初回起動時に事前学習モデル (~165 MB) を自動ダウンロード（Windows でも動作）
- バックグラウンド実行とログ表示

## 必要環境

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/)（mp3 等の読み込みに必要。PATH に通す）
- （任意）CUDA 対応 GPU + PyTorch CUDA ビルド

## セットアップ

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

## 参考

- Training / paper repo: https://github.com/bytedance/piano_transcription
- Inference package: https://github.com/qiuqiangkong/piano_transcription_inference
- Paper: Kong et al., "High-resolution Piano Transcription with Pedals by Regressing Onsets and Offsets Times"
