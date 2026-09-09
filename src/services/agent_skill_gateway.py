"""Narrow admin connection for reading Skills and replacing managed Agent allowlists."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from websockets.asyncio.client import connect

from .openclaw_relay.directory import skills_payload
from .openclaw_relay.identity import connect_params
from .openclaw_relay.settings import configuration

ADMIN_TOKEN_ENV = "HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN"
ADMIN_SCOPES = ["operator.admin"]


class AgentSkillGatewayError(RuntimeError):
    pass


class AgentSkillGateway:
    def __init__(self, secret_store, data_dir: Path):
        self.secret_store = secret_store
        self.data_dir = Path(data_dir)

    def _credentials(self):
        url, _ = configuration()
        token = self.secret_store.read().get(ADMIN_TOKEN_ENV) or os.getenv(ADMIN_TOKEN_ENV, "")
        if not token.strip():
            raise AgentSkillGatewayError("Skill admin credential is unavailable")
        return url, token

    async def _session(self, operation):
        url, token = self._credentials()
        device_dir = self.data_dir / "openclaw-relay" / "skill-admin"
        device_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        async with connect(url, proxy=None, open_timeout=15, close_timeout=5, max_size=2 * 1024 * 1024) as socket:
            challenge = json.loads(await asyncio.wait_for(socket.recv(), 15))
            nonce = challenge.get("payload", {}).get("nonce")
            if challenge.get("event") != "connect.challenge" or not isinstance(nonce, str):
                raise AgentSkillGatewayError("Gateway admin handshake failed")
            await socket.send(json.dumps({"type": "req", "id": "connect", "method": "connect",
                                          "params": connect_params(device_dir, token, nonce, scopes=ADMIN_SCOPES)}))
            hello = await self._response(socket, "connect")
            scopes = hello.get("auth", {}).get("scopes", [])
            if scopes != ADMIN_SCOPES:
                raise AgentSkillGatewayError("Gateway returned unexpected admin scope")
            return await operation(socket, hello)

    @staticmethod
    async def _response(socket, request_id):
        for _ in range(64):
            frame = json.loads(await asyncio.wait_for(socket.recv(), 20))
            if frame.get("type") != "res" or frame.get("id") != request_id:
                continue
            if not frame.get("ok") or not isinstance(frame.get("payload"), dict):
                raise AgentSkillGatewayError("Gateway admin request failed")
            return frame["payload"]
        raise AgentSkillGatewayError("Gateway admin response unavailable")

    @staticmethod
    async def _request(socket, request_id, method, params):
        await socket.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}))
        return await AgentSkillGateway._response(socket, request_id)

    async def _catalog(self, agent_id):
        async def operation(socket, hello):
            if "skills.status" not in hello.get("features", {}).get("methods", []):
                raise AgentSkillGatewayError("Gateway does not support Skills status")
            payload = await self._request(socket, "skills", "skills.status", {"agentId": agent_id})
            return skills_payload(payload)["skills"]
        return await self._session(operation)

    def catalog(self, agent_id: str):
        try:
            return asyncio.run(asyncio.wait_for(self._catalog(agent_id), 45))
        except AgentSkillGatewayError:
            raise
        except Exception as error:
            raise AgentSkillGatewayError("Gateway Skill catalog is unavailable") from error

    async def _sync(self, agent_ids, allowed_skill_keys):
        async def operation(socket, hello):
            methods = hello.get("features", {}).get("methods", [])
            if "config.get" not in methods or "config.patch" not in methods:
                raise AgentSkillGatewayError("Gateway does not support config synchronization")
            current = await self._request(socket, "config-get", "config.get", {})
            config, base_hash = current.get("config"), current.get("hash")
            entries = config.get("agents", {}).get("entries", {}) if isinstance(config, dict) else {}
            if not isinstance(base_hash, str) or any(agent_id not in entries for agent_id in agent_ids):
                raise AgentSkillGatewayError("Managed Agent configuration changed")
            patch = {"agents": {"entries": {agent_id: {"skills": allowed_skill_keys} for agent_id in agent_ids}}}
            await self._request(socket, "config-patch", "config.patch", {
                "raw": json.dumps(patch, separators=(",", ":")), "baseHash": base_hash,
                "replacePaths": [f"agents.entries.{agent_id}.skills" for agent_id in agent_ids],
                "note": "Inteliscope workspace Skill policy synchronization",
            })
            verified = await self._request(socket, "config-verify", "config.get", {})
            verify_entries = verified.get("config", {}).get("agents", {}).get("entries", {})
            if any(verify_entries.get(agent_id, {}).get("skills") != allowed_skill_keys for agent_id in agent_ids):
                raise AgentSkillGatewayError("Gateway Skill policy verification failed")
        return await self._session(operation)

    def sync(self, agent_ids: list[str], allowed_skill_keys: list[str]):
        if not agent_ids:
            return
        try:
            return asyncio.run(asyncio.wait_for(self._sync(agent_ids, allowed_skill_keys), 60))
        except AgentSkillGatewayError:
            raise
        except Exception as error:
            raise AgentSkillGatewayError("Gateway Skill synchronization is unavailable") from error
