import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.translations import ALLOWED_ENGINES
from app.core import auth
from app.main import app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_check_is_public(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_github_login_sets_a_secure_oauth_state_cookie(self) -> None:
        with patch.multiple(
            auth,
            APP_SESSION_SECRET="test-session-secret-with-more-than-32-characters",
            GITHUB_CLIENT_ID="client-id",
            GITHUB_CLIENT_SECRET="client-secret",
            GITHUB_CALLBACK_URL="https://api.example.com/api/auth/github/callback",
            FRONTEND_URL="https://example.github.io/app",
            GITHUB_ALLOWED_USERS="luilencina",
        ):
            response = self.client.get(
                "/api/auth/github",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "api.example.com/api/auth/github/callback",
            parse_qs(urlparse(response.headers["location"]).query)["redirect_uri"][0],
        )
        cookie = response.headers["set-cookie"].casefold()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_translation_routes_require_github_authentication_in_production(self) -> None:
        with (
            patch.object(auth, "APP_ENV", "production"),
            patch.object(auth, "GITHUB_CLIENT_ID", "client-id"),
        ):
            response = self.client.get("/api/engines")

        self.assertEqual(response.status_code, 401)

    def test_authenticated_engine_status_lists_only_current_engines(self) -> None:
        with (
            patch.multiple(
                auth,
                APP_ENV="production",
                APP_SESSION_SECRET="test-session-secret-with-more-than-32-characters",
                GITHUB_CLIENT_ID="client-id",
                GITHUB_CLIENT_SECRET="client-secret",
                GITHUB_CALLBACK_URL="https://api.example.com/api/auth/github/callback",
                FRONTEND_URL="https://example.github.io/app",
                GITHUB_ALLOWED_USERS="luilencina",
            ),
            patch("app.services.translation_service.GEMINI_API_KEY", ""),
            patch("app.services.translation_service.get_argos_languages", return_value=[]),
            patch("app.services.translation_service.get_argos_pairs", return_value=[]),
            patch("app.services.translation_service.find_calibre_converter", return_value=None),
        ):
            token = auth._sign_payload(
                {"typ": "session", "sub": "luilencina"},
                lifetime=60,
            )
            response = self.client.get(
                "/api/engines",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"gemini", "argos", "formats"})

    def test_only_gemini_and_argos_are_supported(self) -> None:
        self.assertEqual(ALLOWED_ENGINES, {"gemini", "argos"})


if __name__ == "__main__":
    unittest.main()
