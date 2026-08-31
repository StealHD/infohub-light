"""Bounded account-plan compatibility signals from public Actor documentation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


ACCOUNT_FIT_COMPATIBLE = 0
ACCOUNT_FIT_CONSTRAINED = 1
ACCOUNT_FIT_INCOMPATIBLE = 2
_MAX_README_BYTES = 64 * 1024

_FREE_API_RESTRICTED = re.compile(
    r"(?:free users?|users? on (?:the )?free plan).{0,180}"
    r"(?:cannot|can not|not allowed to).{0,100}(?:via api|use (?:the )?api)",
)
_FREE_DEMO_ONLY = re.compile(
    r"(?:free users?|users? on (?:the )?free plan).{0,180}"
    r"(?:only in demo mode|demo mode only)",
)
_FREE_RUN_LIMIT = re.compile(
    r"(?:free users?|users? on (?:the )?free plan).{0,180}"
    r"(?:limited to|up to|maximum of|max(?:imum)?).{0,80}"
    r"(?:runs?|times?).{0,40}(?:per|a) month",
)
_FREE_ITEM_LIMIT = re.compile(
    r"(?:free users?|users? on (?:the )?free plan).{0,240}"
    r"(?:capped|limited|maximum|max(?:imum)?).{0,80}(?:items?|results?|rows?)",
)
_MONITORING_RESTRICTED = re.compile(
    r"(?:\bno monitoring\b|(?:do not|don t|not intended to)"
    r".{0,100}(?:same query|monitor(?:ing)?).{0,100}"
    r"(?:short intervals?|repeatedly|recurring))",
)
_MINIMUM_RESULT_VOLUME = re.compile(
    r"(?:minimum (?:requirement|of)?|must return at least)"
    r".{0,80}\d{1,6}.{0,30}(?:tweets?|items?|results?|rows?)"
    r"(?:.{0,40}per query)?",
)


@dataclass(frozen=True, slots=True)
class ActorAccountFit:
    rank: int = ACCOUNT_FIT_COMPATIBLE
    reason_code: str | None = None


def normalize_account_tier(value: object) -> str:
    tier = str(value or "").strip().upper()
    return tier[:32] if tier.isascii() and tier.replace("_", "").isalnum() else "UNKNOWN"


def actor_account_fit(readme: object, *, account_tier: object) -> ActorAccountFit:
    """Return a demotion rank without retaining or exposing README text."""

    text = _readme_text(readme)
    if not text:
        return ActorAccountFit()
    tier = normalize_account_tier(account_tier)
    if tier == "FREE":
        if _FREE_API_RESTRICTED.search(text):
            return ActorAccountFit(
                ACCOUNT_FIT_INCOMPATIBLE,
                "actorops_candidate_free_api_restricted",
            )
        if _FREE_DEMO_ONLY.search(text):
            return ActorAccountFit(
                ACCOUNT_FIT_INCOMPATIBLE,
                "actorops_candidate_free_demo_only",
            )
        if _FREE_RUN_LIMIT.search(text):
            return ActorAccountFit(
                ACCOUNT_FIT_INCOMPATIBLE,
                "actorops_candidate_free_run_limited",
            )
    if _MONITORING_RESTRICTED.search(text):
        return ActorAccountFit(
            ACCOUNT_FIT_INCOMPATIBLE,
            "actorops_candidate_monitoring_restricted",
        )
    if tier == "FREE" and _FREE_ITEM_LIMIT.search(text):
        return ActorAccountFit(
            ACCOUNT_FIT_CONSTRAINED,
            "actorops_candidate_free_item_limited",
        )
    if _MINIMUM_RESULT_VOLUME.search(text):
        return ActorAccountFit(
            ACCOUNT_FIT_CONSTRAINED,
            "actorops_candidate_minimum_volume",
        )
    return ActorAccountFit()


def _readme_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    encoded = value.encode("utf-8")[:_MAX_README_BYTES]
    bounded = encoded.decode("utf-8", errors="ignore")
    normalized = unicodedata.normalize("NFKC", bounded).casefold()
    normalized = normalized.replace("'", " ").replace("’", " ")
    normalized = re.sub(r"[*_`>#\[\](){}|]", " ", normalized)
    return " ".join(normalized.split())


__all__ = [
    "ACCOUNT_FIT_COMPATIBLE",
    "ACCOUNT_FIT_CONSTRAINED",
    "ACCOUNT_FIT_INCOMPATIBLE",
    "ActorAccountFit",
    "actor_account_fit",
    "normalize_account_tier",
]
