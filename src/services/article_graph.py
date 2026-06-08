"""Static article relationship graph generation."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..storage.article_store import ArticleStore
from .article_features import extract_article_features


GRAPH_VERSION = "article-graph-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _set(values: list[str]) -> set[str]:
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _overlap_ratio(left: list[str], right: list[str]) -> float:
    a = _set(left)
    b = _set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _overlap_values(left: list[str], right: list[str], *, limit: int = 5) -> list[str]:
    right_keys = _set(right)
    values: list[str] = []
    seen: set[str] = set()
    for value in left:
        key = str(value).strip().lower()
        if key and key in right_keys and key not in seen:
            values.append(str(value).strip())
            seen.add(key)
        if len(values) >= limit:
            break
    return values


def _time_proximity(left: str, right: str) -> float:
    left_dt = _parse_dt(left)
    right_dt = _parse_dt(right)
    if not left_dt or not right_dt:
        return 0.0
    hours = abs((left_dt - right_dt).total_seconds()) / 3600
    if hours <= 24:
        return 1.0
    if hours <= 72:
        return 0.7
    if hours <= 24 * 14:
        return 0.35
    return 0.0


def _relation_type(
    *,
    tag_score: float,
    entity_score: float,
    keyword_score: float,
    time_score: float,
) -> str:
    if tag_score >= 0.5 and entity_score >= 0.35 and keyword_score >= 0.35 and time_score >= 0.7:
        return "same_event"
    if time_score >= 0.7 and (tag_score >= 0.4 or entity_score >= 0.35):
        return "timeline"
    if entity_score >= tag_score and entity_score > 0:
        return "entity"
    return "topic"


def _relation_reason(evidence: dict[str, Any]) -> str:
    parts: list[str] = []
    if evidence.get("shared_tags"):
        parts.append("共同标签：" + "、".join(evidence["shared_tags"]))
    if evidence.get("shared_entities"):
        parts.append("共同实体：" + "、".join(evidence["shared_entities"]))
    if evidence.get("shared_keywords"):
        parts.append("共同关键词：" + "、".join(evidence["shared_keywords"][:3]))
    if evidence.get("time_proximity", 0) >= 0.7:
        parts.append("发布时间相近")
    if not parts:
        return "标题、摘要和分类存在弱相关。"
    return "；".join(parts) + "。"


def _edge_between(
    left: dict[str, Any],
    right: dict[str, Any],
    left_features: dict[str, Any],
    right_features: dict[str, Any],
) -> dict[str, Any]:
    tag_score = _overlap_ratio(left_features["topics"], right_features["topics"])
    entity_score = _overlap_ratio(left_features["entities"], right_features["entities"])
    keyword_score = _overlap_ratio(left_features["keywords"], right_features["keywords"])
    time_score = _time_proximity(left.get("published_at", ""), right.get("published_at", ""))
    score = (
        0.35 * tag_score
        + 0.25 * entity_score
        + 0.20 * keyword_score
        + 0.10 * tag_score
        + 0.10 * time_score
    )
    evidence = {
        "shared_tags": _overlap_values(left_features["topics"], right_features["topics"]),
        "shared_entities": _overlap_values(left_features["entities"], right_features["entities"]),
        "shared_keywords": _overlap_values(left_features["keywords"], right_features["keywords"]),
        "time_proximity": round(time_score, 3),
        "components": {
            "tag": round(tag_score, 3),
            "entity": round(entity_score, 3),
            "keyword": round(keyword_score, 3),
            "time": round(time_score, 3),
        },
    }
    relation_type = _relation_type(
        tag_score=tag_score,
        entity_score=entity_score,
        keyword_score=keyword_score,
        time_score=time_score,
    )
    return {
        "source": left["id"],
        "target": right["id"],
        "relation_type": relation_type,
        "score": round(score, 4),
        "reason": _relation_reason(evidence),
        "evidence": evidence,
    }


def _node(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": article["id"],
        "title": article.get("title") or "",
        "url": article.get("url") or "",
        "source": article.get("source") or "",
        "source_type": article.get("source_type") or "",
        "published_at": article.get("published_at") or "",
        "score": float(article.get("score") or 0),
        "summary_zh": article.get("summary_zh") or "",
        "tags": article.get("tags") or [],
        "category": article.get("category") or "",
    }


def _build_groups(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    node_by_id = {node["id"]: node for node in nodes}
    edges_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        edges_by_relation[edge["relation_type"]].append(edge)

    groups: list[dict[str, Any]] = []
    for relation_type, relation_edges in sorted(
        edges_by_relation.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        article_ids: list[str] = []
        for edge in relation_edges:
            for article_id in (edge["source"], edge["target"]):
                if article_id not in article_ids:
                    article_ids.append(article_id)
        article_ids = [article_id for article_id in article_ids if article_id in node_by_id]
        if len(article_ids) < 2:
            continue
        label = {
            "same_event": "同一事件",
            "timeline": "时间线",
            "entity": "共同实体",
            "topic": "共同主题",
        }.get(relation_type, relation_type)
        groups.append(
            {
                "id": f"group:{relation_type}",
                "type": relation_type,
                "title": label,
                "reason": f"{len(article_ids)} 篇文章通过{label}形成关联。",
                "article_ids": article_ids[:12],
                "edge_ids": [f"{edge['source']}->{edge['target']}:{edge['relation_type']}" for edge in relation_edges[:12]],
                "score": round(
                    sum(float(edge.get("score") or 0) for edge in relation_edges)
                    / max(1, len(relation_edges)),
                    4,
                ),
            }
        )
    return groups


def empty_article_graph_snapshot() -> dict[str, Any]:
    return {
        "version": GRAPH_VERSION,
        "generated_at": _now_iso(),
        "scope": {},
        "stats": {"nodes": 0, "edges": 0, "groups": 0},
        "nodes": [],
        "edges": [],
        "groups": [],
    }


def build_article_graph_snapshot(
    store: ArticleStore,
    *,
    premium_score_threshold: float = 8.5,
    relation_top_k: int = 3,
    min_relation_score: float = 0.55,
    max_visible_nodes: int = 30,
    max_visible_edges: int = 100,
) -> dict[str, Any]:
    """Build and persist a static graph snapshot from stored premium articles."""
    articles = store.load_premium_articles(
        min_score=premium_score_threshold,
        limit=max_visible_nodes,
    )
    if not articles:
        return {
            **empty_article_graph_snapshot(),
            "scope": {
                "premium_score_threshold": premium_score_threshold,
                "relation_top_k": relation_top_k,
                "min_relation_score": min_relation_score,
            },
        }

    features_by_id = store.load_article_features()
    for article in articles:
        features = extract_article_features(article)
        existing = features_by_id.get(article["id"])
        if not existing or existing.get("feature_text_hash") != features["feature_text_hash"]:
            store.upsert_article_features(article["id"], features)
            features_by_id[article["id"]] = features

    raw_edges: list[dict[str, Any]] = []
    for index, left in enumerate(articles):
        for right in articles[index + 1:]:
            edge = _edge_between(
                left,
                right,
                features_by_id[left["id"]],
                features_by_id[right["id"]],
            )
            if edge["score"] >= min_relation_score:
                raw_edges.append(edge)

    raw_edges.sort(key=lambda edge: edge["score"], reverse=True)
    per_article_count: dict[str, int] = defaultdict(int)
    edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        if len(edges) >= max_visible_edges:
            break
        source = edge["source"]
        target = edge["target"]
        if per_article_count[source] >= relation_top_k or per_article_count[target] >= relation_top_k:
            continue
        per_article_count[source] += 1
        per_article_count[target] += 1
        edges.append(edge)

    store.replace_article_edges(edges, analysis_version=GRAPH_VERSION)
    nodes = [_node(article) for article in articles]
    groups = _build_groups(nodes, edges)
    return {
        "version": GRAPH_VERSION,
        "generated_at": _now_iso(),
        "scope": {
            "premium_score_threshold": premium_score_threshold,
            "relation_top_k": relation_top_k,
            "min_relation_score": min_relation_score,
            "max_visible_nodes": max_visible_nodes,
            "max_visible_edges": max_visible_edges,
        },
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "groups": len(groups),
        },
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
    }


def write_article_graph_snapshot(output_dir: Path | str, snapshot: dict[str, Any]) -> Path:
    path = Path(output_dir) / "article-graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
