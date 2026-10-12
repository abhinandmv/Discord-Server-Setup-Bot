"""Live stat channels: locked voice channels renamed to show member and boost counts.

Discord allows only two channel renames per 10 minutes, so counts refresh
every 10 minutes rather than on every join.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

REFRESH_MINUTES = 10


def stat_value(guild: discord.Guild, kind: str) -> int | None:
    if kind == "members":
        return guild.member_count
    if kind == "boosts":
        return guild.premium_subscription_count
    return None


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.refresh_all.start()

    async def cog_unload(self) -> None:
        self.refresh_all.cancel()

    async def refresh(self, guild: discord.Guild) -> None:
        storage = self.bot.storage
        stats = storage.get_json(guild.id, "stat_channels", None) or {}
        if not stats:
            return
        alive = {}
        for channel_id, info in stats.items():
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                continue  # deleted by hand; forget it
            alive[channel_id] = info
            value = stat_value(guild, info["kind"])
            name = f"{info['label']}: {value:,}" if value is not None else info["label"]
            if channel.name == name:
                continue
            try:
                await channel.edit(name=name[:100], reason="Live server stats")
            except discord.Forbidden:
                log.warning("Can't rename stat channel #%s in %s: I need View Channel and Connect "
                            "there. Re-run /setup or allow them for my role.", channel.name, guild.id)
            except discord.HTTPException as exc:
                log.info("Couldn't update stat channel in %s: %s", guild.id, exc)
        if alive != stats:
            storage.set_json(guild.id, "stat_channels", alive)

    @tasks.loop(minutes=REFRESH_MINUTES)
    async def refresh_all(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self.refresh(guild)
            except Exception:
                log.exception("Stat refresh failed in %s", guild.id)

    @refresh_all.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))
