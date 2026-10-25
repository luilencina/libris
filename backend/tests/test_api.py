import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, MagicMock, patch

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
            GITHUB_CALLBACK_URL="https://novel-translator-api.onrender.com/api/auth/github/callback",
            FRONTEND_URL="https://example.github.io/app",
        ):
            response = self.client.get(
                "/api/auth/github",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            parse_qs(urlparse(response.headers["location"]).query)["redirect_uri"][0],
            "https://novel-translator-api.onrender.com/api/auth/github/callback",
        )
        cookie = response.headers["set-cookie"].casefold()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_any_github_user_can_complete_login(self) -> None:
        configuration = {
            "APP_SESSION_SECRET": "test-session-secret-with-more-than-32-characters",
            "GITHUB_CLIENT_ID": "client-id",
            "GITHUB_CLIENT_SECRET": "client-secret",
            "GITHUB_CALLBACK_URL": "https://api.example.com/api/auth/github/callback",
            "FRONTEND_URL": "https://example.github.io/app",
        }
        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "github-access-token"}
        user_response = MagicMock()
        user_response.json.return_value = {"login": "another-github-user"}

        github_client = AsyncMock()
        github_client.post.return_value = token_response
        github_client.get.return_value = user_response
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=github_client)
        async_client.__aexit__ = AsyncMock(return_value=None)

        with patch.multiple(auth, **configuration), patch.object(
            auth.httpx,
            "AsyncClient",
            return_value=async_client,
        ):
            state = auth._sign_payload(
                {"typ": "oauth_state", "nonce": "test-nonce"},
                lifetime=600,
            )
            self.client.cookies.set(
                auth.OAUTH_STATE_COOKIE,
                state,
                path="/api/auth/github/callback",
            )
            response = self.client.get(
                "/api/auth/github/callback",
                params={"code": "oauth-code", "state": state},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            redirect_url = urlparse(response.headers["location"])
            fragment = parse_qs(redirect_url.fragment)
            self.assertIn("token", fragment)
            self.assertNotIn("auth_error", fragment)
            session = auth._verify_token(fragment["token"][0], "session")

        self.assertEqual(session["sub"], "another-github-user")

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
            ),
            patch("app.services.translation_service.GEMINI_API_KEY", ""),
            patch("app.services.translation_service.get_argos_languages", return_value=[]),
            patch("app.services.translation_service.get_argos_pairs", return_value=[]),
            patch("app.services.translation_service.find_calibre_converter", return_value=None),
        ):
            token = auth._sign_payload(
                {"typ": "session", "sub": "another-github-user"},
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
