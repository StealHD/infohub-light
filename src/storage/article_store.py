"""SQLite-backed light article storage for optional relationship analysis."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from ..models import ContentItem
from ..tag_policy import (
    normalize_channel,
    normalize_entities,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)


ARTICLE_LIGHT_TAXONOMY_COLUMNS: dict[str, str] = {
    "channel": "TEXT",
    "topics_json": "TEXT NOT NULL DEFAULT '[]'",
    "signal_strength": "TEXT",
    "signal_type": "TEXT",
    "entities_json": "TEXT NOT NULL DEFAULT '[]'",
}


def normalize_url(url: str) -> str:
    """Return a stable URL key without scheme, fragment, www, or trailing slash."""
    parsed = urlparse(str(url).strip())
    host = (parsed.hostname or parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    if not path:
        path = ""
    query = f"?{parsed.query}" if parsed.query else ""
    if host:
        return f"{host}{path}{query}"
    return str(url).strip().split("#", 1)[0].rstrip("/")


def content_hash(*parts: Any) -> str:
    """Stable sha256 hash for article content identity."""
    hasher = hashlib.sha256()
    for part in parts:
        text = "" if part is None else str(part)
        hasher.update(text.encode("utf-8", errors="ignore"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _source_label(item: ContentItem) -> str:
    meta = item.metadata or {}
    if meta.get("feed_name"):
        return str(meta["feed_name"])
    if meta.get("subreddit"):
        return f"r/{meta['subreddit']}"
    if meta.get("channel"):
        return f"@{meta['channel']}"
    if meta.get("repo"):
        return str(meta["repo"])
    if meta.get("watchlist"):
        return str(meta["watchlist"])
    return item.author or item.source_type.value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _item_channel(item: ContentItem) -> str:
    meta = item.metadata if isinstance(item.metadata, dict) else {}
    return normalize_channel(
        item.ai_channel
        or item.ai_category
        or meta.get("channel")
        or meta.get("category"),
        fallback=item.source_type.value,
    )


def _item_topics(item: ContentItem, *, channel: str) -> list[str]:
    meta = item.metadata if isinstance(item.metadata, dict) else {}
    values: list[Any] = []
    for group in (
        item.ai_topics,
        item.ai_tags,
        meta.get("topics"),
        meta.get("tags"),
    ):
        values.extend(_as_list(group))
    for legacy_category in (item.ai_category, meta.get("category")):
        text = str(legacy_category or "").strip()
        if text and text != channel:
            values.append(text)
    return normalize_tags(
        values,
        fallback=channel,
        max_tags=6,
        allow_custom=True,
    )


def _item_entities(item: ContentItem) -> list[str]:
    meta = item.metadata if isinstance(item.metadata, dict) else {}
    return normalize_entities(item.ai_entities or _as_list(meta.get("entities")))


def _ensure_articles_light_columns(conn: sqlite3.Connection) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(articles_light)").fetchall()
    }
    for name, definition in ARTICLE_LIGHT_TAXONOMY_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE articles_light ADD COLUMN {name} {definition}")


class ArticleStore:
    """Small SQLite repository for optional premium article graph data."""

    def __init__(
        self,
        data_dir: Path | str,
        db_path: Path | str | None = None,
    ) -> None:
        data_text = str(data_dir)
        if db_path is not None:
            self.db_path = str(db_path)
        elif data_text == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = str(Path(data_dir) / "horizon.db")
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self) -> None:
        conn = self.connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles_light (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                author TEXT,
                published_at TEXT,
                fetched_at TEXT,
                score REAL NOT NULL DEFAULT 0,
                reason TEXT,
                summary_zh TEXT,
                category TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                channel TEXT,
                topics_json TEXT NOT NULL DEFAULT '[]',
                signal_strength TEXT,
                signal_type TEXT,
                entities_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_articles_light_score ON articles_light(score DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_light_published ON articles_light(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_light_normalized_url ON articles_light(normalized_url);

            CREATE TABLE IF NOT EXISTS premium_articles (
                article_id TEXT PRIMARY KEY,
                normalized_url TEXT NOT NULL,
                cleaned_text TEXT,
                text_length INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL,
                fetch_status TEXT NOT NULL DEFAULT 'pending',
                fetch_error TEXT,
                fetched_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles_light(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS article_features (
                article_id TEXT PRIMARY KEY,
                keywords_json TEXT NOT NULL DEFAULT '[]',
                entities_json TEXT NOT NULL DEFAULT '[]',
                topics_json TEXT NOT NULL DEFAULT '[]',
                event_time TEXT,
                viewpoint TEXT,
                feature_text_hash TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles_light(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS article_edges (
                id TEXT PRIMARY KEY,
                source_article_id TEXT NOT NULL,
                target_article_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                score REAL NOT NULL,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                analysis_version TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                FOREIGN KEY(source_article_id) REFERENCES articles_light(id) ON DELETE CASCADE,
                FOREIGN KEY(target_article_id) REFERENCES articles_light(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_article_edges_source ON article_edges(source_article_id, score DESC);
            CREATE INDEX IF NOT EXISTS idx_article_edges_target ON article_edges(target_article_id, score DESC);
            """
        )
        _ensure_articles_light_columns(conn)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def upsert_articles_light(self, items: Iterable[ContentItem]) -> int:
        rows = []
        now = _now_iso()
        for item in items:
            summary = item.ai_summary_zh or item.metadata.get("detailed_summary_zh") or item.ai_summary or ""
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            channel = _item_channel(item)
            topics = _item_topics(item, channel=channel)
            entities = _item_entities(item)
            rows.append(
                {
                    "id": item.id,
                    "source_type": item.source_type.value,
                    "source": _source_label(item),
                    "title": item.title,
                    "url": str(item.url),
                    "normalized_url": normalize_url(str(item.url)),
                    "author": item.author or "",
                    "published_at": _iso(item.published_at),
                    "fetched_at": _iso(item.fetched_at),
                    "score": float(item.ai_score or 0),
                    "reason": item.ai_reason or "",
                    "summary_zh": str(summary),
                    "category": channel,
                    "tags_json": _json_dumps(topics),
                    "channel": channel,
                    "topics_json": _json_dumps(topics),
                    "signal_strength": normalize_signal_strength(
                        item.ai_signal_strength or metadata.get("signal_strength"),
                        score=item.ai_score,
                    ),
                    "signal_type": normalize_signal_type(
                        item.ai_signal_type or metadata.get("signal_type")
                    ),
                    "entities_json": _json_dumps(entities),
                    "metadata_json": _json_dumps(item.metadata or {}),
                    "content_hash": content_hash(item.title, item.content or "", summary),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if not rows:
            return 0

        conn = self.connect()
        conn.executemany(
            """
            INSERT INTO articles_light (
                id, source_type, source, title, url, normalized_url, author,
                published_at, fetched_at, score, reason, summary_zh, category,
                tags_json, channel, topics_json, signal_strength, signal_type,
                entities_json, metadata_json, content_hash, created_at, updated_at
            ) VALUES (
                :id, :source_type, :source, :title, :url, :normalized_url, :author,
                :published_at, :fetched_at, :score, :reason, :summary_zh, :category,
                :tags_json, :channel, :topics_json, :signal_strength, :signal_type,
                :entities_json, :metadata_json, :content_hash, :created_at, :updated_at
            )
            ON CONFLICT(id) DO UPDATE SET
                source_type=excluded.source_type,
                source=excluded.source,
                title=excluded.title,
                url=excluded.url,
                normalized_url=excluded.normalized_url,
                author=excluded.author,
                published_at=excluded.published_at,
                fetched_at=excluded.fetched_at,
                score=excluded.score,
                reason=excluded.reason,
                summary_zh=excluded.summary_zh,
                category=excluded.category,
                tags_json=excluded.tags_json,
                channel=excluded.channel,
                topics_json=excluded.topics_json,
                signal_strength=excluded.signal_strength,
                signal_type=excluded.signal_type,
                entities_json=excluded.entities_json,
                metadata_json=excluded.metadata_json,
                content_hash=excluded.content_hash,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        conn.commit()
        return len(rows)

    def load_articles_light(
        self,
        *,
        min_score: float = 0.0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM articles_light WHERE score >= ? ORDER BY score DESC, published_at DESC"
        params: list[Any] = [float(min_score)]
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self.connect().execute(sql, params).fetchall()
        return [self._article_row_to_dict(row) for row in rows]

    def load_premium_candidates(
        self,
        *,
        min_score: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT al.*
            FROM articles_light al
            LEFT JOIN premium_articles pa ON pa.article_id = al.id
            WHERE al.score >= ?
              AND (pa.article_id IS NULL OR pa.fetch_status != 'ok')
            ORDER BY al.score DESC, al.published_at DESC
            LIMIT ?
            """,
            (float(min_score), int(limit)),
        ).fetchall()
        return [self._article_row_to_dict(row) for row in rows]

    def upsert_premium_article(
        self,
        *,
        article_id: str,
        normalized_url: str,
        cleaned_text: str = "",
        fetch_status: str = "ok",
        fetch_error: str = "",
    ) -> None:
        now = _now_iso()
        text_hash = content_hash(cleaned_text)
        self.connect().execute(
            """
            INSERT INTO premium_articles (
                article_id, normalized_url, cleaned_text, text_length,
                content_hash, fetch_status, fetch_error, fetched_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                normalized_url=excluded.normalized_url,
                cleaned_text=excluded.cleaned_text,
                text_length=excluded.text_length,
                content_hash=excluded.content_hash,
                fetch_status=excluded.fetch_status,
                fetch_error=excluded.fetch_error,
                fetched_at=excluded.fetched_at,
                updated_at=excluded.updated_at
            """,
            (
                article_id,
                normalized_url,
                cleaned_text,
                len(cleaned_text),
                text_hash,
                fetch_status,
                fetch_error,
                now,
                now,
                now,
            ),
        )
        self.connect().commit()

    def load_premium_articles(
        self,
        *,
        min_score: float = 0.0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT al.*, pa.cleaned_text, pa.text_length, pa.fetch_status, pa.fetch_error
            FROM articles_light al
            LEFT JOIN premium_articles pa ON pa.article_id = al.id
            WHERE al.score >= ?
            ORDER BY al.score DESC, al.published_at DESC
        """
        params: list[Any] = [float(min_score)]
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self.connect().execute(sql, params).fetchall()
        results = []
        for row in rows:
            item = self._article_row_to_dict(row)
            item["cleaned_text"] = row["cleaned_text"] or ""
            item["text_length"] = int(row["text_length"] or 0)
            item["fetch_status"] = row["fetch_status"] or ""
            item["fetch_error"] = row["fetch_error"] or ""
            results.append(item)
        return results

    def upsert_article_features(self, article_id: str, features: dict[str, Any]) -> None:
        now = _now_iso()
        self.connect().execute(
            """
            INSERT INTO article_features (
                article_id, keywords_json, entities_json, topics_json,
                event_time, viewpoint, feature_text_hash, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                keywords_json=excluded.keywords_json,
                entities_json=excluded.entities_json,
                topics_json=excluded.topics_json,
                event_time=excluded.event_time,
                viewpoint=excluded.viewpoint,
                feature_text_hash=excluded.feature_text_hash,
                generated_at=excluded.generated_at
            """,
            (
                article_id,
                _json_dumps(features.get("keywords") or []),
                _json_dumps(features.get("entities") or []),
                _json_dumps(features.get("topics") or []),
                str(features.get("event_time") or ""),
                str(features.get("viewpoint") or ""),
                str(features.get("feature_text_hash") or ""),
                now,
            ),
        )
        self.connect().commit()

    def load_article_features(self) -> dict[str, dict[str, Any]]:
        rows = self.connect().execute("SELECT * FROM article_features").fetchall()
        return {
            str(row["article_id"]): {
                "keywords": _json_loads(row["keywords_json"], []),
                "entities": _json_loads(row["entities_json"], []),
                "topics": _json_loads(row["topics_json"], []),
                "event_time": row["event_time"] or "",
                "viewpoint": row["viewpoint"] or "",
                "feature_text_hash": row["feature_text_hash"] or "",
            }
            for row in rows
        }

    def replace_article_edges(
        self,
        edges: Iterable[dict[str, Any]],
        *,
        analysis_version: str,
    ) -> None:
        conn = self.connect()
        conn.execute("DELETE FROM article_edges WHERE analysis_version = ?", (analysis_version,))
        now = _now_iso()
        rows = []
        for edge in edges:
            source_id = str(edge["source"])
            target_id = str(edge["target"])
            relation_type = str(edge["relation_type"])
            edge_id = f"{analysis_version}:{source_id}:{target_id}:{relation_type}"
            rows.append(
                (
                    edge_id,
                    source_id,
                    target_id,
                    relation_type,
                    float(edge.get("score") or 0),
                    str(edge.get("reason") or ""),
                    _json_dumps(edge.get("evidence") or {}),
                    analysis_version,
                    now,
                )
            )
        if rows:
            conn.executemany(
                """
                INSERT INTO article_edges (
                    id, source_article_id, target_article_id, relation_type,
                    score, reason, evidence_json, analysis_version, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()

    def load_article_edges(self, *, analysis_version: str = "article-graph-v1") -> list[dict[str, Any]]:
        rows = self.connect().execute(
            """
            SELECT * FROM article_edges
            WHERE analysis_version = ?
            ORDER BY score DESC
            """,
            (analysis_version,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "source": row["source_article_id"],
                "target": row["target_article_id"],
                "relation_type": row["relation_type"],
                "score": float(row["score"] or 0),
                "reason": row["reason"] or "",
                "evidence": _json_loads(row["evidence_json"], {}),
            }
            for row in rows
        ]

    @staticmethod
    def _article_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = {key: row[key] for key in row.keys()}
        topics = _json_loads(data.get("topics_json"), [])
        if not topics:
            topics = _json_loads(data.get("tags_json"), [])
        channel = data.get("channel") or data.get("category") or ""
        return {
            "id": data["id"],
            "source_type": data["source_type"],
            "source": data["source"],
            "title": data["title"],
            "url": data["url"],
            "normalized_url": data["normalized_url"],
            "author": data.get("author") or "",
            "published_at": data.get("published_at") or "",
            "fetched_at": data.get("fetched_at") or "",
            "score": float(data.get("score") or 0),
            "reason": data.get("reason") or "",
            "summary_zh": data.get("summary_zh") or "",
            "channel": channel,
            "topics": topics,
            "signal_strength": data.get("signal_strength") or "",
            "signal_type": data.get("signal_type") or "",
            "entities": _json_loads(data.get("entities_json"), []),
            "category": channel,
            "tags": topics,
            "metadata": _json_loads(data.get("metadata_json"), {}),
            "content_hash": data["content_hash"],
        }
