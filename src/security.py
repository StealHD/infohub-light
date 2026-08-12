"""Bounded credential classification shared by public projections and storage.

The helpers in this module classify non-persistent copies only.  They never
rewrite or return caller data, and every normalization or URL parsing failure
is treated as sensitive so callers can fail closed with their own constant
error or opaque projection.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit


SECURITY_CLASSIFICATION_MAX_CHARS = 16_384
SECURITY_PERCENT_DECODE_ROUNDS = 2

_DEFAULT_IGNORABLE_RANGES = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFFA0, 0xFFA0),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)

_SENSITIVE_KEY_NAMES = {
    "api_key",
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "header",
    "headers",
    "key",
    "password",
    "secret",
    "secret_env",
    "signature",
    "token",
    "token_env",
}
_SENSITIVE_COMPACT_KEYS = {
    "accesskey",
    "accesstoken",
    "apikey",
    "authtoken",
    "clientkey",
    "clientsecret",
    "clienttoken",
    "privatekey",
    "proxyauthorization",
    "refreshtoken",
    "secretenv",
    "sessiontoken",
    "setcookie",
    "tokenenv",
    "xapikey",
}
_SENSITIVE_COMPACT_SUFFIXES = (
    "authorization",
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "password",
    "secret",
    "signature",
    "token",
)
_SENSITIVE_QUERY_PARTS = (
    "token",
    "key",
    "secret",
    "auth",
    "password",
    "signature",
    "credential",
)

_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9_-]+)\s*[:=]\s*\S+"
)
_KNOWN_CREDENTIAL_VALUE_RE = re.compile(
    r"(?<![a-z0-9_-])(?:"
    r"AIza[a-z0-9_-]{35}"
    r"|gsk_[a-z0-9]{32,}"
    r"|hf_[a-z0-9]{32,}"
    r"|ghp_[a-z0-9]{8,}"
    r"|github_pat_[a-z0-9_]{8,}"
    r"|xox[a-z]-[a-z0-9-]{8,}"
    r"|sk-proj-[a-z0-9_-]{20,}"
    r"|sk-[a-z0-9]{32,}"
    r"|sk_[a-z0-9_-]{20,}"
    r"|xai-[a-z0-9_-]{20,}"
    r"|tp-[a-z0-9_-]{20,}"
    r"|ih_mcp_v1_[a-z0-9_-]{8,}"
    r")(?![a-z0-9_-])"
    r"|(?<![a-z0-9_-])eyj[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}"
    r"\.[a-z0-9_-]{8,}(?![a-z0-9_-])",
    flags=re.IGNORECASE,
)


def classification_copies(value: str) -> tuple[str, ...] | None:
    """Return bounded NFKC copies with no more than two percent decodes."""

    try:
        if not isinstance(value, str) or len(value) > SECURITY_CLASSIFICATION_MAX_CHARS:
            return None
        copies: list[str] = []
        candidate = value
        for decode_round in range(SECURITY_PERCENT_DECODE_ROUNDS + 1):
            candidate = unicodedata.normalize("NFKC", candidate)
            if len(candidate) > SECURITY_CLASSIFICATION_MAX_CHARS:
                return None
            candidate = "".join(
                character
                for character in candidate
                if unicodedata.category(character) != "Cf"
                and not any(
                    start <= ord(character) <= end
                    for start, end in _DEFAULT_IGNORABLE_RANGES
                )
            )
            if len(candidate) > SECURITY_CLASSIFICATION_MAX_CHARS:
                return None
            if not copies or candidate != copies[-1]:
                copies.append(candidate)
            if decode_round == SECURITY_PERCENT_DECODE_ROUNDS or "%" not in candidate:
                break
            decoded = unquote(candidate, errors="replace")
            if len(decoded) > SECURITY_CLASSIFICATION_MAX_CHARS:
                return None
            if decoded == candidate:
                break
            candidate = decoded
        return tuple(copies)
    except Exception:
        return None


def _normalized_key(value: str) -> str:
    candidate = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    candidate = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", candidate)
    return re.sub(r"[^a-z0-9]+", "_", candidate.casefold()).strip("_")


def _classified_sensitive_credential_key(value: str) -> bool:
    normalized = _normalized_key(value)
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    compact = normalized.replace("_", "")
    if compact in _SENSITIVE_COMPACT_KEYS:
        return True
    if compact.endswith(_SENSITIVE_COMPACT_SUFFIXES):
        return True
    parts = normalized.split("_")
    return any(
        part
        in {
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
            "token",
        }
        for part in parts
    ) or normalized.endswith("_api_key")


def is_sensitive_credential_key(value: Any) -> bool:
    """Classify a mapping key or complete credential label."""

    try:
        copies = classification_copies(str(value))
    except Exception:
        return True
    if copies is None:
        return True
    return any(_classified_sensitive_credential_key(copy) for copy in copies)


def _classified_sensitive_query_name(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return any(marker in normalized for marker in _SENSITIVE_QUERY_PARTS)


def _classified_text_contains_credential(value: str) -> bool:
    if _KNOWN_CREDENTIAL_VALUE_RE.search(value):
        return True
    return any(
        _classified_sensitive_credential_key(match.group(1))
        for match in _CREDENTIAL_ASSIGNMENT_RE.finditer(value)
    )


def text_contains_credential(value: str) -> bool:
    """Classify free text using explicit assignments and known token shapes."""

    copies = classification_copies(value)
    if copies is None:
        return True
    try:
        return any(_classified_text_contains_credential(copy) for copy in copies)
    except Exception:
        return True


def _classified_query_value_contains_credential(value: str) -> bool:
    return _classified_sensitive_credential_key(
        value
    ) or _classified_text_contains_credential(value)


def url_contains_credentials(value: str) -> bool:
    """Check userinfo, query names/values, and fragments on bounded copies."""

    copies = classification_copies(value)
    if copies is None:
        return True
    try:
        for copy in copies:
            parsed = urlsplit(copy)
            if parsed.username is not None or parsed.password is not None:
                return True
            for field in parsed.query.split("&") if parsed.query else ():
                name, separator, query_value = field.partition("=")
                if _classified_sensitive_query_name(
                    name
                ) or _classified_text_contains_credential(name):
                    return True
                if separator and _classified_query_value_contains_credential(
                    query_value
                ):
                    return True
            if parsed.fragment and _classified_query_value_contains_credential(
                parsed.fragment
            ):
                return True
        return False
    except Exception:
        return True


def public_data_contains_credentials(value: Any) -> bool:
    """Recursively classify public JSON-like metadata without rewriting it."""

    try:
        if isinstance(value, dict):
            return any(
                is_sensitive_credential_key(key)
                or text_contains_credential(str(key))
                or public_data_contains_credentials(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple, set)):
            return any(public_data_contains_credentials(item) for item in value)
        if isinstance(value, str):
            return text_contains_credential(value) or url_contains_credentials(value)
        return False
    except Exception:
        return True
