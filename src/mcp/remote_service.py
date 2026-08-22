"""Explicit compatibility facade for user-scoped Remote MCP reads."""

from __future__ import annotations

from typing import Any

from ..storage.service_store import ServiceStore
from .remote_feed_read import RemoteMCPFeedReadService
from .remote_job_read import RemoteMCPJobReadService
from .remote_read_projection import RemoteMCPNotFound, safe_job_result_summary
from .remote_subscription_read import RemoteMCPSubscriptionReadService


__all__ = [
    "RemoteMCPNotFound",
    "RemoteMCPReadService",
    "safe_job_result_summary",
]


class RemoteMCPReadService:
    """Compose focused Feed, subscription/health, and Job read services."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store
        self.feed = RemoteMCPFeedReadService(store)
        self.subscriptions = RemoteMCPSubscriptionReadService(store)
        self.jobs = RemoteMCPJobReadService(store)

    def get_my_feed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        collection: str = "latest",
        limit: int = 20,
        offset: int = 0,
        hide_ignored: bool = True,
        unread_first: bool = True,
    ) -> dict[str, Any]:
        return self.feed.get_my_feed(
            workspace_id=workspace_id,
            user_id=user_id,
            collection=collection,
            limit=limit,
            offset=offset,
            hide_ignored=hide_ignored,
            unread_first=unread_first,
        )

    def get_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
        body_offset: int = 0,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        return self.feed.get_item(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id=article_id,
            body_offset=body_offset,
            max_body_chars=max_body_chars,
        )

    def list_subscriptions(
        self,
        *,
        workspace_id: str,
        user_id: str,
        include_disabled: bool = True,
    ) -> dict[str, Any]:
        return self.subscriptions.list_subscriptions(
            workspace_id=workspace_id,
            user_id=user_id,
            include_disabled=include_disabled,
        )

    def source_health(self, *, workspace_id: str, user_id: str) -> dict[str, Any]:
        return self.subscriptions.source_health(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    def list_jobs(
        self,
        *,
        workspace_id: str,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.jobs.list_jobs(
            workspace_id=workspace_id,
            user_id=user_id,
            status=status,
            limit=limit,
        )

    def get_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        return self.jobs.get_job(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
        )
