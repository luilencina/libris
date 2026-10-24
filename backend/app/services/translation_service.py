import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import argostranslate.package
import argostranslate.translate

from google import genai
from google.genai import types

from app.core.config import (
    CHUNK_CHAR_LIMIT,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    JOBS_DIR,
)
from app.services.book_formats import (
    SUPPORTED_FORMATS,
    convert_epub_to_mobi,
    create_translated_epub,
    extract_book_pages,
    find_calibre_converter,
)
from app.services.pdf_service import (
    create_translated_pdf,
    remove_job_directory,
    split_into_chunks,
)

_ACTIVE_JOB_IDS: set[str] = set()


def register_job(job_id: str) -> None:
    _ACTIVE_JOB_IDS.add(job_id)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def get_job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid translation job ID.")
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise FileNotFoundError("Translation job was not found.")
    return job_dir


def delete_job(job_id: str) -> str:
    job_dir = get_job_dir(job_id)
    state = read_json(job_dir / "state.json")
    if not state:
        raise FileNotFoundError("Translation job state was not found.")

    if job_id in _ACTIVE_JOB_IDS:
        state["cancel_requested"] = True
        state["delete_requested"] = True
        save_state(job_dir, state)
        return "deletion_requested"

    remove_job_directory(job_dir)
    return "deleted"


def load_job(job_id: str) -> dict:
    job_dir = get_job_dir(job_id)
    state = read_json(job_dir / "state.json")
    if not state:
        raise FileNotFoundError("Translation job state was not found.")
    state.setdefault(
        "input_format",
        Path(state.get("filename", "")).suffix.lstrip(".").lower() or "pdf",
    )
    state.setdefault("output_format", "pdf")
    completed = len(list((job_dir / "translations").glob("*.txt"))) if (job_dir / "translations").exists() else 0
    state["completed_chunks"] = completed
    return state


def save_state(job_dir: Path, state: dict) -> None:
    state["updated_at"] = utc_now()
    write_json(job_dir / "state.json", state)

def get_argos_languages() -> list[dict]:
    return [
        {"code": language.code, "name": language.name}
        for language in argostranslate.translate.get_installed_languages()
    ]


def get_argos_pairs() -> list[dict]:
    languages = {
        language.code: language
        for language in argostranslate.translate.get_installed_languages()
    }
    pairs = []
    for source in languages.values():
        for translation in source.translations_from:
            target = languages.get(translation.to_lang.code)
            if target and source.code != target.code:
                pairs.append(
                    {
                        "from_code": source.code,
                        "from_name": source.name,
                        "to_code": target.code,
                        "to_name": target.name,
                    }
                )
    return sorted(
        pairs,
        key=lambda pair: (pair["from_name"].casefold(), pair["to_name"].casefold()),
    )


def get_available_argos_packages() -> list[dict]:
    argostranslate.package.update_package_index()
    installed_pairs = {
        (pair["from_code"], pair["to_code"]) for pair in get_argos_pairs()
    }
    packages = []
    for package in argostranslate.package.get_available_packages():
        if (package.from_code, package.to_code) not in installed_pairs:
            packages.append(
                {"from_code": package.from_code, "to_code": package.to_code}
            )
    return sorted(packages, key=lambda item: (item["from_code"], item["to_code"]))


def install_argos_package(source_code: str, target_code: str) -> None:
    argostranslate.package.update_package_index()
    package = next(
        (
            item
            for item in argostranslate.package.get_available_packages()
            if item.from_code == source_code and item.to_code == target_code
        ),
        None,
    )
    if package is None:
        raise ValueError(
            f"No Argos language package is available for {source_code} -> {target_code}."
        )
    package.install()


def build_prompt(text: str, source_language: str, target_language: str) -> str:
    return f"""Translate the following book excerpt from {source_language} into {target_language}.

Requirements:
- Translate the entire excerpt; do not summarize, censor, or omit content.
- Preserve the author's meaning, narrative voice, tense, tone, and literary style.
- Preserve paragraph breaks and dialogue formatting.
- Keep character names and fictional terms consistent.
- Do not add notes, explanations, headings, or commentary.
- Return only the translated text.

TEXT TO TRANSLATE:
{text}
"""


async def translate_with_gemini(text: str, source_language: str, target_language: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini is not configured. Add GEMINI_API_KEY to backend/.env and restart the backend.")

    prompt = build_prompt(text, source_language, target_language)

    def generate():
        client = genai.Client(api_key=GEMINI_API_KEY)
        return client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )

    response = await asyncio.to_thread(generate)
    translated = (getattr(response, "text", None) or "").strip()
    if not translated:
        raise RuntimeError("Gemini returned an empty translation.")
    return translated


async def translate_with_argos(
    text: str,
    source_language: str,
    target_language: str,
) -> str:
    def translate():
        installed_languages = argostranslate.translate.get_installed_languages()

        source = next(
            (
                language
                for language in installed_languages
                if language.code.casefold() == source_language.strip().casefold()
                or language.name.casefold() == source_language.strip().casefold()
            ),
            None,
        )
        target = next(
            (
                language
                for language in installed_languages
                if language.code.casefold() == target_language.strip().casefold()
                or language.name.casefold() == target_language.strip().casefold()
            ),
            None,
        )

        if source is None or target is None:
            raise RuntimeError(
                f"Argos language packages are missing for "
                f"{source_language} -> {target_language}. "
                "Install the required language packages first."
            )

        translation = source.get_translation(target)

        if translation is None:
            raise RuntimeError(
                f"No Argos translation package is installed for "
                f"{source.code} -> {target.code}."
            )

        result = translation.translate(text).strip()

        if not result:
            raise RuntimeError("Argos Translate returned an empty translation.")

        return result

    return await asyncio.to_thread(translate)

async def translate_chunk(job: dict, text: str) -> str:
    if job["engine"] == "argos":
        return await translate_with_argos(
            text,
            job["source_language"],
            job["target_language"],
        )

    if job["engine"] == "gemini":
        return await translate_with_gemini(
            text,
            job["source_language"],
            job["target_language"],
        )

    raise ValueError(f"Unsupported translation engine: {job['engine']}")

def create_job(
    upload_path: Path,
    original_filename: str,
    engine: str,
    source_language: str,
    target_language: str,
    output_format: str = "pdf",
) -> dict:
    input_format = Path(original_filename).suffix.lstrip(".").lower()
    if input_format not in SUPPORTED_FORMATS:
        raise ValueError("Only PDF, EPUB, and MOBI files are supported.")
    if output_format not in SUPPORTED_FORMATS:
        raise ValueError("Choose PDF, EPUB, or MOBI as the export format.")
    if output_format == "mobi" and not find_calibre_converter():
        raise ValueError(
            "MOBI export requires Calibre. Install Calibre and restart the backend."
        )

    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    try:
        (job_dir / "translations").mkdir()
        saved_upload = job_dir / f"source.{input_format}"
        upload_path.replace(saved_upload)

        pages = extract_book_pages(saved_upload, input_format, job_dir)
        chunks = split_into_chunks(pages, CHUNK_CHAR_LIMIT)
        write_json(job_dir / "chunks.json", chunks)
    except Exception:
        remove_job_directory(job_dir)
        raise

    state = {
        "id": job_id,
        "filename": original_filename,
        "engine": engine,
        "source_language": source_language,
        "target_language": target_language,
        "input_format": input_format,
        "output_format": output_format,
        "status": "queued",
        "total_pages_with_text": len(pages),
        "total_chunks": len(chunks),
        "completed_chunks": 0,
        "progress": 0,
        "error": None,
        "cancel_requested": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    save_state(job_dir, state)
    return state


async def _run_job(job_id: str) -> None:
    job_dir = get_job_dir(job_id)
    state = read_json(job_dir / "state.json")
    if not state:
        return

    if state.get("cancel_requested"):
        state["status"] = "cancelled"
        save_state(job_dir, state)
        return

    state["status"] = "running"
    state["error"] = None
    save_state(job_dir, state)

    chunks = read_json(job_dir / "chunks.json", [])
    translations_dir = job_dir / "translations"

    try:
        for chunk in chunks:
            state = read_json(job_dir / "state.json", state)
            if state.get("cancel_requested"):
                state["status"] = "cancelled"
                save_state(job_dir, state)
                return

            chunk_path = translations_dir / f"{chunk['index']:06d}.txt"
            if chunk_path.exists() and chunk_path.read_text(encoding="utf-8").strip():
                continue

            last_error = None
            for attempt in range(3):
                state = read_json(job_dir / "state.json", state)
                if state.get("cancel_requested"):
                    state["status"] = "cancelled"
                    save_state(job_dir, state)
                    return
                try:
                    translated = await translate_chunk(state, chunk["text"])
                    chunk_path.write_text(translated, encoding="utf-8")
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)

            if last_error is not None:
                raise RuntimeError(
                    f"Translation failed at chunk {chunk['index'] + 1}: {last_error}"
                )

            state = read_json(job_dir / "state.json", state)
            completed = len(list(translations_dir.glob("*.txt")))
            state["completed_chunks"] = completed
            state["progress"] = round(completed / max(len(chunks), 1) * 100)
            if state.get("cancel_requested"):
                state["status"] = "cancelled"
            save_state(job_dir, state)
            if state.get("cancel_requested"):
                return

        state = read_json(job_dir / "state.json", state)
        if state.get("cancel_requested"):
            state["status"] = "cancelled"
            save_state(job_dir, state)
            return

        translated_chunks = []
        for chunk in chunks:
            chunk_path = translations_dir / f"{chunk['index']:06d}.txt"
            if not chunk_path.exists():
                raise RuntimeError(f"Missing translation checkpoint for chunk {chunk['index'] + 1}.")
            translated_chunks.append(chunk_path.read_text(encoding="utf-8"))

        title = Path(state["filename"]).stem.replace("_", " ").replace("-", " ").strip()
        output_format = state.get("output_format", "pdf")
        output_path = job_dir / f"translated.{output_format}"
        paragraph_styles = [
            chunk.get("paragraph_styles", []) for chunk in chunks
        ]
        if output_format == "pdf":
            await asyncio.to_thread(
                create_translated_pdf,
                translated_chunks,
                output_path,
                title,
                paragraph_styles,
            )
        else:
            epub_path = (
                output_path
                if output_format == "epub"
                else job_dir / "translated.epub"
            )
            await asyncio.to_thread(
                create_translated_epub,
                translated_chunks,
                epub_path,
                title,
                paragraph_styles,
            )
            if output_format == "mobi":
                await asyncio.to_thread(convert_epub_to_mobi, epub_path, output_path)

        state = read_json(job_dir / "state.json", state)
        if state.get("cancel_requested"):
            state["status"] = "cancelled"
            save_state(job_dir, state)
            return

        state["status"] = "completed"
        state["progress"] = 100
        state["completed_chunks"] = len(chunks)
        state["output_filename"] = (
            f"{Path(state['filename']).stem}_translated.{output_format}"
        )
        state["error"] = None
        save_state(job_dir, state)

    except Exception as error:
        state = read_json(job_dir / "state.json", state)
        state["status"] = "failed"
        state["error"] = str(error)
        state["completed_chunks"] = len(list(translations_dir.glob("*.txt")))
        state["progress"] = round(state["completed_chunks"] / max(len(chunks), 1) * 100)
        save_state(job_dir, state)


async def run_job(job_id: str) -> None:
    register_job(job_id)
    try:
        await _run_job(job_id)
    finally:
        try:
            job_dir = JOBS_DIR / job_id
            state = read_json(job_dir / "state.json") if job_dir.is_dir() else None
            if state and state.get("delete_requested"):
                remove_job_directory(job_dir)
        finally:
            _ACTIVE_JOB_IDS.discard(job_id)


async def get_engine_status() -> dict:
    gemini_ready = bool(GEMINI_API_KEY)

    argos_languages = get_argos_languages()
    argos_pairs = get_argos_pairs()
    calibre_available = find_calibre_converter() is not None

    return {
        "gemini": {
            "configured": gemini_ready,
            "model": GEMINI_MODEL,
            "limits_note": "Requires an API key and internet access. Provider quotas and charges may apply.",
        },
        "argos": {
            "available": bool(argos_pairs),
            "languages": argos_languages,
            "pairs": argos_pairs,
            "limits_note": (
                "Runs locally using installed Argos Translate language packages."
            ),
        },
        "formats": {
            "input": ["pdf", "epub", *(["mobi"] if calibre_available else [])],
            "output": ["pdf", "epub", *(["mobi"] if calibre_available else [])],
            "mobi_available": calibre_available,
        },
    }
