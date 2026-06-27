import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from fastapi import HTTPException, Request, Response, status

from .config import Settings
from .models import AuthUser


SESSION_COOKIE = "vibechat_session"


@dataclass(frozen=True)
class SessionPayload:
    email: str
    display_name: str
    expires_at: int


def configured_user(settings: Settings) -> AuthUser:
    return AuthUser(
        email=settings.auth_email.strip().lower(),
        display_name=settings.auth_display_name.strip() or "VibeChat 用户",
    )


def authenticate(settings: Settings, account: str, password: str) -> AuthUser | None:
    expected_account = settings.auth_email.strip().lower()
    expected_password = settings.auth_password
    if (
        secrets.compare_digest(account.strip().lower(), expected_account)
        and secrets.compare_digest(password, expected_password)
    ):
        return configured_user(settings)
    return None


def create_session_token(settings: Settings, user: AuthUser) -> str:
    now = datetime.now(timezone.utc)
    expires_at = int((now + timedelta(seconds=settings.auth_session_ttl_seconds)).timestamp())
    payload = {
        "email": user.email,
        "display_name": user.display_name,
        "iat": int(now.timestamp()),
        "exp": expires_at,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_part = _base64_url_encode(payload_bytes)
    signature = _sign(settings, payload_part)
    return f"{payload_part}.{signature}"


def read_session(settings: Settings, request: Request) -> AuthUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError as exc:
        raise _invalid_session() from exc
    expected_signature = _sign(settings, payload_part)
    if not secrets.compare_digest(signature, expected_signature):
        raise _invalid_session()
    try:
        payload = json.loads(_base64_url_decode(payload_part))
    except (ValueError, json.JSONDecodeError) as exc:
        raise _invalid_session() from exc
    parsed = _parse_payload(payload)
    if parsed.expires_at < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    return AuthUser(email=parsed.email, display_name=parsed.display_name)


def set_session_cookie(settings: Settings, request: Request, response: Response, user: AuthUser) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(settings, user),
        max_age=settings.auth_session_ttl_seconds,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def _parse_payload(payload: Any) -> SessionPayload:
    if not isinstance(payload, dict):
        raise _invalid_session()
    email = payload.get("email")
    display_name = payload.get("display_name")
    expires_at = payload.get("exp")
    if not isinstance(email, str) or not isinstance(display_name, str) or not isinstance(expires_at, int):
        raise _invalid_session()
    return SessionPayload(email=email, display_name=display_name, expires_at=expires_at)


def _sign(settings: Settings, payload_part: str) -> str:
    signature = hmac.new(
        settings.auth_secret_key.encode("utf-8"),
        payload_part.encode("utf-8"),
        sha256,
    ).digest()
    return _base64_url_encode(signature)


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")


def _is_secure_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto.split(",", 1)[0].strip() == "https"


def _invalid_session() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效")
