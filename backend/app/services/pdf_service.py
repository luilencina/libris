import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

import fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


def _span_is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower()


def _span_is_italic(span: dict) -> bool:
    return bool(span.get("flags", 0) & 2) or "italic" in span.get("font", "").lower()


def _extract_page_paragraphs(page: fitz.Page) -> list[dict]:
    blocks = page.get_text("dict", sort=True).get("blocks", [])
    lines_with_styles: list[dict] = []

    for block_index, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if text:
                lines_with_styles.append(
                    {
                        "text": text,
                        "bbox": line.get("bbox", (0, 0, 0, 0)),
                        "spans": spans,
                        "block_index": block_index,
                    }
                )

    if not lines_with_styles:
        return []

    heights = [
        max(1.0, line["bbox"][3] - line["bbox"][1])
        for line in lines_with_styles
    ]
    typical_height = sorted(heights)[len(heights) // 2]
    groups: list[list[dict]] = []

    for line in lines_with_styles:
        if not groups:
            groups.append([line])
            continue
        previous = groups[-1][-1]
        vertical_gap = line["bbox"][1] - previous["bbox"][3]
        if (
            line["block_index"] != previous["block_index"]
            or vertical_gap > typical_height * 0.65
        ):
            groups.append([line])
        else:
            groups[-1].append(line)

    page_font_sizes = [
        span.get("size", 10)
        for line in lines_with_styles
        for span in line["spans"]
        if span.get("text", "").strip()
    ]
    typical_font_size = sorted(page_font_sizes)[len(page_font_sizes) // 2]
    paragraphs = []

    for group in groups:
        text = " ".join(line["text"] for line in group)
        spans = [span for line in group for span in line["spans"]]
        characters = [char for char in text if char.isalpha()]
        uppercase = bool(characters) and all(char.isupper() for char in characters)
        bold = bool(spans) and sum(
            len(span.get("text", "")) for span in spans if _span_is_bold(span)
        ) >= sum(len(span.get("text", "")) for span in spans) * 0.5
        italic = bool(spans) and sum(
            len(span.get("text", "")) for span in spans if _span_is_italic(span)
        ) >= sum(len(span.get("text", "")) for span in spans) * 0.5
        font_size = max((span.get("size", 10) for span in spans), default=10)
        is_heading = (
            len(text) <= 140
            and (
                font_size >= typical_font_size * 1.18
                or (bold and len(text) <= 90)
                or uppercase
            )
        )
        paragraphs.append(
            {
                "text": text,
                "bold": bold,
                "italic": italic,
                "uppercase": uppercase,
                "heading": is_heading,
            }
        )

    return paragraphs


def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    pages: list[dict] = []
    with fitz.open(pdf_path) as document:
        if document.is_encrypted:
            raise ValueError("This PDF is password-protected and cannot be processed.")
        for page in document:
            paragraphs = _extract_page_paragraphs(page)
            if paragraphs:
                pages.append({"paragraphs": paragraphs})

    if not pages:
        raise ValueError(
            "No selectable text was found in this PDF. It may be scanned; OCR is required."
        )
    return pages


def extract_pdf_text(pdf_path: Path) -> list[str]:
    return [
        "\n\n".join(paragraph["text"] for paragraph in page["paragraphs"])
        for page in extract_pdf_pages(pdf_path)
    ]


def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
    words = paragraph.split()
    pieces: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                pieces.append(current)
            while len(word) > limit:
                pieces.append(word[:limit])
                word = word[limit:]
            current = word

    if current:
        pieces.append(current)
    return pieces


def split_into_chunks(pages: list[str] | list[dict], limit: int) -> list[dict]:
    chunks: list[dict] = []
    current_parts: list[str] = []
    current_styles: list[dict] = []
    current_length = 0
    chunk_page_start = 1
    chunk_page_end = 1

    for page_number, page in enumerate(pages, start=1):
        if isinstance(page, dict):
            source_paragraphs = page.get("paragraphs", [])
        else:
            source_paragraphs = [
                {"text": paragraph}
                for paragraph in re.split(r"\n\s*\n", page)
                if paragraph.strip()
            ]

        for source_paragraph in source_paragraphs:
            paragraph = re.sub(
                r"[ \t]+", " ", source_paragraph.get("text", "")
            ).strip()
            if not paragraph:
                continue
            for piece in _split_long_paragraph(paragraph, limit):
                required = len(piece) + 2
                if current_parts and current_length + required > limit:
                    chunks.append({
                        "index": len(chunks),
                        "page_start": chunk_page_start,
                        "page_end": chunk_page_end,
                        "text": "\n\n".join(current_parts),
                        "paragraph_styles": current_styles,
                    })
                    current_parts = []
                    current_styles = []
                    current_length = 0

                if not current_parts:
                    chunk_page_start = page_number

                current_parts.append(piece)
                current_styles.append(
                    {
                        "bold": bool(source_paragraph.get("bold")),
                        "italic": bool(source_paragraph.get("italic")),
                        "uppercase": bool(source_paragraph.get("uppercase")),
                        "heading": bool(source_paragraph.get("heading")),
                    }
                )
                current_length += required
                chunk_page_end = page_number

    if current_parts:
        chunks.append({
            "index": len(chunks),
            "page_start": chunk_page_start,
            "page_end": chunk_page_end,
            "text": "\n\n".join(current_parts),
            "paragraph_styles": current_styles,
        })

    return chunks


def create_translated_pdf(
    translated_chunks: list[str],
    output_path: Path,
    title: str,
    paragraph_styles: list[list[dict]] | None = None,
) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "BookTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=23,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#34264f"),
        spaceAfter=18,
    )
    body_style = ParagraphStyle(
        "BookBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=9,
        splitLongWords=True,
        allowWidows=0,
        allowOrphans=0,
    )
    heading_style = ParagraphStyle(
        "BookHeading",
        parent=body_style,
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        spaceBefore=10,
        spaceAfter=7,
        keepWithNext=True,
    )

    def draw_page_number(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawCentredString(A4[0] / 2, 12 * mm, str(document.page))
        canvas.restoreState()

    story = [Paragraph(escape(title), title_style), Spacer(1, 4 * mm)]

    for chunk_index, chunk in enumerate(translated_chunks):
        styles_for_chunk = (
            paragraph_styles[chunk_index]
            if paragraph_styles and chunk_index < len(paragraph_styles)
            else []
        )
        paragraphs = re.split(r"\n\s*\n", chunk.strip())
        for paragraph_index, paragraph in enumerate(paragraphs):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            paragraph_style = (
                styles_for_chunk[paragraph_index]
                if paragraph_index < len(styles_for_chunk)
                else {}
            )
            if paragraph_style.get("uppercase"):
                paragraph = paragraph.upper()
            safe_text = escape(paragraph).replace("\n", "<br/>")
            if paragraph_style.get("bold"):
                safe_text = f"<b>{safe_text}</b>"
            if paragraph_style.get("italic"):
                safe_text = f"<i>{safe_text}</i>"

            if paragraph_style.get("heading"):
                story.append(KeepTogether([Paragraph(safe_text, heading_style), Spacer(1, 2 * mm)]))
            else:
                story.append(Paragraph(safe_text, body_style))
        story.append(Spacer(1, 4 * mm))

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="Libris",
    )
    document.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number)


def remove_job_directory(job_dir: Path) -> None:
    shutil.rmtree(job_dir)
