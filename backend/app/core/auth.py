import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import (
    APP_ENV,
    APP_SESSION_SECRET,
    FRONTEND_URL,
    GITHUB_ALLOWED_USERS,
    GITHUB_CALLBACK_URL,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
)

auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)
OAUTH_STATE_COOKIE = "novel_translator_oauth_state"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _require_auth_configuration() -> None:
    required = {
        "GITHUB_CLIENT_ID": GITHUB_CLIENT_ID,
        "GITHUB_CLIENT_SECRET": GITHUB_CLIENT_SECRET,
        "GITHUB_CALLBACK_URL": GITHUB_CALLBACK_URL,
        "FRONTEND_URL": FRONTEND_URL,
        "APP_SESSION_SECRET": APP_SESSION_SECRET,
        "GITHUB_ALLOWED_USERS": GITHUB_ALLOWED_USERS,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"GitHub authentication is not configured: {', '.join(missing)}.",
        )
    if len(APP_SESSION_SECRET.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="APP_SESSION_SECRET must contain at least 32 characters.",
        )


def _sign_payload(payload: dict, lifetime: int) -> str:
    _require_auth_configuration()
    now = int(time.time())
    header = _encode(b'{"alg":"HS256","typ":"JWT"}')
    claims = _encode(
        json.dumps(
            {**payload, "iat": now, "exp": now + lifetime},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    message = f"{header}.{claims}".encode("ascii")
    signature = hmac.new(
        APP_SESSION_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return f"{header}.{claims}.{_encode(signature)}"


def _verify_token(token: str, expected_type: str) -> dict:
    _require_auth_configuration()
    try:
        header, claims, signature = token.split(".")
        message = f"{header}.{claims}".encode("ascii")
        expected_signature = hmac.new(
            APP_SESSION_SECRET.encode("utf-8"),
            message,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_decode(signature), expected_signature):
            raise ValueError("Invalid signature.")
        payload = json.loads(_decode(claims))
        if payload.get("typ") != expected_type or payload.get("exp", 0) <= time.time():
            raise ValueError("Invalid or expired token.")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("Invalid or expired token.") from error


def _allowed_users() -> set[str]:
    return {
        username.strip().casefold()
        for username in GITHUB_ALLOWED_USERS.split(",")
        if username.strip()
    }


def _frontend_redirect(fragment: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{FRONTEND_URL.rstrip('/')}/#{fragment}",
        status_code=303,
    )
    response.delete_cookie(
        OAUTH_STATE_COOKIE,
        path="/api/auth/github/callback",
        secure=GITHUB_CALLBACK_URL.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return response


@auth_router.get("/github")
async def github_login():
    _require_auth_configuration()
    state = _sign_payload(
        {"typ": "oauth_state", "nonce": secrets.token_urlsafe(24)},
        lifetime=600,
    )
    query = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_CALLBACK_URL,
            "scope": "read:user",
            "state": state,
        }
    )
    response = RedirectResponse(
        f"https://github.com/login/oauth/authorize?{query}",
        status_code=302,
    )
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        path="/api/auth/github/callback",
        secure=GITHUB_CALLBACK_URL.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return response


@auth_router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    _require_auth_configuration()
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if (
        not state
        or not cookie_state
        or not hmac.compare_digest(state, cookie_state)
    ):
        raise HTTPException(status_code=400, detail="GitHub login state did not match.")

    try:
        _verify_token(state, "oauth_state")
    except ValueError as token_error:
        raise HTTPException(status_code=400, detail=str(token_error)) from token_error

    if error:
        return _frontend_redirect("auth_error=cancelled")
    if not code:
        raise HTTPException(status_code=400, detail="GitHub returned an incomplete login response.")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": GITHUB_CALLBACK_URL,
                    "state": state,
                },
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = (
                token_payload.get("access_token")
                if isinstance(token_payload, dict)
                else None
            )
            if not access_token:
                raise HTTPException(
                    status_code=400,
                    detail="GitHub did not return an access token.",
                )

            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            user_response.raise_for_status()
            user_payload = user_response.json()
            username = (
                user_payload.get("login", "")
                if isinstance(user_payload, dict)
                else ""
            )
    except (httpx.HTTPError, ValueError) as request_error:
        raise HTTPException(
            status_code=502,
            detail="Could not complete GitHub authentication.",
        ) from request_error

    if not isinstance(username, str) or username.casefold() not in _allowed_users():
        return _frontend_redirect("auth_error=not_allowed")

    session_token = _sign_payload(
        {"typ": "session", "sub": username},
        lifetime=8 * 60 * 60,
    )
    return _frontend_redirect(f"token={session_token}")


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, str]:
    if APP_ENV == "development" and not GITHUB_CLIENT_ID:
        return {"login": "local"}
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign in with GitHub to use the API.")

    try:
        payload = _verify_token(credentials.credentials, "session")
    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    username = payload.get("sub")
    if not isinstance(username, str) or username.casefold() not in _allowed_users():
        raise HTTPException(status_code=403, detail="This GitHub account is not authorized.")
    return {"login": username}
