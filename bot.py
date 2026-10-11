"""Entry point: python bot.py"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

import config
import templates
from core.storage import Storage

log = logging.getLogger("setup_bot")

EXTENSIONS = ("cogs.wizard", "cogs.reset", "cogs.role_menu", "cogs.tickets")


class SetupBot(commands.Bot):
    def __init__(self) -> None:
        # Default intents are enough: no privileged intents (members, message content) needed.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default(),
                         help_command=None)
        self.storage = Storage(config.DATABASE_PATH)
        self._guild_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def guild_lock(self, guild_id: int) -> asyncio.Lock:
        """One build or reset at a time per guild."""
        return self._guild_locks[guild_id]

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.tree.on_error = self.on_app_command_error

        if config.TEST_GUILD_ID:
            guild = discord.Object(id=config.TEST_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to test guild %s (instant)", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global command(s) (may take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id %s) in %d guild(s)", self.user, self.user.id, len(self.guilds))

    async def on_app_command_error(self, interaction: discord.Interaction,
                                   error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(p.replace("_", " ").replace("guild", "server").title()
                                for p in error.missing_permissions)
            text = f"You need these permissions to use this command: **{missing}**."
        elif isinstance(error, app_commands.NoPrivateMessage):
            text = "This command only works inside a server."
        else:
            log.exception("Unhandled error in /%s", interaction.command and interaction.command.name,
                          exc_info=error)
            text = "⚠️ Something went wrong. Check the bot logs for details."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await super().close()
        self.storage.close()


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO, root=True)
    if not config.DISCORD_TOKEN:
        sys.exit("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")
    templates.validate()  # fail fast on template typos
    SetupBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
