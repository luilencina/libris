import asyncio
import errno
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import JOBS_DIR, MAX_UPLOAD_MB
from app.core.auth import require_authenticated_user
from app.services.book_formats import MIME_TYPES, SUPPORTED_FORMATS, find_calibre_converter
from app.services.translation_service import (
    create_job_safely,
    delete_job,
    get_argos_diagnostics,
    get_argos_languages,
    get_argos_pairs,
    get_available_argos_packages_safely,
    get_job_dir,
    install_argos_package_safely,
    load_job,
    register_job,
    read_json,
    run_job,
    save_state,
)

router = APIRouter(
    prefix="/api",
    tags=["translations"],
    dependencies=[Depends(require_authenticated_user)],
)
public_router = APIRouter(prefix="/api", tags=["health"])
ALLOWED_ENGINES = {"gemini", "argos"}
_LOGGER = logging.getLogger(__name__)


class ArgosPackageRequest(BaseModel):
    source_code: str
    target_code: str


@public_router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/engines")
async def engines():
    from app.services.translation_service import get_engine_status
    return await get_engine_status()


@router.get("/languages")
async def languages():
    return {"languages": get_argos_languages(), "pairs": get_argos_pairs()}


@router.get("/languages/diagnostics")
async def argos_diagnostics(test: bool = False):
    try:
        return await get_argos_diagnostics(run_test=test)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Could not inspect Argos Translate: {error}",
        ) from error


@router.get("/languages/available")
async def available_languages():
    try:
        packages = await get_available_argos_packages_safely()
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not load Argos language packages: {error}",
        ) from error
    return {"packages": packages}


@router.post("/languages/install")
async def install_language_package(request: ArgosPackageRequest):
    try:
        await install_argos_package_safely(
            request.source_code,
            request.target_code,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not install the Argos language package: {error}",
        ) from error
    return {"status": "installed"}


@router.post("/translations")
async def start_translation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    engine: str = Form(...),
    source_language: str = Form("English"),
    target_language: str = Form("Portuguese (Brazil)"),
    output_format: str = Form("pdf"),
):
    if engine not in ALLOWED_ENGINES:
        raise HTTPException(status_code=400, detail="Choose a supported translation engine.")

    filename = Path(file.filename or "book.pdf").name
    input_format = Path(filename).suffix.lstrip(".").lower()
    if input_format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail="Only PDF, EPUB, and MOBI files are supported.")
    if input_format == "mobi" and not find_calibre_converter():
        raise HTTPException(
            status_code=503,
            detail="MOBI input requires Calibre. Install Calibre and restart the backend.",
        )
    if output_format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=400, detail="Choose PDF, EPUB, or MOBI as the export format.")
    if output_format == "mobi" and not find_calibre_converter():
        raise HTTPException(
            status_code=503,
            detail="MOBI export requires Calibre. Install Calibre and restart the backend.",
        )

    if engine == "argos":
        installed_languages = get_argos_languages()
        source = next(
            (item for item in installed_languages if item["name"].casefold() == source_language.casefold() or item["code"].casefold() == source_language.casefold()),
            None,
        )
        target = next(
            (item for item in installed_languages if item["name"].casefold() == target_language.casefold() or item["code"].casefold() == target_language.casefold()),
            None,
        )
        if not source or not target or not any(
            pair["from_code"] == source["code"] and pair["to_code"] == target["code"]
            for pair in get_argos_pairs()
        ):
            raise HTTPException(
                status_code=400,
                detail="Install the selected Argos language pair before translating.",
            )

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{input_format}") as temporary_file:
        temporary_path = Path(temporary_file.name)
        total_size = 0
        try:
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                total_size += len(block)
                if total_size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The book exceeds the {MAX_UPLOAD_MB} MB upload limit.",
                    )
                temporary_file.write(block)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    try:
        job = await create_job_safely(
            temporary_path,
            filename,
            engine,
            source_language,
            target_language,
            output_format,
        )
    except ValueError as error:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        _LOGGER.exception("Could not save or read uploaded book %s.", filename)
        status_code = 507 if error.errno == errno.ENOSPC else 500
        detail = (
            "The server does not have enough storage to process this book."
            if status_code == 507
            else "The server could not save or read the uploaded book."
        )
        raise HTTPException(status_code=status_code, detail=detail) from error
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not read the book: {error}") from error

    register_job(job["id"])
    background_tasks.add_task(run_job, job["id"])
    return job


@router.get("/translations")
async def list_translations():
    jobs = []
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        state = read_json(job_dir / "state.json")
        if state:
            try:
                state.setdefault(
                    "input_format",
                    Path(state.get("filename", "")).suffix.lstrip(".").lower()
                    or "pdf",
                )
                state.setdefault("output_format", "pdf")
                state["completed_chunks"] = len(list((job_dir / "translations").glob("*.txt")))
                jobs.append(state)
            except OSError:
                continue
    jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jobs[:50]


@router.get("/translations/{job_id}")
async def translation_status(job_id: str):
    try:
        return load_job(job_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/translations/{job_id}/cancel")
async def cancel_translation(job_id: str):
    try:
        job_dir = get_job_dir(job_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    state = read_json(job_dir / "state.json")
    if state["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="This translation is not running.")

    state["cancel_requested"] = True
    save_state(job_dir, state)
    return {"status": "cancellation_requested"}


@router.delete("/translations/{job_id}")
async def delete_translation(job_id: str):
    try:
        status = delete_job(job_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not delete the translation job: {error}",
        ) from error
    return {"status": status}


@router.post("/translations/{job_id}/resume")
async def resume_translation(job_id: str, background_tasks: BackgroundTasks):
    try:
        job_dir = get_job_dir(job_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    state = read_json(job_dir / "state.json")
    if state["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be resumed.")

    state["status"] = "queued"
    state["cancel_requested"] = False
    state["error"] = None
    save_state(job_dir, state)
    register_job(job_id)
    background_tasks.add_task(run_job, job_id)
    return state


@router.get("/translations/{job_id}/download")
async def download_translation(job_id: str):
    try:
        job_dir = get_job_dir(job_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    state = read_json(job_dir / "state.json")
    output_format = state.get("output_format", "pdf")
    output_path = job_dir / f"translated.{output_format}"
    if state.get("status") != "completed" or not output_path.exists():
        raise HTTPException(status_code=409, detail="The translated book is not ready.")

    return FileResponse(
        path=output_path,
        media_type=MIME_TYPES[output_format],
        filename=state.get(
            "output_filename",
            f"translated_book.{output_format}",
        ),
    )
