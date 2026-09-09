"""Owner/Admin Skill catalog and workspace authorization policy routes."""

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.agent_skill_access import AgentSkillAccess, AgentSkillPolicyError
from ..services.agent_skill_gateway import AgentSkillGateway, AgentSkillGatewayError

MUTATION_OPERATION_ROUTES = {
    ("PUT", "/api/admin/agent-skills/policy"): ("agent", "skill_policy_update"),
}


class AgentSkillPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)
    allowed_skill_keys: list[str] = Field(max_length=256)


def _public_policy(policy):
    result = {key: policy[key] for key in (
        "revision", "allowed_skill_keys", "sync_state", "sync_error_code", "updated_at", "synced_at"
    )}
    result["sync_in_progress"] = bool(policy.get("sync_attempt_id"))
    return result


def _error(error):
    if isinstance(error, AgentSkillPolicyError):
        status = 409 if error.code == "agent_skill_policy_conflict" else 400
        if error.code == "agent_skill_policy_migration_required":
            status = 503
        return ApiError(error.code, str(error), status_code=status, retryable=status >= 500)
    return ApiError("agent_skill_gateway_unavailable", "Gateway Skill 管理连接当前不可用。", status_code=503,
                    retryable=True, action="检查管理员凭据、Gateway 状态后重试。")


async def list_agent_skills(
    response: Response,
    user=Depends(current_admin),
    context: ApiContext = Depends(api_context),
):
    access = AgentSkillAccess(context.store)
    try:
        policy = await run_in_threadpool(access.policy, str(user["workspace_id"]))
        bindings = await run_in_threadpool(access.active_bindings, str(user["workspace_id"]))
        catalog = [] if not bindings else await run_in_threadpool(
            AgentSkillGateway(context.secret_values, context.data_path).catalog, bindings[0]["agent_id"]
        )
    except (AgentSkillPolicyError, AgentSkillGatewayError) as error:
        raise _error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return ok({"policy": _public_policy(policy), "skills": catalog})


async def update_agent_skill_policy(payload: AgentSkillPolicyRequest, response: Response,
                                    user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    access = AgentSkillAccess(context.store)
    workspace_id = str(user["workspace_id"])
    policy = None
    bindings = []
    try:
        bindings = await run_in_threadpool(access.active_bindings, workspace_id)
        gateway = AgentSkillGateway(context.secret_values, context.data_path)
        catalog = [] if not bindings else await run_in_threadpool(gateway.catalog, bindings[0]["agent_id"])
        if not set(payload.allowed_skill_keys).issubset({item["skillKey"] for item in catalog}):
            raise AgentSkillPolicyError("invalid_skill_policy", "Skill selection includes unknown keys")
        policy = await run_in_threadpool(
            access.prepare, workspace_id, expected_revision=payload.expected_revision,
            allowed_skill_keys=payload.allowed_skill_keys,
        )
        await run_in_threadpool(
            gateway.sync,
            [item["agent_id"] for item in bindings], policy["allowed_skill_keys"],
        )
        policy = await run_in_threadpool(
            access.finish, workspace_id, revision=policy["revision"],
            attempt_id=policy["sync_attempt_id"],
            binding_ids=[item["binding_id"] for item in bindings],
        )
    except AgentSkillGatewayError as error:
        if policy is not None:
            await run_in_threadpool(
                access.finish, workspace_id, revision=policy["revision"],
                attempt_id=policy["sync_attempt_id"],
                binding_ids=[item["binding_id"] for item in bindings], error_code="gateway_sync_failed",
            )
        raise _error(error) from error
    except AgentSkillPolicyError as error:
        raise _error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return ok({"policy": _public_policy(policy)})


def register_agent_skill_routes(app: FastAPI):
    app.add_api_route("/api/admin/agent-skills", list_agent_skills, methods=["GET"])
    app.add_api_route("/api/admin/agent-skills/policy", update_agent_skill_policy, methods=["PUT"])
