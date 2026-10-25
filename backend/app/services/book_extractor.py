import json
import sys
from pathlib import Path
from typing import Iterator

from app.services.book_formats import extract_book_pages
from app.services.pdf_service import iter_chunks


def extract_job_chunks(
    source_path: Path,
    input_format: str,
    job_dir: Path,
    chunk_limit: int,
) -> tuple[int, int]:
    page_count = 0
    chunk_count = 0
    previous_page_number = None

    def counted_pages() -> Iterator[dict]:
        nonlocal page_count, previous_page_number
        for page in extract_book_pages(source_path, input_format, job_dir):
            current_page_number = page.get("page_number")
            if current_page_number is None or current_page_number != previous_page_number:
                page_count += 1
            if current_page_number is not None:
                previous_page_number = current_page_number
            yield page

    chunks_path = job_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as chunks_file:
        for chunk in iter_chunks(counted_pages(), chunk_limit):
            chunks_file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            chunk_count += 1

    if not chunk_count:
        raise ValueError("No readable book text was found.")

    return page_count, chunk_count


def main() -> None:
    source_path = Path(sys.argv[1])
    input_format = sys.argv[2]
    job_dir = Path(sys.argv[3])
    chunk_limit = int(sys.argv[4])
    page_count, chunk_count = extract_job_chunks(
        source_path,
        input_format,
        job_dir,
        chunk_limit,
    )
    (job_dir / "extraction.json").write_text(
        json.dumps(
            {
                "total_pages_with_text": page_count,
                "total_chunks": chunk_count,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
