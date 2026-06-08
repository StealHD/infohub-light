"""Small env-driven auth helpers for the local radar web UI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any


COOKIE_NAME = "horizon_session"
HASH_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 260_000
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


@dataclass(frozen=True)
class AuthSettings:
    """Environment-derived settings for config/admin auth."""

    enabled: bool
    username: str
    password: str | None
    password_hash: str | None
    session_secret: str | None
    cookie_secure: bool
    session_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "AuthSettings":
        ttl_raw = os.getenv("HORIZON_AUTH_SESSION_TTL_SECONDS", "")
        try:
            ttl = int(ttl_raw) if ttl_raw else DEFAULT_SESSION_TTL_SECONDS
        except ValueError:
            ttl = DEFAULT_SESSION_TTL_SECONDS
        return cls(
            enabled=_truthy(os.getenv("HORIZON_AUTH_ENABLED")),
            username=os.getenv("HORIZON_AUTH_USER", "admin").strip() or "admin",
            password=os.getenv("HORIZON_AUTH_PASSWORD") or None,
            password_hash=os.getenv("HORIZON_AUTH_PASSWORD_HASH") or None,
            session_secret=os.getenv("HORIZON_AUTH_SESSION_SECRET") or None,
            cookie_secure=_truthy(os.getenv("HORIZON_AUTH_SECURE_COOKIE")),
            session_ttl_seconds=max(300, ttl),
        )

    @property
    def configured(self) -> bool:
        return bool(self.password_hash or self.password)

    @property
    def signing_secret(self) -> str:
        return self.session_secret or self.password_hash or self.password or "disabled-auth"


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return a PBKDF2-SHA256 hash suitable for HORIZON_AUTH_PASSWORD_HASH."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password_hash(password: str, stored_hash: str) -> bool:
    """Verify a PBKDF2-SHA256 password hash."""
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != HASH_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def verify_login(settings: AuthSettings, username: str, password: str) -> bool:
    """Return whether supplied credentials match the configured admin account."""
    if not settings.enabled or not settings.configured:
        return False
    if not hmac.compare_digest(username, settings.username):
        return False
    if settings.password_hash:
        return verify_password_hash(password, settings.password_hash)
    return hmac.compare_digest(password, settings.password or "")


def _sign(settings: AuthSettings, payload: str) -> str:
    return _b64encode(
        hmac.new(
            settings.signing_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    )


def create_session_token(
    settings: AuthSettings,
    username: str,
    *,
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "u": username,
        "exp": issued_at + settings.session_ttl_seconds,
        "iat": issued_at,
    }
    payload_text = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    return f"{payload_text}.{_sign(settings, payload_text)}"


def verify_session_token(
    settings: AuthSettings,
    token: str | None,
    *,
    now: int | None = None,
) -> str | None:
    if not settings.enabled:
        return settings.username
    if not settings.configured or not token or "." not in token:
        return None
    payload_text, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(settings, payload_text), signature):
        return None
    try:
        payload = json.loads(_b64decode(payload_text).decode("utf-8"))
    except Exception:
        return None
    expires_at = int(payload.get("exp") or 0)
    if expires_at < int(now if now is not None else time.time()):
        return None
    username = str(payload.get("u") or "")
    return username if hmac.compare_digest(username, settings.username) else None


def session_cookie_header(settings: AuthSettings, token: str) -> str:
    parts = [
        f"{COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={settings.session_ttl_seconds}",
    ]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie_header(settings: AuthSettings) -> str:
    parts = [
        f"{COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def session_token_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else None


def auth_status(settings: AuthSettings, username: str | None) -> dict[str, Any]:
    return {
        "auth_enabled": settings.enabled,
        "auth_configured": settings.configured,
        "authenticated": bool(username) if settings.enabled else True,
        "username": username or "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Horizon web auth helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    hash_parser = subparsers.add_parser("hash-password", help="create PBKDF2 password hash")
    hash_parser.add_argument("password")
    args = parser.parse_args()

    if args.command == "hash-password":
        print(hash_password(args.password))


if __name__ == "__main__":
    main()
