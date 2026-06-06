"""Controlled tag taxonomy for the private AI radar."""

from __future__ import annotations

import re
from typing import Iterable


CANONICAL_TAGS: tuple[str, ...] = (
    "AI Agent",
    "AI 编程",
    "模型发布",
    "RAG/MCP",
    "AI Infra",
    "开源模型",
    "推理框架",
    "产品创业",
    "研究论文",
    "安全治理",
    "行业动态",
)


def _key(value: object) -> str:
    return re.sub(r"[\s_\\/#:：,，.\-]+", "", str(value or "").strip().lstrip("#").lower())


_ALIASES: dict[str, str] = {
    # AI agents / automation
    "aiagent": "AI Agent",
    "agent": "AI Agent",
    "agents": "AI Agent",
    "llm代理": "AI Agent",
    "智能体": "AI Agent",
    "自动化": "AI Agent",
    "computeruse": "AI Agent",
    "计算机使用": "AI Agent",
    # AI coding
    "ai编程": "AI 编程",
    "aicoding": "AI 编程",
    "coding": "AI 编程",
    "codex": "AI 编程",
    "claudecode": "AI 编程",
    "cursor": "AI 编程",
    "devin": "AI 编程",
    "vscode": "AI 编程",
    "workflow": "AI 编程",
    "ai编程工具": "AI 编程",
    "开发工具": "AI 编程",
    "开发者工具": "AI 编程",
    "代码理解": "AI 编程",
    "工具优化": "AI 编程",
    "python": "AI 编程",
    # Model releases / major labs
    "模型发布": "模型发布",
    "大模型": "模型发布",
    "modelrelease": "模型发布",
    "llm": "模型发布",
    "openai": "模型发布",
    "anthropic": "模型发布",
    "googledeepmind": "模型发布",
    "deepmind": "模型发布",
    "metaai": "模型发布",
    "chatgpt": "模型发布",
    "gpt": "模型发布",
    "maimodels": "模型发布",
    # RAG / MCP / tool use
    "ragmcp": "RAG/MCP",
    "rag": "RAG/MCP",
    "mcp": "RAG/MCP",
    "tooluse": "RAG/MCP",
    "工具调用": "RAG/MCP",
    "longcontext": "RAG/MCP",
    "长上下文": "RAG/MCP",
    "mcp服务器": "RAG/MCP",
    # AI infra
    "aiinfra": "AI Infra",
    "aiinfrastructure": "AI Infra",
    "infra": "AI Infra",
    "ai基础设施": "AI Infra",
    "基础设施": "AI Infra",
    "token优化": "AI Infra",
    "数据加密": "AI Infra",
    "知识图谱": "AI Infra",
    # Open models
    "开源模型": "开源模型",
    "openmodel": "开源模型",
    "opensource": "开源模型",
    "opensourcemodel": "开源模型",
    "localllm": "开源模型",
    "本地ai": "开源模型",
    "本地部署": "开源模型",
    "vlm": "开源模型",
    "unsloth": "开源模型",
    # Inference frameworks
    "推理框架": "推理框架",
    "inference": "推理框架",
    "serving": "推理框架",
    "vllm": "推理框架",
    "ollama": "推理框架",
    "量化": "推理框架",
    # Products / startups
    "产品创业": "产品创业",
    "创业产品": "产品创业",
    "startup": "产品创业",
    "product": "产品创业",
    "ai产品": "产品创业",
    "ai市场": "产品创业",
    "用户增长": "产品创业",
    "webui": "产品创业",
    # Research
    "研究论文": "研究论文",
    "论文": "研究论文",
    "paper": "研究论文",
    "research": "研究论文",
    "alignment": "研究论文",
    # Safety / governance
    "安全治理": "安全治理",
    "安全": "安全治理",
    "治理": "安全治理",
    "policy": "安全治理",
    "合规": "安全治理",
    "商业滥用": "安全治理",
    "安全漏洞": "安全治理",
    "平台治理": "安全治理",
    "账号安全": "安全治理",
    # Industry / ecosystem
    "行业动态": "行业动态",
    "公司动态": "行业动态",
    "社区讨论": "行业动态",
    "社区反馈": "行业动态",
    "github": "行业动态",
    "github趋势": "行业动态",
    "收购猜测": "行业动态",
    "汽车软件": "行业动态",
    "特斯拉": "行业动态",
    "行车记录仪": "行业动态",
    "软件更新": "行业动态",
    "里程碑": "行业动态",
}

for _tag in CANONICAL_TAGS:
    _ALIASES[_key(_tag)] = _tag


def clean_custom_tag(value: object) -> str:
    """Return a safe custom tag label for the user-maintained tag library."""
    tag = re.sub(r"\s+", " ", str(value or "").strip().lstrip("#").strip())
    if not tag:
        raise ValueError("标签不能为空")
    if len(tag) > 32:
        raise ValueError("标签长度不能超过 32 个字符")
    if re.search(r"[,，\n\r\t<>$`{}]", tag):
        raise ValueError("标签不能包含逗号、换行或特殊符号")
    return tag


def _allowed_tag_map(allowed_tags: Iterable[object] | None) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for value in allowed_tags or []:
        raw = str(value or "").strip().lstrip("#").strip()
        if not raw:
            continue
        canonical = canonical_tag(raw)
        tag = canonical or raw
        allowed[_key(tag)] = tag
    return allowed


def canonical_tag(value: object) -> str | None:
    """Return the canonical tag for a free-form value, or None if unknown."""
    return _ALIASES.get(_key(value))


def normalize_tags(
    values: Iterable[object],
    *,
    strict: bool = False,
    max_tags: int | None = 3,
    fallback: object | None = None,
    allowed_tags: Iterable[object] | None = None,
    allow_custom: bool = False,
) -> list[str]:
    """Normalize tags to the controlled taxonomy.

    Unknown tags are ignored by default for AI/feed output, but rejected in
    strict mode for user-saved config.
    """
    tags: list[str] = []
    unknown: list[str] = []
    allowed = _allowed_tag_map(allowed_tags)
    for value in values:
        raw = str(value or "").strip().lstrip("#").strip()
        if not raw:
            continue
        tag = canonical_tag(raw)
        if not tag and allowed:
            tag = allowed.get(_key(raw))
        if not tag and allow_custom:
            tag = clean_custom_tag(raw)
        if not tag:
            unknown.append(raw)
            continue
        if tag not in tags:
            tags.append(tag)

    if not tags and fallback is not None:
        tag = canonical_tag(fallback)
        if tag:
            tags.append(tag)

    if strict and unknown:
        allowed_text = "、".join([*CANONICAL_TAGS, *[tag for tag in allowed.values() if tag not in CANONICAL_TAGS]])
        raise ValueError(f"未知标签：{unknown[0]}。只能使用固定大类：{allowed_text}")

    if max_tags is not None:
        tags = tags[:max_tags]
    return tags


def normalize_category(value: object, *, fallback: object | None = None) -> str:
    """Normalize category to a canonical tag-like category."""
    tag = canonical_tag(value)
    if tag:
        return tag
    if fallback is not None:
        fallback_tag = canonical_tag(fallback)
        if fallback_tag:
            return fallback_tag
    return "行业动态"


def order_tags(
    values: Iterable[object],
    *,
    allowed_tags: Iterable[object] | None = None,
) -> list[str]:
    """Return canonical tags in fixed taxonomy order."""
    normalized = normalize_tags(values, max_tags=None, allowed_tags=allowed_tags)
    present = set(normalized)
    ordered = [tag for tag in CANONICAL_TAGS if tag in present]
    allowed = _allowed_tag_map(allowed_tags)
    for tag in allowed.values():
        if tag in present and tag not in ordered:
            ordered.append(tag)
    for tag in normalized:
        if tag not in ordered:
            ordered.append(tag)
    return ordered


ALLOWED_TAGS_TEXT = "、".join(CANONICAL_TAGS)
