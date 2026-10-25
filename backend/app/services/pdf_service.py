from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:
    import fitz


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


def iter_pdf_pages(pdf_path: Path) -> Iterator[dict]:
    import fitz

    has_text = False
    with fitz.open(pdf_path) as document:
        if document.is_encrypted:
            raise ValueError("This PDF is password-protected and cannot be processed.")
        for page in document:
            paragraphs = _extract_page_paragraphs(page)
            if paragraphs:
                has_text = True
                yield {"paragraphs": paragraphs}

    if not has_text:
        raise ValueError(
            "No selectable text was found in this PDF. It may be scanned; OCR is required."
        )


def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    return list(iter_pdf_pages(pdf_path))


def extract_pdf_text(pdf_path: Path) -> list[str]:
    return [
        "\n\n".join(paragraph["text"] for paragraph in page["paragraphs"])
        for page in extract_pdf_pages(pdf_path)
    ]


def _iter_long_paragraph(paragraph: str, limit: int) -> Iterator[str]:
    current = ""

    for match in re.finditer(r"\S+", paragraph):
        word = match.group()
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                yield current
            while len(word) > limit:
                yield word[:limit]
                word = word[limit:]
            current = word

    if current:
        yield current


def iter_chunks(pages: Iterable[str | dict], limit: int) -> Iterator[dict]:
    current_parts: list[str] = []
    current_styles: list[dict] = []
    current_length = 0
    chunk_page_start = 1
    chunk_page_end = 1
    chunk_index = 0

    for page_number, page in enumerate(pages, start=1):
        if isinstance(page, dict):
            page_number = page.get("page_number", page_number)
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
            for piece in _iter_long_paragraph(paragraph, limit):
                required = len(piece) + 2
                if current_parts and current_length + required > limit:
                    yield {
                        "index": chunk_index,
                        "page_start": chunk_page_start,
                        "page_end": chunk_page_end,
                        "text": "\n\n".join(current_parts),
                        "paragraph_styles": current_styles,
                    }
                    chunk_index += 1
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
        yield {
            "index": chunk_index,
            "page_start": chunk_page_start,
            "page_end": chunk_page_end,
            "text": "\n\n".join(current_parts),
            "paragraph_styles": current_styles,
        }


def split_into_chunks(pages: Iterable[str | dict], limit: int) -> list[dict]:
    return list(iter_chunks(pages, limit))


def create_translated_pdf(
    translated_chunks: Iterable[str],
    output_path: Path,
    title: str,
    paragraph_styles: Iterable[list[dict]] | None = None,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = canvas.Canvas(str(output_path), pagesize=A4)
    document.setTitle(title)
    document.setAuthor("Libris")
    page_width, page_height = A4
    left_margin = right_margin = 22 * mm
    top_margin = 22 * mm
    bottom_margin = 20 * mm
    footer_height = 12 * mm
    text_width = page_width - left_margin - right_margin
    cursor = page_height - top_margin
    page_number = 1

    def draw_footer() -> None:
        document.saveState()
        document.setFont("Helvetica", 8)
        document.setFillColor(colors.HexColor("#777777"))
        document.drawCentredString(page_width / 2, 12 * mm, str(page_number))
        document.restoreState()

    def new_page() -> None:
        nonlocal cursor, page_number
        draw_footer()
        document.showPage()
        page_number += 1
        cursor = page_height - top_margin

    def draw_wrapped(text: str, font: str, size: float, leading: float) -> None:
        nonlocal cursor
        for raw_line in text.splitlines() or [""]:
            lines = simpleSplit(raw_line, font, size, text_width) or [""]
            for line in lines:
                if cursor - leading < bottom_margin + footer_height:
                    new_page()
                document.setFont(font, size)
                document.drawString(left_margin, cursor - size, line)
                cursor -= leading

    document.setFillColor(colors.HexColor("#34264f"))
    draw_wrapped(title, "Helvetica-Bold", 18, 23)
    cursor -= 4 * mm
    style_iterator = iter(paragraph_styles) if paragraph_styles is not None else iter(())

    for chunk in translated_chunks:
        styles_for_chunk = next(style_iterator, [])
        for paragraph_index, paragraph in enumerate(re.split(r"\n\s*\n", chunk.strip())):
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
            document.setFillColor(colors.black)
            if paragraph_style.get("heading"):
                cursor -= 10
                font = "Helvetica-Bold"
                size = 13
                leading = 17
            else:
                font = (
                    "Helvetica-BoldOblique"
                    if paragraph_style.get("bold") and paragraph_style.get("italic")
                    else "Helvetica-Bold"
                    if paragraph_style.get("bold")
                    else "Helvetica-Oblique"
                    if paragraph_style.get("italic")
                    else "Helvetica"
                )
                size = 10.5
                leading = 15
            draw_wrapped(paragraph, font, size, leading)
            cursor -= 7 if paragraph_style.get("heading") else 9
        cursor -= 4 * mm

    draw_footer()
    document.save()


def remove_job_directory(job_dir: Path) -> None:
    shutil.rmtree(job_dir)
