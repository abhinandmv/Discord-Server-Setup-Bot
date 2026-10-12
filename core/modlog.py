"""Post events to the server's mod-log channel (set up by the staff area feature)."""

from __future__ import annotations

import logging

import discord

from core import ui

log = logging.getLogger(__name__)


async def log_event(bot, guild: discord.Guild, title: str, description: str, *,
                    colour: int = ui.BLURPLE) -> None:
    """Best effort: does nothing if there's no mod-log channel or it can't be posted to."""
    raw = bot.storage.get_setting(guild.id, "mod_log_channel_id")
    channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
    if not isinstance(channel, discord.TextChannel):
        return
    embed = discord.Embed(title=title, description=ui.clip(description, 4000), colour=colour,
                          timestamp=discord.utils.utcnow())
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        log.info("Couldn't write to mod log in %s: %s", guild.id, exc)
