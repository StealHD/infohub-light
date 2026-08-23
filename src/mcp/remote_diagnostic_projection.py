"""Stable response projection for Remote MCP diagnostics."""

from __future__ import annotations

from typing import Any


_CAUSE_COPY = {
    "auth_missing": ("认证信息缺失或无效", "来源认证未通过，请在 Web 中检查密钥配置", False),
    "rate_limited": ("上游请求受限", "上游限制了请求频率，请稍后再试", True),
    "network_timeout": ("上游连接超时", "连接上游时超时或网络不可用", True),
    "upstream_rejected": ("上游拒绝请求", "上游未接受本次请求", True),
    "invalid_source_config": ("来源配置无效", "来源配置未通过校验", False),
    "source_disabled": ("来源已停用", "该来源当前处于停用状态", False),
    "subscription_disabled": ("订阅已停用", "该订阅当前处于停用状态", False),
    "schedule_blocked": ("自动计划受阻", "自动抓取计划当前未能继续执行", False),
    "worker_unavailable": ("Worker 当前不可用", "没有可用的 Worker 处理该任务", True),
    "no_items": ("本次未获取到条目", "最近一次成功尝试没有获取到新条目", True),
    "unknown": ("原因未知", "现有记录不足以确定原因", False),
}

_ACTION_BY_CATEGORY = {
    "auth_missing": {
        "code": "check_secret_in_web",
        "mode": "web",
        "label": "在 Web 中检查密钥配置",
    },
    "rate_limited": {
        "code": "wait_for_rate_limit",
        "mode": "wait",
        "label": "等待上游限流窗口恢复",
    },
    "network_timeout": {
        "code": "wait_and_review_target",
        "mode": "wait",
        "label": "稍后重试并检查来源可达性",
    },
    "upstream_rejected": {
        "code": "review_upstream_response",
        "mode": "wait",
        "label": "稍后重试或检查上游状态",
    },
    "invalid_source_config": {
        "code": "review_source_config",
        "mode": "prepare_change",
        "label": "检查来源配置并准备变更",
    },
    "source_disabled": {
        "code": "review_source_enabled",
        "mode": "prepare_change",
        "label": "检查是否需要启用来源",
    },
    "subscription_disabled": {
        "code": "review_subscription_enabled",
        "mode": "prepare_change",
        "label": "检查是否需要启用订阅",
    },
    "schedule_blocked": {
        "code": "review_schedule",
        "mode": "prepare_change",
        "label": "检查自动抓取计划",
    },
    "worker_unavailable": {
        "code": "contact_worker_admin",
        "mode": "contact_admin",
        "label": "联系管理员检查 Worker 状态",
    },
    "no_items": {
        "code": "wait_for_new_items",
        "mode": "wait",
        "label": "等待来源发布新条目",
    },
    "unknown": {
        "code": "contact_admin_for_evidence",
        "mode": "contact_admin",
        "label": "联系管理员获取更多运行证据",
    },
}


def diagnostic_response(
    *,
    kind: str,
    target_id: str,
    name: str,
    status: str,
    category: str,
    code: str | None,
    confidence: str,
    evidence: list[dict[str, Any]],
    related_job_id: str | None,
) -> dict[str, Any]:
    title, message, retryable = _CAUSE_COPY[category]
    return {
        "target": {"kind": kind, "id": target_id, "name": name},
        "status": status,
        "cause": {
            "category": category,
            "code": code,
            "title": title,
            "message": message,
            "confidence": confidence,
            "retryable": retryable,
        },
        "evidence": evidence,
        "suggested_actions": [dict(_ACTION_BY_CATEGORY[category])],
        "related_job_id": related_job_id,
    }
