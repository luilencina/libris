import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.core import auth


class AuthenticationTests(unittest.TestCase):
    def test_signed_session_token_round_trips(self) -> None:
        with patch.multiple(
            auth,
            APP_SESSION_SECRET="test-session-secret-with-more-than-32-characters",
            GITHUB_CLIENT_ID="client-id",
            GITHUB_CLIENT_SECRET="client-secret",
            GITHUB_CALLBACK_URL="https://api.example.com/api/auth/github/callback",
            FRONTEND_URL="https://example.github.io/app",
        ):
            token = auth._sign_payload(
                {"typ": "session", "sub": "luilencina"},
                lifetime=60,
            )

            self.assertEqual(auth._verify_token(token, "session")["sub"], "luilencina")

    def test_tampered_session_token_is_rejected(self) -> None:
        with patch.multiple(
            auth,
            APP_SESSION_SECRET="test-session-secret-with-more-than-32-characters",
            GITHUB_CLIENT_ID="client-id",
            GITHUB_CLIENT_SECRET="client-secret",
            GITHUB_CALLBACK_URL="https://api.example.com/api/auth/github/callback",
            FRONTEND_URL="https://example.github.io/app",
        ):
            token = auth._sign_payload(
                {"typ": "session", "sub": "luilencina"},
                lifetime=60,
            )
            header, claims, signature = token.split(".")
            tampered_token = f"{header}.{claims[:-1]}x.{signature}"

            with self.assertRaisesRegex(ValueError, "Invalid or expired token"):
                auth._verify_token(tampered_token, "session")

    def test_production_requests_require_a_session(self) -> None:
        with (
            patch.object(auth, "APP_ENV", "production"),
            patch.object(auth, "GITHUB_CLIENT_ID", "client-id"),
        ):
            with self.assertRaises(HTTPException) as error:
                auth.require_authenticated_user(credentials=None)

        self.assertEqual(error.exception.status_code, 401)

    def test_local_development_does_not_require_github_login(self) -> None:
        with (
            patch.object(auth, "APP_ENV", "development"),
            patch.object(auth, "GITHUB_CLIENT_ID", ""),
        ):
            self.assertEqual(
                auth.require_authenticated_user(credentials=None),
                {"login": "local"},
            )


if __name__ == "__main__":
    unittest.main()
