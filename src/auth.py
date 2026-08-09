"""Authentication primitives shared by the Service API and store."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass


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
    """Environment-derived settings for database-backed Service sessions."""

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
            cookie_secure=_truthy(os.getenv("HORIZON_AUTH_SECURE_COOKIE")),
            session_ttl_seconds=max(300, ttl),
        )


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return a PBKDF2-SHA256 password hash for Service users."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password_hash(password: str, stored_hash: str) -> bool:
    """Verify a Service user's PBKDF2-SHA256 password hash."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Service password hash helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    hash_parser = subparsers.add_parser("hash-password", help="create a PBKDF2 password hash")
    hash_parser.add_argument("password", nargs="?", help="omit to read without echo")
    args = parser.parse_args()
    if args.command == "hash-password":
        password = args.password if args.password is not None else getpass.getpass("Password: ")
        print(hash_password(password))


if __name__ == "__main__":
    main()
