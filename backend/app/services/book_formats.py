import codecs
import html
import posixpath
import shutil
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from app.services.pdf_service import iter_pdf_pages

SUPPORTED_FORMATS = {"pdf", "epub", "mobi"}
MIME_TYPES = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
}


def find_calibre_converter() -> str | None:
    converter = shutil.which("ebook-convert")
    if converter:
        return converter
    for candidate in (
        Path("C:/Program Files/Calibre2/ebook-convert.exe"),
        Path("C:/Program Files/Calibre/ebook-convert.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _convert_with_calibre(source: Path, destination: Path) -> None:
    converter = find_calibre_converter()
    if converter is None:
        raise RuntimeError(
            "MOBI conversion requires Calibre. Install Calibre and restart the backend."
        )

    result = subprocess.run(
        [converter, str(source), str(destination)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"Calibre could not convert the book: {detail or 'unknown conversion error'}"
        )


class _EpubTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[dict] = []
        self._parts: list[str] = []
        self._bold_depth = 0
        self._italic_depth = 0
        self._has_bold = False
        self._has_italic = False
        self._heading = False

    def _flush(self) -> None:
        text = "".join(self._parts).strip()
        self._parts.clear()
        if not text:
            self._has_bold = False
            self._has_italic = False
            self._heading = False
            return
        characters = [character for character in text if character.isalpha()]
        self.paragraphs.append(
            {
                "text": text,
                "bold": self._has_bold or self._bold_depth > 0,
                "italic": self._has_italic or self._italic_depth > 0,
                "uppercase": bool(characters)
                and all(character.isupper() for character in characters),
                "heading": self._heading,
            }
        )
        self._has_bold = False
        self._has_italic = False
        self._heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in self._BLOCK_TAGS:
            self._flush()
        if normalized in {"b", "strong"}:
            self._has_bold = True
            self._bold_depth += 1
        elif normalized in {"i", "em"}:
            self._has_italic = True
            self._italic_depth += 1
        elif normalized in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = True
            self._bold_depth += 1
        if normalized == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self._BLOCK_TAGS:
            self._flush()
        if normalized in {"b", "strong", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._bold_depth = max(0, self._bold_depth - 1)
        elif normalized in {"i", "em"}:
            self._italic_depth = max(0, self._italic_depth - 1)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data)
        elif self._parts and self._parts[-1] != " ":
            self._parts.append(" ")


def _resolve_epub_path(base: PurePosixPath, href: str) -> str:
    href_path = unquote(urlsplit(href).path)
    resolved = posixpath.normpath(posixpath.join(base.as_posix(), href_path))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise ValueError("The EPUB contains an invalid content path.")
    return resolved


def iter_epub_pages(epub_path: Path) -> Iterator[dict]:
    try:
        with zipfile.ZipFile(epub_path) as archive:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise ValueError("The EPUB is missing its package document.")

            package_path = PurePosixPath(rootfile.attrib["full-path"])
            package_root = ElementTree.fromstring(archive.read(str(package_path)))
            manifest = {
                item.attrib["id"]: item.attrib["href"]
                for item in package_root.findall(".//{*}manifest/{*}item")
                if item.get("id") and item.get("href")
            }
            spine = [
                item.attrib["idref"]
                for item in package_root.findall(".//{*}spine/{*}itemref")
                if item.get("idref") in manifest
            ]
            base = package_path.parent
            has_text = False
            text_page_number = 0
            for item_id in spine:
                content_path = _resolve_epub_path(base, manifest[item_id])
                parser = _EpubTextParser()
                decoder = codecs.getincrementaldecoder("utf-8")()
                page_number = None
                with archive.open(content_path) as chapter:
                    while block := chapter.read(64 * 1024):
                        parser.feed(decoder.decode(block))
                        if parser.paragraphs:
                            has_text = True
                            if page_number is None:
                                text_page_number += 1
                                page_number = text_page_number
                            paragraphs = parser.paragraphs
                            parser.paragraphs = []
                            yield {
                                "page_number": page_number,
                                "paragraphs": paragraphs,
                            }
                    parser.feed(decoder.decode(b"", final=True))
                parser.close()
                parser._flush()
                if parser.paragraphs:
                    has_text = True
                    if page_number is None:
                        text_page_number += 1
                        page_number = text_page_number
                    yield {
                        "page_number": page_number,
                        "paragraphs": parser.paragraphs,
                    }
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise ValueError("The EPUB file is invalid or could not be read.") from error

    if not has_text:
        raise ValueError("No readable book text was found in this EPUB.")


def extract_epub_pages(epub_path: Path) -> list[dict]:
    return list(iter_epub_pages(epub_path))


def extract_book_pages(
    source_path: Path,
    input_format: str,
    job_dir: Path,
) -> Iterator[dict]:
    if input_format == "pdf":
        yield from iter_pdf_pages(source_path)
        return
    if input_format == "epub":
        yield from iter_epub_pages(source_path)
        return
    if input_format == "mobi":
        converted_epub = job_dir / "source-converted.epub"
        _convert_with_calibre(source_path, converted_epub)
        yield from iter_epub_pages(converted_epub)
        return
    raise ValueError(f"Unsupported input format: {input_format}")


def create_translated_epub(
    translated_chunks: Iterable[str],
    output_path: Path,
    title: str,
    paragraph_styles: Iterable[list[dict]] | None = None,
) -> None:
    safe_title = html.escape(title)
    package = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:identifier id=\"book-id\">urn:uuid:translated-book</dc:identifier>"
        f"<dc:title>{safe_title}</dc:title><dc:language>und</dc:language>"
        "</metadata><manifest>"
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        "</manifest><spine><itemref idref=\"chapter\"/></spine></package>"
    )
    navigation = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head>'
        f"<body><nav epub:type=\"toc\"><h1>Contents</h1><ol><li>"
        f"<a href=\"chapter.xhtml\">{safe_title}</a></li></ol></nav></body></html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/content.opf", package)
        with archive.open("OEBPS/chapter.xhtml", "w") as chapter:
            chapter.write(
                (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml" '
                    'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>'
                    f"{safe_title}</title><style>body{{font-family:serif;line-height:1.55;margin:5%}}"
                    "h1{text-align:center;margin:0 0 2em}"
                    "h2{font-size:1.25em;margin-top:1.5em}"
                    "p{margin:.7em 0;text-indent:1.2em}</style></head><body>"
                    f"<h1>{safe_title}</h1>"
                ).encode("utf-8")
            )
            style_iterator = iter(paragraph_styles) if paragraph_styles is not None else iter(())
            for text in translated_chunks:
                styles_for_chunk = next(style_iterator, [])
                for paragraph_index, paragraph in enumerate(text.split("\n\n")):
                    paragraph = paragraph.strip()
                    if not paragraph:
                        continue
                    style = (
                        styles_for_chunk[paragraph_index]
                        if paragraph_index < len(styles_for_chunk)
                        else {}
                    )
                    tag = "h2" if style.get("heading") else "p"
                    content = html.escape(paragraph).replace("\n", "<br/>")
                    if style.get("uppercase"):
                        content = content.upper()
                    if style.get("bold"):
                        content = f"<strong>{content}</strong>"
                    if style.get("italic"):
                        content = f"<em>{content}</em>"
                    chapter.write(f"<{tag}>{content}</{tag}>".encode("utf-8"))
            chapter.write(b"</body></html>")
        archive.writestr("OEBPS/nav.xhtml", navigation)


def convert_epub_to_mobi(epub_path: Path, mobi_path: Path) -> None:
    _convert_with_calibre(epub_path, mobi_path)
