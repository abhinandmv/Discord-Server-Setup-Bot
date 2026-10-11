"""Configuration loaded from the environment / .env file."""

import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "").strip()

_guild_id = os.getenv("TEST_GUILD_ID", "").strip()
TEST_GUILD_ID: int | None = int(_guild_id) if _guild_id.isdigit() else None

DATABASE_PATH: str = os.getenv("DATABASE_PATH", "").strip() or "data/bot.db"
