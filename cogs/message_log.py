"""Edited and deleted messages, logged to the staff-only message-log channel.

Needs the Message Content intent (Developer Portal -> Bot). Discord only sends
the old text of a message the bot still has in memory, so edits and deletes of
messages from before the bot started show "(not in my memory)".
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core import ui

log = logging.getLogger(__name__)


def _content(message: discord.Message | None) -> str:
    if message is None:
        return "*(not in my memory: it was sent before I started)*"
    text = message.content or "*(no text)*"
    if message.attachments:
        text += "\n📎 " + ", ".join(a.filename for a in message.attachments)
    return ui.clip(text, 1000)


class MessageLog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _log_channel(self, guild: discord.Guild | None) -> discord.TextChannel | None:
        if guild is None:
            return None
        raw = self.bot.storage.get_setting(guild.id, "message_log_channel_id")
        channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def _skip(self, channel_id: int, log_channel: discord.TextChannel | None,
              author: discord.abc.User | None) -> bool:
        # Never log the log channel itself (that would loop), or bots.
        return log_channel is None or channel_id == log_channel.id or bool(author and author.bot)

    async def _post(self, log_channel: discord.TextChannel, embed: discord.Embed) -> None:
        try:
            await log_channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.info("Couldn't write to message log in %s: %s", log_channel.guild.id, exc)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        log_channel = self._log_channel(guild)
        after = payload.message
        if self._skip(payload.channel_id, log_channel, after.author):
            return
        before = payload.cached_message
        if before is not None and before.content == after.content:
            return  # e.g. a link preview loaded; the text didn't change
        embed = discord.Embed(title="✏️ Message edited", colour=ui.YELLOW,
                              description=f"By {after.author.mention} in <#{payload.channel_id}> · "
                                          f"[jump to message]({after.jump_url})",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Before", value=_content(before), inline=False)
        embed.add_field(name="After", value=_content(after), inline=False)
        embed.set_footer(text=f"User ID {after.author.id}")
        await self._post(log_channel, embed)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        log_channel = self._log_channel(guild)
        message = payload.cached_message
        if self._skip(payload.channel_id, log_channel, message.author if message else None):
            return
        who = f"By {message.author.mention} " if message else ""
        embed = discord.Embed(title="🗑️ Message deleted", colour=ui.RED,
                              description=f"{who}in <#{payload.channel_id}>",
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="Content", value=_content(message), inline=False)
        if message:
            embed.set_footer(text=f"User ID {message.author.id}")
        await self._post(log_channel, embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        log_channel = self._log_channel(guild)
        if self._skip(payload.channel_id, log_channel, None):
            return
        await self._post(log_channel, discord.Embed(
            title="🧹 Messages bulk-deleted", colour=ui.RED, timestamp=discord.utils.utcnow(),
            description=f"{len(payload.message_ids)} message(s) in <#{payload.channel_id}> "
                        "(usually /purge; see the mod log for who ran it)."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageLog(bot))
