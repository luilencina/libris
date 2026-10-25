import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import translation_service


class RuntimeSafetyTests(unittest.TestCase):
    def test_fastapi_import_does_not_import_argos_translate(self) -> None:
        backend_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.main; "
                "print('argostranslate.translate' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=backend_dir,
        )

        self.assertEqual(result.stdout.strip(), "False")

    def test_argos_catalog_uses_package_metadata_without_loading_translator(self) -> None:
        packages = [
            SimpleNamespace(
                type="translate",
                from_code="en",
                from_name="English",
                to_code="pt",
                to_name="Portuguese",
            ),
            SimpleNamespace(
                type="translate",
                from_code="pt",
                from_name="Portuguese",
                to_code="es",
                to_name="Spanish",
            ),
        ]
        package_module = SimpleNamespace(
            get_installed_packages=lambda: packages,
        )
        with (
            patch.object(
                translation_service,
                "_argos_package_module",
                return_value=package_module,
            ),
            patch.object(
                translation_service,
                "_argos_translate_module",
                side_effect=AssertionError("catalog must not load model runtime"),
            ),
        ):
            languages, pairs = translation_service.get_argos_catalog()

        self.assertEqual({language["code"] for language in languages}, {"en", "pt", "es"})
        self.assertIn(
            {"from_code": "en", "from_name": "English", "to_code": "es", "to_name": "Spanish"},
            pairs,
        )

    def test_argos_memory_preflight_rejects_low_container_headroom(self) -> None:
        memory = {
            "rss_mib": 300.0,
            "peak_rss_mib": 400.0,
            "container_used_mib": 400.0,
            "container_limit_mib": 512.0,
            "container_available_mib": 112.0,
        }
        with (
            patch.object(translation_service, "ARGOS_PEAK_RSS_ESTIMATE_MB", 465),
            patch.object(translation_service, "ARGOS_MEMORY_SAFETY_MARGIN_MB", 32),
            patch.object(translation_service, "_process_memory_mib", return_value=memory),
            self.assertRaisesRegex(RuntimeError, "112.0 MiB free"),
        ):
            translation_service._check_argos_memory_headroom()

    def test_translation_dispatches_to_gemini_and_argos_without_fallback(self) -> None:
        argos_job = {"engine": "argos", "source_language": "en", "target_language": "pt"}
        gemini_job = {
            "engine": "gemini",
            "source_language": "en",
            "target_language": "pt",
        }
        with (
            patch.object(
                translation_service,
                "translate_with_argos",
                new=AsyncMock(return_value="Argos result"),
            ) as argos_translate,
            patch.object(
                translation_service,
                "translate_with_gemini",
                new=AsyncMock(return_value="Gemini result"),
            ) as gemini_translate,
        ):
            argos_result = asyncio.run(
                translation_service.translate_chunk(argos_job, "short input")
            )
            gemini_result = asyncio.run(
                translation_service.translate_chunk(gemini_job, "short input")
            )

        self.assertEqual(argos_result, "Argos result")
        self.assertEqual(gemini_result, "Gemini result")
        argos_translate.assert_awaited_once()
        gemini_translate.assert_awaited_once()

    def test_short_argos_and_gemini_translations(self) -> None:
        with (
            patch.object(
                translation_service,
                "get_argos_translation_steps",
                return_value=[object()],
            ),
            patch.object(
                translation_service,
                "_translate_argos_step",
                return_value="Argos result",
            ),
            patch.object(translation_service, "release_argos_translation"),
            patch.object(
                translation_service,
                "_check_argos_memory_headroom",
                return_value={},
            ),
        ):
            argos_result = asyncio.run(
                translation_service.translate_with_argos("Hello", "en", "pt")
            )

        with (
            patch.object(translation_service, "GEMINI_API_KEY", "test-key"),
            patch.object(
                translation_service.asyncio,
                "to_thread",
                new=AsyncMock(return_value=SimpleNamespace(text="Gemini result")),
            ),
        ):
            gemini_result = asyncio.run(
                translation_service.translate_with_gemini("Hello", "en", "pt")
            )

        self.assertEqual(argos_result, "Argos result")
        self.assertEqual(gemini_result, "Gemini result")

    def test_failed_argos_job_is_checkpointed_without_raising_to_server(self) -> None:
        job_id = "a" * 32
        with tempfile.TemporaryDirectory() as temporary:
            jobs_dir = Path(temporary)
            job_dir = jobs_dir / job_id
            (job_dir / "translations").mkdir(parents=True)
            translation_service.write_json(
                job_dir / "state.json",
                {
                    "id": job_id,
                    "engine": "argos",
                    "source_language": "en",
                    "target_language": "pt",
                    "status": "queued",
                    "total_chunks": 1,
                    "completed_chunks": 0,
                    "progress": 0,
                    "cancel_requested": False,
                },
            )

            with (
                patch.object(translation_service, "JOBS_DIR", jobs_dir),
                patch.object(
                    translation_service,
                    "_run_argos_stages",
                    new=AsyncMock(side_effect=RuntimeError("model unavailable")),
                ),
            ):
                asyncio.run(translation_service.run_job(job_id))

            state = translation_service.read_json(job_dir / "state.json")

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], "model unavailable")
        self.assertEqual(translation_service._ACTIVE_JOB_IDS, set())

    def test_argos_stage_resume_skips_completed_checkpoint(self) -> None:
        stage = MagicMock()
        stage.from_lang = SimpleNamespace(code="en")
        stage.to_lang = SimpleNamespace(code="pt")
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            translations_dir = job_dir / "translations"
            translations_dir.mkdir()
            (job_dir / "chunks.jsonl").write_text(
                json.dumps({"index": 0, "text": "already translated"}) + "\n",
                encoding="utf-8",
            )
            checkpoint = translations_dir / "000000.txt"
            checkpoint.write_text("saved translation", encoding="utf-8")
            state = {
                "id": "b" * 32,
                "status": "running",
                "cancel_requested": False,
                "source_language": "en",
                "target_language": "pt",
                "total_chunks": 1,
            }

            with (
                patch.object(
                    translation_service,
                    "get_argos_translation_steps",
                    return_value=[stage],
                ),
                patch.object(translation_service, "release_argos_translation"),
                patch.object(
                    translation_service,
                    "_translate_argos_step",
                    side_effect=AssertionError("checkpoint should be reused"),
                ),
            ):
                completed = asyncio.run(
                    translation_service._run_argos_stages(
                        job_dir,
                        state,
                        translations_dir,
                        total_chunks=1,
                    )
                )

            self.assertEqual(checkpoint.read_text(encoding="utf-8"), "saved translation")
            self.assertTrue(completed)
            self.assertEqual(state["completed_chunks"], 1)
            self.assertEqual(state["progress"], 100)


if __name__ == "__main__":
    unittest.main()
