"""SQLite storage: what the bot created in each guild, per-guild settings, layout
backups and templates, XP, warnings and timed mutes.

/reset only ever deletes IDs recorded in created_items, so anything a human made is safe.
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
CREATE TABLE IF NOT EXISTS backups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    label      TEXT    NOT NULL,
    data       TEXT    NOT NULL,   -- JSON layout from core.layout.snapshot()
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS templates (
    user_id    INTEGER NOT NULL,   -- templates belong to the person who saved them
    name       TEXT    NOT NULL,
    data       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, name)
);
CREATE TABLE IF NOT EXISTS xp (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    xp       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason       TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS giveaways (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    host_id    INTEGER NOT NULL,
    prize      TEXT    NOT NULL,
    winners    INTEGER NOT NULL,
    ends_at    REAL    NOT NULL,
    ended      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    won         INTEGER NOT NULL DEFAULT 0,   -- 1 once picked (so rerolls pick someone new)
    PRIMARY KEY (giveaway_id, user_id)
);
CREATE TABLE IF NOT EXISTS suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    message_id INTEGER,
    author_id  INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS birthdays (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    month    INTEGER NOT NULL,
    day      INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,   -- who set it
    channel_id INTEGER,            -- NULL = DM the user
    text       TEXT    NOT NULL,
    due        REAL    NOT NULL,
    repeat     TEXT    NOT NULL DEFAULT 'none'   -- none | daily | weekdays | weekly
);
CREATE TABLE IF NOT EXISTS mutes (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    until    REAL    NOT NULL,     -- unix time when the Muted role comes off
    PRIMARY KEY (guild_id, user_id)
);
"""

MAX_BACKUPS_PER_GUILD = 10


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

    # -- layout backups ---------------------------------------------------------
    def add_backup(self, guild_id: int, label: str, data: dict) -> int:
        cur = self._db.execute("INSERT INTO backups (guild_id, label, data) VALUES (?, ?, ?)",
                               (guild_id, label, json.dumps(data)))
        # Keep only the newest few per guild.
        self._db.execute(
            "DELETE FROM backups WHERE guild_id = ? AND id NOT IN "
            "(SELECT id FROM backups WHERE guild_id = ? ORDER BY id DESC LIMIT ?)",
            (guild_id, guild_id, MAX_BACKUPS_PER_GUILD))
        self._db.commit()
        return cur.lastrowid

    def backups(self, guild_id: int) -> list[sqlite3.Row]:
        """Newest first; rows have id, label, created_at (no data)."""
        return self._db.execute(
            "SELECT id, label, created_at FROM backups WHERE guild_id = ? ORDER BY id DESC",
            (guild_id,)).fetchall()

    def get_backup(self, guild_id: int, backup_id: int) -> dict | None:
        row = self._db.execute("SELECT data FROM backups WHERE guild_id = ? AND id = ?",
                               (guild_id, backup_id)).fetchone()
        return json.loads(row["data"]) if row else None

    # -- templates ------------------------------------------------------------
    def save_template(self, user_id: int, name: str, data: dict) -> None:
        self._db.execute("INSERT OR REPLACE INTO templates (user_id, name, data) VALUES (?, ?, ?)",
                         (user_id, name, json.dumps(data)))
        self._db.commit()

    def template_names(self, user_id: int) -> list[str]:
        rows = self._db.execute("SELECT name FROM templates WHERE user_id = ? ORDER BY name",
                                (user_id,)).fetchall()
        return [r["name"] for r in rows]

    def get_template(self, user_id: int, name: str) -> dict | None:
        row = self._db.execute("SELECT data FROM templates WHERE user_id = ? AND name = ?",
                               (user_id, name)).fetchone()
        return json.loads(row["data"]) if row else None

    def delete_template(self, user_id: int, name: str) -> bool:
        cur = self._db.execute("DELETE FROM templates WHERE user_id = ? AND name = ?", (user_id, name))
        self._db.commit()
        return cur.rowcount > 0

    # -- leveling -------------------------------------------------------------
    def add_xp(self, guild_id: int, user_id: int, amount: int) -> int:
        """Add XP and return the new total."""
        self._db.execute(
            "INSERT INTO xp (guild_id, user_id, xp) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = xp + excluded.xp",
            (guild_id, user_id, amount))
        self._db.commit()
        return self.get_xp(guild_id, user_id)

    def get_xp(self, guild_id: int, user_id: int) -> int:
        row = self._db.execute("SELECT xp FROM xp WHERE guild_id = ? AND user_id = ?",
                               (guild_id, user_id)).fetchone()
        return row["xp"] if row else 0

    def xp_rank(self, guild_id: int, user_id: int) -> int:
        """1-based leaderboard position (ties share the better rank)."""
        xp = self.get_xp(guild_id, user_id)
        row = self._db.execute("SELECT COUNT(*) AS n FROM xp WHERE guild_id = ? AND xp > ?",
                               (guild_id, xp)).fetchone()
        return row["n"] + 1

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        rows = self._db.execute(
            "SELECT user_id, xp FROM xp WHERE guild_id = ? AND xp > 0 ORDER BY xp DESC LIMIT ?",
            (guild_id, limit)).fetchall()
        return [(r["user_id"], r["xp"]) for r in rows]

    # -- moderation -----------------------------------------------------------
    def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        cur = self._db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason))
        self._db.commit()
        return cur.lastrowid

    def warnings(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT id, moderator_id, reason, created_at FROM warnings "
            "WHERE guild_id = ? AND user_id = ? ORDER BY id DESC", (guild_id, user_id)).fetchall()

    def clear_warnings(self, guild_id: int, user_id: int) -> int:
        cur = self._db.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
                               (guild_id, user_id))
        self._db.commit()
        return cur.rowcount

    def set_mute(self, guild_id: int, user_id: int, until: float) -> None:
        self._db.execute("INSERT OR REPLACE INTO mutes (guild_id, user_id, until) VALUES (?, ?, ?)",
                         (guild_id, user_id, until))
        self._db.commit()

    def clear_mute(self, guild_id: int, user_id: int) -> None:
        self._db.execute("DELETE FROM mutes WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        self._db.commit()

    def is_muted(self, guild_id: int, user_id: int, now: float) -> bool:
        row = self._db.execute("SELECT 1 FROM mutes WHERE guild_id = ? AND user_id = ? AND until > ?",
                               (guild_id, user_id, now)).fetchone()
        return row is not None

    def due_mutes(self, now: float) -> list[tuple[int, int]]:
        rows = self._db.execute("SELECT guild_id, user_id FROM mutes WHERE until <= ?",
                                (now,)).fetchall()
        return [(r["guild_id"], r["user_id"]) for r in rows]

    # -- giveaways -------------------------------------------------------------
    def add_giveaway(self, guild_id: int, channel_id: int, host_id: int, prize: str,
                     winners: int, ends_at: float) -> int:
        cur = self._db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, host_id, prize, winners, ends_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (guild_id, channel_id, host_id, prize, winners, ends_at))
        self._db.commit()
        return cur.lastrowid

    def set_giveaway_message(self, giveaway_id: int, message_id: int) -> None:
        self._db.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
        self._db.commit()

    def giveaway(self, giveaway_id: int) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)).fetchone()

    def due_giveaways(self, now: float) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM giveaways WHERE ended = 0 AND ends_at <= ?",
                                (now,)).fetchall()

    def end_giveaway(self, giveaway_id: int) -> bool:
        """Mark ended; False if it already was (so two callers can't both end it)."""
        cur = self._db.execute("UPDATE giveaways SET ended = 1 WHERE id = ? AND ended = 0",
                               (giveaway_id,))
        self._db.commit()
        return cur.rowcount > 0

    def toggle_entry(self, giveaway_id: int, user_id: int) -> bool:
        """Enter, or leave if already entered. Returns True if now entered."""
        cur = self._db.execute("DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                               (giveaway_id, user_id))
        if cur.rowcount == 0:
            self._db.execute("INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                             (giveaway_id, user_id))
        self._db.commit()
        return cur.rowcount == 0

    def entries(self, giveaway_id: int, *, include_winners: bool = True) -> list[int]:
        sql = "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?"
        if not include_winners:
            sql += " AND won = 0"
        return [r["user_id"] for r in self._db.execute(sql, (giveaway_id,)).fetchall()]

    def mark_winners(self, giveaway_id: int, user_ids: list[int]) -> None:
        self._db.executemany("UPDATE giveaway_entries SET won = 1 WHERE giveaway_id = ? AND user_id = ?",
                             [(giveaway_id, u) for u in user_ids])
        self._db.commit()

    # -- suggestions ------------------------------------------------------------
    def add_suggestion(self, guild_id: int, author_id: int, text: str) -> int:
        cur = self._db.execute("INSERT INTO suggestions (guild_id, author_id, text) VALUES (?, ?, ?)",
                               (guild_id, author_id, text))
        self._db.commit()
        return cur.lastrowid

    def set_suggestion_message(self, suggestion_id: int, message_id: int) -> None:
        self._db.execute("UPDATE suggestions SET message_id = ? WHERE id = ?",
                         (message_id, suggestion_id))
        self._db.commit()

    def suggestion(self, suggestion_id: int) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()

    def set_suggestion_status(self, suggestion_id: int, status: str) -> None:
        self._db.execute("UPDATE suggestions SET status = ? WHERE id = ?", (status, suggestion_id))
        self._db.commit()

    # -- birthdays --------------------------------------------------------------
    def set_birthday(self, guild_id: int, user_id: int, month: int, day: int) -> None:
        self._db.execute("INSERT OR REPLACE INTO birthdays (guild_id, user_id, month, day) "
                         "VALUES (?, ?, ?, ?)", (guild_id, user_id, month, day))
        self._db.commit()

    def remove_birthday(self, guild_id: int, user_id: int) -> bool:
        cur = self._db.execute("DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?",
                               (guild_id, user_id))
        self._db.commit()
        return cur.rowcount > 0

    def birthdays(self, guild_id: int) -> list[tuple[int, int, int]]:
        """(user_id, month, day) for everyone in the guild."""
        rows = self._db.execute("SELECT user_id, month, day FROM birthdays WHERE guild_id = ?",
                                (guild_id,)).fetchall()
        return [(r["user_id"], r["month"], r["day"]) for r in rows]

    # -- reminders --------------------------------------------------------------
    def add_reminder(self, guild_id: int, user_id: int, channel_id: int | None, text: str,
                     due: float, repeat: str) -> int:
        cur = self._db.execute(
            "INSERT INTO reminders (guild_id, user_id, channel_id, text, due, repeat) "
            "VALUES (?, ?, ?, ?, ?, ?)", (guild_id, user_id, channel_id, text, due, repeat))
        self._db.commit()
        return cur.lastrowid

    def reminders_for(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM reminders WHERE guild_id = ? AND user_id = ? "
                                "ORDER BY due", (guild_id, user_id)).fetchall()

    def due_reminders(self, now: float) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM reminders WHERE due <= ?", (now,)).fetchall()

    def reschedule_reminder(self, reminder_id: int, due: float) -> None:
        self._db.execute("UPDATE reminders SET due = ? WHERE id = ?", (due, reminder_id))
        self._db.commit()

    def delete_reminder(self, reminder_id: int, user_id: int | None = None) -> bool:
        sql, args = "DELETE FROM reminders WHERE id = ?", [reminder_id]
        if user_id is not None:  # only the owner may delete their own
            sql += " AND user_id = ?"
            args.append(user_id)
        cur = self._db.execute(sql, args)
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()
