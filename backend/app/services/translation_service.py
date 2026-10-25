import asyncio
import gc
import json
import logging
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.config import (
    BACKEND_DIR,
    CHUNK_CHAR_LIMIT,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    JOBS_DIR,
)
import argostranslate.package
import argostranslate.translate

from app.services.book_formats import (
    SUPPORTED_FORMATS,
    convert_epub_to_mobi,
    create_translated_epub,
    find_calibre_converter,
)
from app.services.pdf_service import (
    create_translated_pdf,
    remove_job_directory,
)

_ACTIVE_JOB_IDS: set[str] = set()
_RESOURCE_LOCK = asyncio.Lock()
_LOGGER = logging.getLogger(__name__)
_PRIORITY_LANGUAGE_CODES = frozenset({"pt", "en", "es", "de", "fr", "it"})


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


def iter_job_chunks(job_dir: Path) -> Iterator[dict]:
    chunks_path = job_dir / "chunks.jsonl"
    if chunks_path.is_file():
        with chunks_path.open(encoding="utf-8") as chunks_file:
            for line in chunks_file:
                if line.strip():
                    yield json.loads(line)
        return

    legacy_chunks = read_json(job_dir / "chunks.json", [])
    yield from legacy_chunks


def iter_translated_chunks(job_dir: Path) -> Iterator[str]:
    for chunk in iter_job_chunks(job_dir):
        translated_path = job_dir / "translations" / f"{chunk['index']:06d}.txt"
        if not translated_path.is_file():
            raise RuntimeError(
                f"Missing translation checkpoint for chunk {chunk['index'] + 1}."
            )
        yield translated_path.read_text(encoding="utf-8")


def iter_chunk_styles(job_dir: Path) -> Iterator[list[dict]]:
    for chunk in iter_job_chunks(job_dir):
        yield chunk.get("paragraph_styles", [])


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


def get_argos_translation_steps(source_code: str, target_code: str) -> list[Any]:
    languages = {
        identifier: language
        for language in argostranslate.translate.get_installed_languages()
        for identifier in (language.code.casefold(), language.name.casefold())
    }
    source = languages.get(source_code.strip().casefold())
    target = languages.get(target_code.strip().casefold())
    if source is None or target is None:
        raise RuntimeError(
            f"Argos language packages are missing for {source_code} -> {target_code}."
        )

    translation = source.get_translation(target)
    if translation is None:
        raise RuntimeError(
            f"No Argos translation route is installed for "
            f"{source.code} -> {target.code}."
        )

    def flatten(item: Any) -> list[Any]:
        if isinstance(item, argostranslate.translate.CompositeTranslation):
            return flatten(item.t1) + flatten(item.t2)
        return [item]

    return flatten(translation)


def release_argos_translation(translation: Any) -> None:
    visited: set[int] = set()

    def release(item: Any) -> None:
        if id(item) in visited:
            return
        visited.add(id(item))
        if isinstance(item, argostranslate.translate.CachedTranslation):
            item.cache.clear()
            release(item.underlying)
        elif isinstance(item, argostranslate.translate.CompositeTranslation):
            release(item.t1)
            release(item.t2)
        elif isinstance(item, argostranslate.translate.PackageTranslation):
            item.translator = None
            if getattr(item.sentencizer, "detector", None) is not None:
                item.sentencizer.detector = None
            if getattr(item.sentencizer, "stanza_pipeline", None) is not None:
                item.sentencizer.stanza_pipeline = None

    release(translation)
    gc.collect()


def _process_memory_mib() -> dict[str, float | None]:
    values: dict[str, float | None] = {"rss_mib": None, "peak_rss_mib": None}
    try:
        with Path("/proc/self/status").open(encoding="utf-8") as status_file:
            for line in status_file:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    key = "rss_mib" if line.startswith("VmRSS:") else "peak_rss_mib"
                    values[key] = round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return values


def _argos_diagnostics(run_test: bool) -> dict:
    installed_packages = [
        package
        for package in argostranslate.package.get_installed_packages()
        if package.type == "translate"
    ]
    direct_pairs = sorted(
        {
            (package.from_code, package.to_code)
            for package in installed_packages
        }
    )
    languages = get_argos_languages()
    language_codes = {language["code"] for language in languages}
    usable_pairs = get_argos_pairs()
    usable_pair_codes = {
        (pair["from_code"], pair["to_code"])
        for pair in usable_pairs
    }
    missing_priority_pairs = sorted(
        (source, target)
        for source in _PRIORITY_LANGUAGE_CODES
        for target in _PRIORITY_LANGUAGE_CODES
        if source != target
        and (
            source not in language_codes
            or target not in language_codes
            or (source, target) not in usable_pair_codes
        )
    )
    status = (
        "ready"
        if not missing_priority_pairs
        else "partial"
        if direct_pairs
        else "unavailable"
    )
    result = {
        "status": status,
        "languages": languages,
        "installed_direct_pairs": [
            {"from_code": source, "to_code": target}
            for source, target in direct_pairs
        ],
        "usable_pairs": usable_pairs,
        "missing_priority_pairs": [
            {"from_code": source, "to_code": target}
            for source, target in missing_priority_pairs
        ],
        "process_memory": _process_memory_mib(),
        "test_translation": None,
    }

    if run_test:
        preferred_pair = ("en", "pt")
        pair = preferred_pair if preferred_pair in direct_pairs else next(iter(direct_pairs), None)
        if pair is None:
            result["test_translation"] = {
                "status": "unavailable",
                "detail": "No installed Argos package can be tested.",
            }
        else:
            source = next(
                language
                for language in argostranslate.translate.get_installed_languages()
                if language.code == pair[0]
            )
            target = next(
                language
                for language in argostranslate.translate.get_installed_languages()
                if language.code == pair[1]
            )
            translation = source.get_translation(target)
            try:
                if translation is None:
                    raise RuntimeError(
                        f"No installed Argos route for {pair[0]} -> {pair[1]}."
                    )
                translated = translation.translate("Good morning.")
                result["test_translation"] = {
                    "status": "ok",
                    "from_code": pair[0],
                    "to_code": pair[1],
                    "source_text": "Good morning.",
                    "translated_text": translated,
                }
            except Exception as error:
                result["status"] = "degraded"
                result["test_translation"] = {
                    "status": "failed",
                    "from_code": pair[0],
                    "to_code": pair[1],
                    "detail": str(error),
                }
            finally:
                if translation is not None:
                    release_argos_translation(translation)
                result["process_memory"] = _process_memory_mib()

    return result


async def get_argos_diagnostics(run_test: bool = False) -> dict:
    async with _RESOURCE_LOCK:
        return await asyncio.to_thread(_argos_diagnostics, run_test)


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


async def get_available_argos_packages_safely() -> list[dict]:
    async with _RESOURCE_LOCK:
        return await asyncio.to_thread(get_available_argos_packages)


def install_argos_package(source_code: str, target_code: str) -> None:
    source_code = source_code.strip().casefold()
    target_code = target_code.strip().casefold()
    installed_pairs = {
        (package.from_code, package.to_code)
        for package in argostranslate.package.get_installed_packages()
        if package.type == "translate"
    }
    if (source_code, target_code) in installed_pairs:
        return

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


async def install_argos_package_safely(source_code: str, target_code: str) -> None:
    async with _RESOURCE_LOCK:
        await asyncio.to_thread(install_argos_package, source_code, target_code)


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
        from google import genai
        from google.genai import types

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
    async with _RESOURCE_LOCK:
        steps = await asyncio.to_thread(
            get_argos_translation_steps,
            source_language,
            target_language,
        )
        result = text
        try:
            for step in steps:
                result = await asyncio.to_thread(_translate_argos_step, step, result)
                await asyncio.to_thread(release_argos_translation, step)
        finally:
            for step in steps:
                await asyncio.to_thread(release_argos_translation, step)
        return result


def _translate_argos_step(translation: Any, text: str) -> str:
    result = translation.translate(text).strip()
    if not result:
        raise RuntimeError("Argos Translate returned an empty translation.")
    return result

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
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.services.book_extractor",
                str(saved_upload),
                input_format,
                str(job_dir),
                str(CHUNK_CHAR_LIMIT),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=BACKEND_DIR,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or "The book extraction process failed.")
        extraction = read_json(job_dir / "extraction.json")
        if not extraction:
            raise RuntimeError("The book extraction process did not report its result.")
        page_count = int(extraction["total_pages_with_text"])
        chunk_count = int(extraction["total_chunks"])
        (job_dir / "extraction.json").unlink()
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
        "total_pages_with_text": page_count,
        "total_chunks": chunk_count,
        "completed_chunks": 0,
        "progress": 0,
        "error": None,
        "cancel_requested": False,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    save_state(job_dir, state)
    return state


async def create_job_safely(
    upload_path: Path,
    original_filename: str,
    engine: str,
    source_language: str,
    target_language: str,
    output_format: str = "pdf",
) -> dict:
    async with _RESOURCE_LOCK:
        return await asyncio.to_thread(
            create_job,
            upload_path,
            original_filename,
            engine,
            source_language,
            target_language,
            output_format,
        )


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

    translations_dir = job_dir / "translations"
    total_chunks = max(int(state.get("total_chunks", 0)), 1)

    try:
        if state["engine"] == "argos":
            completed = await _run_argos_stages(
                job_dir,
                state,
                translations_dir,
                total_chunks,
            )
        else:
            completed = await _run_gemini_chunks(
                job_dir,
                state,
                translations_dir,
                total_chunks,
            )
        if not completed:
            return

        state = read_json(job_dir / "state.json", state)
        if state.get("cancel_requested"):
            state["status"] = "cancelled"
            save_state(job_dir, state)
            return

        title = Path(state["filename"]).stem.replace("_", " ").replace("-", " ").strip()
        output_format = state.get("output_format", "pdf")
        output_path = job_dir / f"translated.{output_format}"
        translated_chunks = iter_translated_chunks(job_dir)
        paragraph_styles = iter_chunk_styles(job_dir)
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
        state["completed_chunks"] = int(state.get("total_chunks", 0))
        state["output_filename"] = (
            f"{Path(state['filename']).stem}_translated.{output_format}"
        )
        state["error"] = None
        save_state(job_dir, state)

    except Exception as error:
        state = read_json(job_dir / "state.json", state)
        state["status"] = "failed"
        state["error"] = str(error)
        state["completed_chunks"] = sum(1 for _ in translations_dir.glob("*.txt"))
        state["progress"] = round(state["completed_chunks"] / total_chunks * 100)
        save_state(job_dir, state)


async def _run_gemini_chunks(
    job_dir: Path,
    state: dict,
    translations_dir: Path,
    total_chunks: int,
) -> bool:
    completed = sum(1 for _ in translations_dir.glob("*.txt"))
    for chunk in iter_job_chunks(job_dir):
        state = read_json(job_dir / "state.json", state)
        if state.get("cancel_requested"):
            state["status"] = "cancelled"
            save_state(job_dir, state)
            return False

        output_path = translations_dir / f"{chunk['index']:06d}.txt"
        if output_path.is_file() and output_path.stat().st_size:
            continue

        last_error = None
        for attempt in range(3):
            state = read_json(job_dir / "state.json", state)
            if state.get("cancel_requested"):
                state["status"] = "cancelled"
                save_state(job_dir, state)
                return False
            try:
                translated = await translate_with_gemini(
                    chunk["text"],
                    state["source_language"],
                    state["target_language"],
                )
                output_path.write_text(translated, encoding="utf-8")
                last_error = None
                break
            except Exception as error:
                last_error = error
                if attempt < 2:
                    await asyncio.sleep(2**attempt)

        if last_error is not None:
            raise RuntimeError(
                f"Translation failed at chunk {chunk['index'] + 1}: {last_error}"
            )

        completed += 1
        state["completed_chunks"] = completed
        state["progress"] = round(completed / total_chunks * 100)
        save_state(job_dir, state)
    return True


async def _run_argos_stages(
    job_dir: Path,
    state: dict,
    translations_dir: Path,
    total_chunks: int,
) -> bool:
    stages = await asyncio.to_thread(
        get_argos_translation_steps,
        state["source_language"],
        state["target_language"],
    )
    intermediate_dirs = [
        job_dir / f"argos-stage-{index}"
        for index in range(max(0, len(stages) - 1))
    ]

    for stage_index, stage in enumerate(stages):
        final_stage = stage_index == len(stages) - 1
        output_dir = translations_dir if final_stage else intermediate_dirs[stage_index]
        output_dir.mkdir(exist_ok=True)
        input_dir = None if stage_index == 0 else intermediate_dirs[stage_index - 1]
        stage_completed = 0
        _LOGGER.info(
            "Starting Argos model stage %d/%d: %s -> %s.",
            stage_index + 1,
            len(stages),
            stage.from_lang.code,
            stage.to_lang.code,
        )

        try:
            for chunk in iter_job_chunks(job_dir):
                state = read_json(job_dir / "state.json", state)
                if state.get("cancel_requested"):
                    state["status"] = "cancelled"
                    save_state(job_dir, state)
                    return False

                output_path = output_dir / f"{chunk['index']:06d}.txt"
                if output_path.is_file() and output_path.stat().st_size:
                    stage_completed += 1
                    state["progress"] = round(
                        ((stage_index * total_chunks + stage_completed)
                        / (len(stages) * total_chunks))
                        * 100
                    )
                    if final_stage:
                        state["completed_chunks"] = sum(
                            1 for _ in translations_dir.glob("*.txt")
                        )
                    save_state(job_dir, state)
                    continue

                input_text = (
                    chunk["text"]
                    if input_dir is None
                    else (input_dir / output_path.name).read_text(encoding="utf-8")
                )
                last_error = None
                for attempt in range(3):
                    state = read_json(job_dir / "state.json", state)
                    if state.get("cancel_requested"):
                        state["status"] = "cancelled"
                        save_state(job_dir, state)
                        return False
                    try:
                        translated = await asyncio.to_thread(
                            _translate_argos_step,
                            stage,
                            input_text,
                        )
                        output_path.write_text(translated, encoding="utf-8")
                        last_error = None
                        break
                    except Exception as error:
                        last_error = error
                        if attempt < 2:
                            await asyncio.sleep(2**attempt)

                if last_error is not None:
                    raise RuntimeError(
                        f"Argos translation failed at stage {stage_index + 1}, "
                        f"chunk {chunk['index'] + 1}: {last_error}"
                    )

                stage_completed += 1
                state["completed_chunks"] = (
                    sum(1 for _ in translations_dir.glob("*.txt"))
                    if final_stage
                    else 0
                )
                state["progress"] = round(
                    ((stage_index * total_chunks + stage_completed)
                    / (len(stages) * total_chunks))
                    * 100
                )
                save_state(job_dir, state)
        except Exception:
            _LOGGER.exception(
                "Argos model stage %d failed: %s -> %s.",
                stage_index + 1,
                stage.from_lang.code,
                stage.to_lang.code,
            )
            raise
        finally:
            await asyncio.to_thread(release_argos_translation, stage)
            _LOGGER.info(
                "Released Argos model stage %d/%d.",
                stage_index + 1,
                len(stages),
            )

    for intermediate_dir in intermediate_dirs:
        if intermediate_dir.exists():
            shutil.rmtree(intermediate_dir)
    state["completed_chunks"] = total_chunks
    state["progress"] = 100
    save_state(job_dir, state)
    return True


async def run_job(job_id: str) -> None:
    register_job(job_id)
    try:
        async with _RESOURCE_LOCK:
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
