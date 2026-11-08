"""Render a project Markdown doc (headings, paragraphs, bullets, tables, code) to PDF.

Usage (repo root):  make script-pdf
   or:  cd backend && uv run python ../tools/docs/md_to_pdf.py ../docs/DEMO_SCRIPT.md ../docs/DEMO_SCRIPT.pdf

Uses DejaVu Sans when available so symbols like → ≈ ≥ Ø ⚠ render (the built-in PDF fonts lack them).
"""

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/Library/Fonts"),
    Path("C:/Windows/Fonts"),
]


def register_fonts() -> tuple[str, str, str]:
    for d in FONT_DIRS:
        regular, bold, mono = (
            d / "DejaVuSans.ttf",
            d / "DejaVuSans-Bold.ttf",
            d / "DejaVuSansMono.ttf",
        )
        if regular.exists() and bold.exists() and mono.exists():
            pdfmetrics.registerFont(TTFont("Body", str(regular)))
            pdfmetrics.registerFont(TTFont("Body-Bold", str(bold)))
            pdfmetrics.registerFont(TTFont("Mono", str(mono)))
            pdfmetrics.registerFontFamily(
                "Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold"
            )
            return "Body", "Body-Bold", "Mono"
    return "Helvetica", "Helvetica-Bold", "Courier"


BODY, BOLD, MONO = register_fonts()
INK, MUTED, ACCENT, RULE = (
    colors.HexColor("#0f172a"),
    colors.HexColor("#475569"),
    colors.HexColor("#b91c1c"),
    colors.HexColor("#cbd5e1"),
)

STYLES = {
    "h1": ParagraphStyle(
        "h1", keepWithNext=1, fontName=BOLD, fontSize=20, leading=24, textColor=INK, spaceAfter=6
    ),
    "h2": ParagraphStyle(
        "h2", fontName=BOLD, fontSize=14, leading=18, textColor=INK, spaceBefore=10, spaceAfter=6
    ),
    "h3": ParagraphStyle(
        "h3", fontName=BOLD, fontSize=11.5, leading=15, textColor=INK, spaceBefore=6, spaceAfter=4
    ),
    "p": ParagraphStyle(
        "p",
        fontName=BODY,
        fontSize=9.5,
        leading=13.5,
        textColor=INK,
        spaceAfter=5,
        alignment=TA_LEFT,
    ),
    "cell": ParagraphStyle("cell", fontName=BODY, fontSize=8.3, leading=10.8, textColor=INK),
    "head": ParagraphStyle(
        "head", fontName=BOLD, fontSize=8.3, leading=10.8, textColor=colors.white
    ),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=8.2, leading=10.5, textColor=INK),
}


def inline(text: str) -> str:
    """Markdown inline -> ReportLab mini-HTML (escape first, then bold / italic / code)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", rf'<font face="{MONO}" color="#7c2d12">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", text)
    return text


def split_row(line: str) -> list[str]:
    line = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", line)
    return [c.strip().replace("\\|", "|") for c in cells]


def table(rows: list[list[str]], width: float) -> Table:
    n = len(rows[0])
    cells = [[r[i] if i < len(r) else "" for i in range(n)] for r in rows]
    # Minimum: the longest unbreakable word; the rest of the width is shared by text length.
    min_w = [
        max(pdfmetrics.stringWidth(w, BOLD, 8.3) for r in cells for w in (r[i].split() or [""]))
        + 10
        for i in range(n)
    ]
    weights = [min(max(max(len(r[i]) for r in cells), 6), 90) for i in range(n)]
    spare = max(width - sum(min_w), 0)
    col_widths = [m + spare * w / sum(weights) for m, w in zip(min_w, weights, strict=True)]
    if sum(col_widths) > width:
        col_widths = [c * width / sum(col_widths) for c in col_widths]
    data = [[Paragraph(inline(c), STYLES["head"]) for c in rows[0]]]
    data += [
        [Paragraph(inline(r[i]) if i < len(r) else "", STYLES["cell"]) for i in range(n)]
        for r in rows[1:]
    ]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def code_block(lines: list[str], width: float) -> Table:
    pre = Preformatted("\n".join(lines), STYLES["code"])
    t = Table([[pre]], colWidths=[width])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def build(md: str, width: float) -> list:
    story: list = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            story.append(Paragraph(inline(" ".join(para)), STYLES["p"]))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            story += [code_block(block, width), Spacer(1, 6)]
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.fullmatch(r"\|?[\s:|-]+\|?", lines[i].strip()):
                    rows.append(split_row(lines[i]))
                i += 1
            story += [table(rows, width), Spacer(1, 8)]
            continue
        elif s.startswith("# "):
            flush()
            story.append(Paragraph(inline(s[2:]), STYLES["h1"]))
        elif s.startswith("## "):
            flush()
            story.append(CondPageBreak(60 * mm))  # never leave a section heading at a page bottom
            story.append(Paragraph(inline(s[3:]), STYLES["h2"]))
        elif s.startswith("### "):
            flush()
            story.append(CondPageBreak(35 * mm))
            story.append(Paragraph(inline(s[4:]), STYLES["h3"]))
        elif s.startswith(("- ", "* ")):
            flush()
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(
                    ListItem(Paragraph(inline(lines[i].strip()[2:]), STYLES["p"]), leftIndent=12)
                )
                i += 1
            story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=12))
            continue
        elif s == "---":
            flush()
            story.append(Spacer(1, 4))
        elif s.startswith(">"):
            flush()
            story.append(Paragraph(inline(s.lstrip("> ")), STYLES["p"]))
        elif not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return story


def main(src: str, dst: str) -> None:
    page = landscape(A4)
    margin = 14 * mm
    doc = SimpleDocTemplate(
        dst,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=13 * mm,
        bottomMargin=13 * mm,
        title="Smart CMM Quality: Round 2 demo script",
        author="Team Xyrus",
    )
    width = page[0] - 2 * margin

    def footer(canvas, doc_) -> None:
        canvas.saveState()
        canvas.setFont(BODY, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            margin,
            7 * mm,
            "Smart CMM Quality · Team Xyrus · Sakthi Hackathon 2.0 Round 2 · synthetic demo data",
        )
        canvas.drawRightString(page[0] - margin, 7 * mm, f"Page {doc_.page}")
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.2)
        canvas.line(margin, page[1] - 9 * mm, page[0] - margin, page[1] - 9 * mm)
        canvas.restoreState()

    doc.build(
        build(Path(src).read_text(encoding="utf-8"), width), onFirstPage=footer, onLaterPages=footer
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    main(
        sys.argv[1] if len(sys.argv) > 1 else str(root / "docs" / "DEMO_SCRIPT.md"),
        sys.argv[2] if len(sys.argv) > 2 else str(root / "docs" / "DEMO_SCRIPT.pdf"),
    )
