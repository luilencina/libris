import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile
from xml.etree import ElementTree

from app.services.book_formats import (
    _convert_with_calibre,
    _resolve_epub_path,
    create_translated_epub,
    extract_epub_pages,
)


class BookFormatTests(unittest.TestCase):
    def _create_epub(self, path: Path, href: str = "../Text/chapter.xhtml") -> None:
        container = (
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
            'xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf"/>'
            "</rootfiles></container>"
        )
        package = (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
            f'<manifest><item id="chapter" href="{href}"/></manifest>'
            '<spine><itemref idref="chapter"/></spine></package>'
        )
        with ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("OPS/package.opf", package)
            archive.writestr(
                "Text/chapter.xhtml",
                "<html><body><h2>CHAPTER ONE</h2><p><strong>Bold</strong> "
                "<em>italic</em> and regular.</p></body></html>",
            )

    def test_extracts_epub_spine_and_paragraph_styles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.epub"
            self._create_epub(source)

            pages = extract_epub_pages(source)

        self.assertEqual(len(pages), 1)
        self.assertEqual(
            [paragraph["text"] for paragraph in pages[0]["paragraphs"]],
            ["CHAPTER ONE", "Bold italic and regular."],
        )
        heading, paragraph = pages[0]["paragraphs"]
        self.assertTrue(heading["heading"])
        self.assertTrue(heading["bold"])
        self.assertTrue(heading["uppercase"])
        self.assertTrue(paragraph["bold"])
        self.assertTrue(paragraph["italic"])

    def test_generates_epub_with_requested_styles_and_uncompressed_mimetype(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "translated.epub"
            create_translated_epub(
                ["CHAPTER ONE\n\nTranslated emphasis."],
                output,
                "Translated book",
                [[{"heading": True}, {"bold": True, "italic": True}]],
            )

            with ZipFile(output) as archive:
                self.assertEqual(archive.getinfo("mimetype").compress_type, ZIP_STORED)
                document = archive.read("OEBPS/chapter.xhtml").decode("utf-8")
                root = ElementTree.fromstring(document)

        self.assertIn("<h2>CHAPTER ONE</h2>", document)
        self.assertIn("<em><strong>Translated emphasis.</strong></em>", document)
        self.assertIn("Translated book", "".join(root.itertext()))

    def test_rejects_epub_content_path_outside_archive_root(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_epub_path(PurePosixPath("OPS"), "../../../outside.xhtml")

    def test_mobi_conversion_reports_missing_calibre(self) -> None:
        with patch("app.services.book_formats.find_calibre_converter", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "requires Calibre"):
                _convert_with_calibre(Path("input.epub"), Path("output.mobi"))


if __name__ == "__main__":
    unittest.main()
