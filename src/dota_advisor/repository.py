from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import TypeAdapter

from .models import (
    HeroProfile,
    Item,
    MatchState,
    Recommendation,
    RetrievedPassage,
    StrategyDocument,
)

T = TypeVar("T")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    patch_version TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS heroes (
                    name TEXT PRIMARY KEY,
                    patch_version TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_documents (
                    source_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    hero TEXT,
                    role TEXT,
                    patch_version TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    threat_tags TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS strategy_fts USING fts5(
                    source_id UNINDEXED,
                    title,
                    content,
                    hero,
                    role,
                    topic,
                    threat_tags,
                    tokenize='porter unicode61'
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS ix_snapshots_kind_id ON snapshots(kind, id DESC);
                """
            )


class SQLiteItemRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def seed(self, items: Sequence[Item], heroes: Sequence[HeroProfile]) -> None:
        with self.database._lock, self.database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO items(id, name, patch_version, payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                    patch_version=excluded.patch_version, payload=excluded.payload
                """,
                [
                    (item.id, item.name, item.patch_version, item.model_dump_json())
                    for item in items
                ],
            )
            connection.executemany(
                """
                INSERT INTO heroes(name, patch_version, payload) VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET patch_version=excluded.patch_version,
                    payload=excluded.payload
                """,
                [(hero.name, hero.patch_version, hero.model_dump_json()) for hero in heroes],
            )

    def list_items(self) -> list[Item]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT payload FROM items ORDER BY name").fetchall()
        return [Item.model_validate_json(row["payload"]) for row in rows]

    def get_item(self, item_id: str) -> Item | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return Item.model_validate_json(row["payload"]) if row else None

    def list_heroes(self) -> list[HeroProfile]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT payload FROM heroes ORDER BY name").fetchall()
        return [HeroProfile.model_validate_json(row["payload"]) for row in rows]


class SQLiteStrategyRetriever:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ingest(self, documents: Sequence[StrategyDocument]) -> int:
        with self.database._lock, self.database.connect() as connection:
            for document in documents:
                connection.execute(
                    """
                    INSERT INTO strategy_documents(
                        source_id, title, hero, role, patch_version, topic, threat_tags, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        title=excluded.title, hero=excluded.hero, role=excluded.role,
                        patch_version=excluded.patch_version, topic=excluded.topic,
                        threat_tags=excluded.threat_tags, payload=excluded.payload
                    """,
                    (
                        document.source_id,
                        document.title,
                        document.hero,
                        document.role.value if document.role else None,
                        document.patch_version,
                        document.topic,
                        json.dumps(document.threat_tags),
                        document.model_dump_json(),
                    ),
                )
                connection.execute(
                    "DELETE FROM strategy_fts WHERE source_id = ?", (document.source_id,)
                )
                connection.execute(
                    """
                    INSERT INTO strategy_fts(
                        source_id, title, content, hero, role, topic, threat_tags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.source_id,
                        document.title,
                        document.content,
                        document.hero or "",
                        document.role.value if document.role else "",
                        document.topic,
                        " ".join(document.threat_tags),
                    ),
                )
        return len(documents)

    @staticmethod
    def _fts_query(terms: Sequence[str]) -> str:
        clean = [term.replace('"', " ").strip() for term in terms if term.strip()]
        return " OR ".join(f'"{term}"' for term in dict.fromkeys(clean))

    def retrieve(
        self,
        *,
        hero: str | None,
        role: str | None,
        patch_version: str,
        threat_tags: Sequence[str],
        limit: int = 5,
    ) -> list[RetrievedPassage]:
        terms = [*threat_tags]
        if hero:
            terms.append(hero)
        if role:
            terms.append(role.replace("_", " "))
        query = self._fts_query(terms or ["item"])
        params: list[Any] = [query, patch_version]
        filters = ["strategy_fts MATCH ?", "d.patch_version = ?"]
        if hero:
            filters.append("(d.hero IS NULL OR lower(d.hero) = lower(?))")
            params.append(hero)
        if role:
            filters.append("(d.role IS NULL OR d.role = ?)")
            params.append(role)
        params.append(limit * 3)
        sql = f"""
            SELECT d.payload, bm25(strategy_fts, 0.0, 1.0, 2.0, 0.2, 0.2, 0.5, 1.5) AS rank
            FROM strategy_fts
            JOIN strategy_documents d ON d.source_id = strategy_fts.source_id
            WHERE {" AND ".join(filters)}
            ORDER BY rank
            LIMIT ?
        """
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            if not rows:
                fallback_params: list[Any] = [patch_version]
                fallback_filters = ["patch_version = ?"]
                if hero:
                    fallback_filters.append("(hero IS NULL OR lower(hero) = lower(?))")
                    fallback_params.append(hero)
                if role:
                    fallback_filters.append("(role IS NULL OR role = ?)")
                    fallback_params.append(role)
                fallback_params.append(limit)
                rows = connection.execute(
                    f"SELECT payload, 1.0 AS rank FROM strategy_documents "
                    f"WHERE {' AND '.join(fallback_filters)} ORDER BY source_id LIMIT ?",
                    fallback_params,
                ).fetchall()

        requested = {tag.casefold() for tag in threat_tags}
        scored: list[RetrievedPassage] = []
        for row in rows:
            document = StrategyDocument.model_validate_json(row["payload"])
            overlap = len(requested & {tag.casefold() for tag in document.threat_tags})
            score = 0.35 + min(0.4, overlap * 0.16)
            if hero and document.hero and document.hero.casefold() == hero.casefold():
                score += 0.15
            if role and document.role and document.role.value == role:
                score += 0.10
            score += min(0.08, 0.08 / (1.0 + abs(float(row["rank"]))))
            scored.append(
                RetrievedPassage(**document.model_dump(), relevance_score=min(1.0, score))
            )
        scored.sort(key=lambda passage: (-passage.relevance_score, passage.source_id))
        return scored[:limit]


class SQLiteMatchStateStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _save(self, kind: str, payload: str) -> None:
        with self.database._lock, self.database.connect() as connection:
            connection.execute(
                "INSERT INTO snapshots(kind, payload) VALUES (?, ?)", (kind, payload)
            )
            connection.execute(
                """
                DELETE FROM snapshots WHERE kind = ? AND id NOT IN (
                    SELECT id FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT 50
                )
                """,
                (kind, kind),
            )

    def _latest_payload(self, kind: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM snapshots WHERE kind = ? ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
        return row["payload"] if row else None

    def save_state(self, state: MatchState) -> None:
        self._save("state", state.model_dump_json())

    def latest_state(self) -> MatchState | None:
        payload = self._latest_payload("state")
        return MatchState.model_validate_json(payload) if payload else None

    def save_recommendations(self, recommendations: Sequence[Recommendation]) -> None:
        adapter = TypeAdapter(list[Recommendation])
        self._save("recommendations", adapter.dump_json(list(recommendations)).decode())

    def latest_recommendations(self) -> list[Recommendation]:
        payload = self._latest_payload("recommendations")
        return TypeAdapter(list[Recommendation]).validate_json(payload) if payload else []

    def save_retrieval(self, passages: Sequence[RetrievedPassage]) -> None:
        adapter = TypeAdapter(list[RetrievedPassage])
        self._save("retrieval", adapter.dump_json(list(passages)).decode())

    def latest_retrieval(self) -> list[RetrievedPassage]:
        payload = self._latest_payload("retrieval")
        return TypeAdapter(list[RetrievedPassage]).validate_json(payload) if payload else []
