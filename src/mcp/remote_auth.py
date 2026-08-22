"""Opaque delegation-token authentication for Remote MCP."""

from __future__ import annotations

from datetime import datetime

from mcp.server.auth.provider import AccessToken, TokenVerifier

from ..storage.service_store import ServiceStore


class AgentDelegationTokenVerifier(TokenVerifier):
    """Resolve one opaque bearer token to its own user and workspace."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = self.store.authenticate_agent_delegation(token)
        if principal is None:
            return None
        return AccessToken(
            token=principal["delegation_id"],
            client_id=f"openclaw:{principal['delegation_id']}",
            scopes=principal["scopes"],
            expires_at=int(datetime.fromisoformat(principal["expires_at"]).timestamp()),
        )
