"""User-scoped Feed translation endpoints."""

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_user, require_mutating_member
from ..services.content_translation import ContentTranslationService
from ..services.content_translation_input import TranslationError
from ..services.quota import QuotaExceeded


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def invoke(operation):
    try:
        return ok(operation())
    except TranslationError as exc:
        raise ApiError(exc.code, exc.message, status_code=exc.status_code, retryable=False) from None
    except QuotaExceeded:
        raise ApiError("quota_exceeded", "AI 额度不足，请稍后重试。", status_code=429) from None


def get_translation(article_id: str, user=Depends(current_user), context: ApiContext=Depends(api_context)):
    return invoke(lambda: ContentTranslationService(context.store).get(user, article_id))


def request_translation(article_id: str, body: TranslationRequest,
                        user=Depends(current_user), context: ApiContext=Depends(api_context)):
    require_mutating_member(user)
    return invoke(lambda: ContentTranslationService(context.store).request(user, article_id, body.request_id))


def register(app):
    path = "/api/feed/items/{article_id}/translation"
    app.add_api_route(path, get_translation, methods=["GET"])
    app.add_api_route(path, request_translation, methods=["POST"])
