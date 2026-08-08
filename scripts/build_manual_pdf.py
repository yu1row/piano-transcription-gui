"""Build a readable Japanese PDF manual from docs/manual.md."""

from __future__ import annotations

import os
import re
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "docs" / "manual.md"
PDF_PATH = ROOT / "docs" / "manual.pdf"

COLOR_TEXT = (28, 32, 38)
COLOR_MUTED = (90, 98, 110)
COLOR_ACCENT = (20, 110, 120)
COLOR_RULE = (210, 216, 222)
COLOR_TABLE_HEAD = (232, 242, 244)
COLOR_TABLE_ALT = (246, 248, 250)

# Markdown table separator: |---|---|  (hyphen must be matched explicitly)
_TABLE_SEP_RE = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_DASH_ONLY_RE = re.compile(r"^:?-{3,}:?$")


def _find_font() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        windir / "Fonts" / "YuGothM.ttc",
        windir / "Fonts" / "YuGothR.ttc",
        windir / "Fonts" / "meiryo.ttc",
        windir / "Fonts" / "Meiryo.ttc",
        windir / "Fonts" / "msgothic.ttc",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("Japanese font not found in Windows Fonts.")


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Collapse runs of spaces created by markup removal / mixed scripts
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _is_table_separator(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|") and "---" not in s:
        return False
    if _TABLE_SEP_RE.match(s):
        return True
    # Fallback: every cell is dashes
    cells = [c.strip() for c in s.strip("|").split("|")]
    return bool(cells) and all(_DASH_ONLY_RE.match(c or "") for c in cells)


class ManualPDF(FPDF):
    def __init__(self, font_path: Path) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(18, 20, 18)
        self.add_font("JP", fname=str(font_path))
        self.add_font("JP", style="B", fname=str(font_path))
        self._usable_w = self.w - self.l_margin - self.r_margin

    def _text(self, w: float, h: float, text: str, **kwargs) -> None:
        """Left-aligned multi_cell — avoid justify gaps with CJK + Latin mixed text."""
        kwargs.setdefault("align", "L")
        self.multi_cell(w, h, text, **kwargs)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("JP", size=9)
        self.set_text_color(*COLOR_MUTED)
        self.set_xy(self.l_margin, 10)
        self.cell(self._usable_w, 6, "Piano Transcription GUI 説明書", align="L")
        self.set_draw_color(*COLOR_RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, 16, self.w - self.r_margin, 16)
        self.set_y(20)
        self.set_text_color(*COLOR_TEXT)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*COLOR_RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font("JP", size=9)
        self.set_text_color(*COLOR_MUTED)
        self.cell(0, 8, f"{self.page_no()}", align="C")
        self.set_text_color(*COLOR_TEXT)

    def draw_title_block(self, title: str, subtitle: str) -> None:
        self.set_fill_color(*COLOR_ACCENT)
        self.rect(0, 0, self.w, 42, style="F")
        self.set_xy(self.l_margin, 14)
        self.set_text_color(255, 255, 255)
        self.set_font("JP", size=22)
        self._text(self._usable_w, 10, title)
        self.set_x(self.l_margin)
        self.set_font("JP", size=11)
        self._text(self._usable_w, 6, subtitle)
        self.set_text_color(*COLOR_TEXT)
        self.set_y(50)

    def h2(self, text: str) -> None:
        self.ln(3)
        y = self.get_y()
        self.set_fill_color(*COLOR_ACCENT)
        self.rect(self.l_margin, y + 1, 1.8, 7, style="F")
        self.set_xy(self.l_margin + 5, y)
        self.set_font("JP", size=14)
        self.set_text_color(*COLOR_TEXT)
        self._text(self._usable_w - 5, 8, text)
        self.ln(1)

    def h3(self, text: str) -> None:
        self.ln(1.5)
        self.set_font("JP", size=12)
        self.set_text_color(*COLOR_ACCENT)
        self.set_x(self.l_margin)
        self._text(self._usable_w, 7, text)
        self.set_text_color(*COLOR_TEXT)

    def para(self, text: str) -> None:
        self.set_font("JP", size=10.5)
        self.set_text_color(*COLOR_TEXT)
        self.set_x(self.l_margin)
        self._text(self._usable_w, 6.2, _strip_inline_md(text))
        self.ln(1.2)

    def bullet(self, text: str) -> None:
        self.set_font("JP", size=10.5)
        self.set_x(self.l_margin + 3)
        bullet_w = 5
        self.cell(bullet_w, 6.2, "-", align="L")
        self._text(self._usable_w - 3 - bullet_w, 6.2, _strip_inline_md(text))

    def numbered(self, n: int, text: str) -> None:
        self.set_font("JP", size=10.5)
        self.set_x(self.l_margin + 3)
        self.cell(7, 6.2, f"{n}.", align="L")
        self._text(self._usable_w - 10, 6.2, _strip_inline_md(text))

    def table(self, rows: list[list[str]]) -> None:
        # Drop markdown separator leftovers just in case
        filtered: list[list[str]] = []
        for row in rows:
            if row and all(_DASH_ONLY_RE.match((c or "").strip()) for c in row):
                continue
            filtered.append(row)
        rows = filtered
        if not rows:
            return

        col0 = self._usable_w * 0.28
        col1 = self._usable_w - col0
        self.ln(1)
        for idx, row in enumerate(rows):
            left = _strip_inline_md(row[0] if row else "")
            right = _strip_inline_md(" ".join(row[1:]) if len(row) > 1 else "")
            fill = (
                COLOR_TABLE_HEAD
                if idx == 0
                else (COLOR_TABLE_ALT if idx % 2 == 0 else (255, 255, 255))
            )
            self.set_fill_color(*fill)
            self.set_draw_color(*COLOR_RULE)
            self.set_line_width(0.2)
            self.set_font("JP", size=9.5)
            x = self.l_margin
            y = self.get_y()

            self.set_xy(x, y)
            self._text(col0, 5.8, left, border=0, fill=False)
            h0 = self.get_y() - y
            self.set_xy(x + col0, y)
            self._text(col1, 5.8, right, border=0, fill=False)
            h1 = self.get_y() - y
            h = max(h0, h1, 7)
            if y + h > self.page_break_trigger:
                self.add_page()
                y = self.get_y()
            self.set_xy(x, y)
            self.rect(x, y, col0, h, style="DF")
            self.rect(x + col0, y, col1, h, style="DF")
            self.set_xy(x + 1.5, y + 1)
            self._text(col0 - 3, 5.5, left)
            self.set_xy(x + col0 + 1.5, y + 1)
            self._text(col1 - 3, 5.5, right)
            self.set_y(y + h)
        self.ln(2)


def _parse_and_render(pdf: ManualPDF, markdown: str) -> None:
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    title_done = False
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue

        if line.startswith("# ") and not title_done:
            title = line[2:].strip()
            subtitle = "ローカルでピアノ音源を MIDI に変換するガイド"
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            pdf.draw_title_block(title, subtitle)
            title_done = True
            i = j if j < len(lines) else i + 1
            continue

        if line.startswith("## "):
            pdf.h2(line[3:].strip())
        elif line.startswith("### "):
            pdf.h3(line[4:].strip())
        elif _is_table_separator(line):
            pass
        elif line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                raw = lines[i].strip()
                if _is_table_separator(raw):
                    i += 1
                    continue
                cells = [c.strip() for c in raw.strip("|").split("|")]
                if cells and all(_DASH_ONLY_RE.match(c or "") for c in cells):
                    i += 1
                    continue
                rows.append(cells)
                i += 1
            pdf.table(rows)
            continue
        elif re.match(r"^\d+\.\s+", line.strip()):
            m = re.match(r"^(\d+)\.\s+(.*)$", line.strip())
            assert m
            pdf.numbered(int(m.group(1)), m.group(2))
        elif line.startswith("- "):
            pdf.bullet(line[2:].strip())
        elif line.strip() == "---":
            pdf.ln(2)
        else:
            pdf.para(line.strip())
        i += 1


def build_pdf() -> Path:
    if not MD_PATH.is_file():
        raise FileNotFoundError(MD_PATH)
    font_path = _find_font()
    md = MD_PATH.read_text(encoding="utf-8")
    pdf = ManualPDF(font_path)
    pdf.add_page()
    _parse_and_render(pdf, md)
    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_PATH))
    return PDF_PATH


if __name__ == "__main__":
    # Quick self-check for separator detection
    assert _is_table_separator("|------|------|")
    assert _is_table_separator("| --- | --- |")
    assert not _is_table_separator("| 項目 | 意味 |")
    out = build_pdf()
    print(f"Wrote {out}")
