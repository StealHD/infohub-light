"""Public Bilibili acquisition state and pre-queue checks without external calls."""

from .responses import ApiError
from ..services.bilibili_actor_source import is_bilibili_record
from ..services.actorops.binding_service import ActorOpsBindingService
from ..services.actorops.repository import ActorOpsNotFound
from ..services.actorops.readiness import require_actorops_v2_schema


def public_bilibili_source_additions(store, source):
    if not is_bilibili_record(source):
        return {}
    status, allowed, reason = "unbound", False, "actorops_v2_binding_missing"
    try:
        require_actorops_v2_schema(store)
        state = ActorOpsBindingService(store, workspace_id=source["workspace_id"]).execution_state(source["id"])
        status, allowed, reason = state.binding_status, state.allowed, state.reason
        if allowed and not source["enabled"]:
            allowed, reason = False, "source_disabled"
    except ActorOpsNotFound:
        pass
    except RuntimeError:
        status, reason = "unavailable", "actorops_v2_unavailable"
    return {"setup_type": "bilibili", "acquisition": {
        "provider": "apify", "status": status, "allowed": allowed, "reason": reason,
    }}


def catalog_sources_for_user(store, user, *, include_disabled=False):
    sources = store.list_visible_sources(user, include_disabled=True)
    if include_disabled:
        return sources
    subscribed = {row["source_id"] for row in store.list_user_subscriptions(user["id"])}
    return [source for source in sources if source["enabled"] or (
        source["id"] in subscribed and is_bilibili_record(source)
    )]


def require_source_job_access(store, source_id, user):
    source = next((row for row in store.list_visible_sources(user, include_disabled=True)
                   if row["id"] == source_id), None)
    if source is None or (not source["enabled"] and not is_bilibili_record(source)):
        raise ApiError("not_found", "source not found", status_code=404)
    additions = public_bilibili_source_additions(store, source)
    acquisition = additions.get("acquisition")
    if acquisition and not acquisition["allowed"]:
        status = acquisition["status"]
        message = ("Bilibili 来源已停用。" if status == "disabled" or acquisition["reason"] == "source_disabled"
                   else "ActorOps 当前不可用，请联系管理员恢复服务。" if status == "unavailable"
                   else "Bilibili 主备路线尚未就绪，正在等待 Actor 验证。")
        action = ("请在 ActorOps 完成主备验证并启用 Bilibili 路线后重试。"
                  if user.get("role") in {"owner", "admin"}
                  else "请联系管理员在 ActorOps 完成 Bilibili 主备配置。")
        raise ApiError(acquisition["reason"], message, status_code=409, retryable=False, action=action)
    return source
