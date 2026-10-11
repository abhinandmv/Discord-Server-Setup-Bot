"""SQLite storage: what the bot created in each guild, plus small per-guild settings.

/reset only ever deletes IDs recorded here, so anything a human made is safe.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS created_items (
    guild_id   INTEGER NOT NULL,
    item_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL,   -- role | category | channel | message
    name       TEXT,
    parent_id  INTEGER,            -- category for channels, channel for messages
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, item_id)
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, key)
);
"""


@dataclass(frozen=True)
class TrackedItem:
    guild_id: int
    item_id: int
    kind: str
    name: str | None
    parent_id: int | None


class Storage:
    """Tiny synchronous wrapper; every query is a single-row write or a small read."""

    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # -- created items --------------------------------------------------------
    def track(self, guild_id: int, item_id: int, kind: str, name: str | None = None,
              parent_id: int | None = None) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO created_items (guild_id, item_id, kind, name, parent_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, item_id, kind, name, parent_id),
        )
        self._db.commit()

    def untrack(self, guild_id: int, item_id: int) -> None:
        self._db.execute("DELETE FROM created_items WHERE guild_id = ? AND item_id = ?",
                         (guild_id, item_id))
        self._db.commit()

    def items(self, guild_id: int) -> list[TrackedItem]:
        rows = self._db.execute(
            "SELECT guild_id, item_id, kind, name, parent_id FROM created_items "
            "WHERE guild_id = ? ORDER BY created_at, rowid",
            (guild_id,),
        ).fetchall()
        return [TrackedItem(**dict(row)) for row in rows]

    # -- settings -------------------------------------------------------------
    def get_setting(self, guild_id: int, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
                               (guild_id, key)).fetchone()
        return row["value"] if row else None

    def set_setting(self, guild_id: int, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)",
                         (guild_id, key, value))
        self._db.commit()

    def get_json(self, guild_id: int, key: str, default: Any = None) -> Any:
        raw = self.get_setting(guild_id, key)
        return default if raw is None else json.loads(raw)

    def set_json(self, guild_id: int, key: str, value: Any) -> None:
        self.set_setting(guild_id, key, json.dumps(value))

    def delete_setting(self, guild_id: int, key: str) -> None:
        self._db.execute("DELETE FROM guild_settings WHERE guild_id = ? AND key = ?", (guild_id, key))
        self._db.commit()

    def clear_settings(self, guild_id: int) -> None:
        self._db.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild_id,))
        self._db.commit()

    def close(self) -> None:
        self._db.close()
