"""/remind: personal reminders (sent by DM) and repeating channel reminders.

`when` is either a delay ("10m", "2h", "3d") or a time of day ("09:00"). Times
of day use `utc_offset` (e.g. "+5:30"), and the confirmation shows the result
as a Discord timestamp, which every viewer sees in their own time zone.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import ui
from core.permissions import MOD_COMMAND_PERMISSIONS
from cogs.moderation import parse_duration

log = logging.getLogger(__name__)

MAX_PER_USER = 25
MAX_DELAY = 365 * 86400
_TIME = re.compile(r"^\s*([01]?\d|2[0-3])[:.]([0-5]\d)\s*$")
_OFFSET = re.compile(r"^\s*(?:UTC)?\s*([+-])?(\d{1,2})(?::?([0-5]\d))?\s*$", re.IGNORECASE)
Repeat = Literal["none", "daily", "weekdays", "weekly"]


def parse_offset(text: str | None) -> datetime.timezone | None:
    """'+5:30' -> UTC+05:30; '' -> UTC; None if invalid."""
    if not text or not text.strip():
        return datetime.timezone.utc
    match = _OFFSET.match(text)
    if not match or int(match[2]) > 14:
        return None
    minutes = int(match[2]) * 60 + int(match[3] or 0)
    return datetime.timezone(datetime.timedelta(minutes=-minutes if match[1] == "-" else minutes))


def first_due(when: str, tz: datetime.timezone, repeat: str, now: float) -> float | None:
    """Unix time of the first reminder, or None if ``when`` can't be understood."""
    seconds = parse_duration(when)
    if seconds is not None:
        return now + seconds if 0 < seconds <= MAX_DELAY else None
    match = _TIME.match(when or "")
    if not match:
        return None
    local_now = datetime.datetime.fromtimestamp(now, tz)
    due = local_now.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    if due <= local_now:
        due += datetime.timedelta(days=1)
    while repeat == "weekdays" and due.weekday() >= 5:
        due += datetime.timedelta(days=1)
    return due.timestamp()


def next_due(due: float, repeat: str, tz: datetime.timezone) -> float | None:
    if repeat == "none":
        return None
    step = {"daily": 1, "weekdays": 1, "weekly": 7}[repeat]
    nxt = datetime.datetime.fromtimestamp(due, tz) + datetime.timedelta(days=step)
    while repeat == "weekdays" and nxt.weekday() >= 5:
        nxt += datetime.timedelta(days=1)
    return nxt.timestamp()


class Reminders(commands.Cog):
    remind = app_commands.Group(name="remind", description="Set reminders", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.deliver.start()

    async def cog_unload(self) -> None:
        self.deliver.cancel()

    def _room(self, interaction: discord.Interaction) -> bool:
        return len(self.bot.storage.reminders_for(interaction.guild.id,
                                                  interaction.user.id)) < MAX_PER_USER

    async def _create(self, interaction: discord.Interaction, channel: discord.TextChannel | None,
                      when: str, text: str, repeat: str, utc_offset: str | None) -> None:
        tz = parse_offset(utc_offset)
        if tz is None:
            await interaction.response.send_message("Use a UTC offset like `+5:30` or `-4`.",
                                                    ephemeral=True)
            return
        due = first_due(when, tz, repeat, time.time())
        if due is None:
            await interaction.response.send_message(
                "Use a delay like `10m`, `2h`, `3d`, or a time of day like `09:00`.", ephemeral=True)
            return
        if not self._room(interaction):
            await interaction.response.send_message(
                f"You already have {MAX_PER_USER} reminders. Delete some with `/remind delete`.",
                ephemeral=True)
            return
        # The offset is stored with the repeat so "every weekday at 9" stays at 9 local time.
        offset_min = int(tz.utcoffset(None).total_seconds() // 60)
        rid = self.bot.storage.add_reminder(interaction.guild.id, interaction.user.id,
                                            channel.id if channel else None, text, due,
                                            f"{repeat}@{offset_min}")
        where = channel.mention if channel else "your DMs"
        again = "" if repeat == "none" else f", then {repeat}"
        await interaction.response.send_message(
            f"⏰ Reminder **#{rid}** set for <t:{int(due)}:F> (<t:{int(due)}:R>){again}, in {where}.",
            ephemeral=True)

    @remind.command(name="me", description="Remind yourself (by DM)")
    @app_commands.describe(when="A delay like 10m / 2h / 3d, or a time like 09:00",
                           text="What to remind you about",
                           repeat="Repeat the reminder", utc_offset="Your time zone, e.g. +5:30")
    async def me(self, interaction: discord.Interaction, when: str,
                 text: app_commands.Range[str, 1, 1000], repeat: Repeat = "none",
                 utc_offset: str | None = None) -> None:
        await self._create(interaction, None, when, text, repeat, utc_offset)

    @remind.command(name="channel", description="Post a reminder in a channel (staff)")
    @app_commands.checks.has_permissions(**{MOD_COMMAND_PERMISSIONS["remind_channel"]: True})
    @app_commands.describe(channel="Where to post it", when="A delay like 2h, or a time like 09:00",
                           text="The reminder", repeat="e.g. weekdays for a daily standup",
                           utc_offset="Time zone for the time of day, e.g. +5:30")
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel,
                      when: str, text: app_commands.Range[str, 1, 1000], repeat: Repeat = "none",
                      utc_offset: str | None = None) -> None:
        mine = channel.permissions_for(interaction.user)
        if not (mine.view_channel and mine.send_messages):
            await interaction.response.send_message(f"You can't post in {channel.mention}.",
                                                    ephemeral=True)
            return
        await self._create(interaction, channel, when, text, repeat, utc_offset)

    @remind.command(name="list", description="Your reminders")
    async def list_(self, interaction: discord.Interaction) -> None:
        rows = self.bot.storage.reminders_for(interaction.guild.id, interaction.user.id)
        lines = [f"**#{r['id']}** · <t:{int(r['due'])}:f> · "
                 f"{'<#' + str(r['channel_id']) + '>' if r['channel_id'] else 'DM'}"
                 f"{'' if r['repeat'].startswith('none') else ' · ' + r['repeat'].split('@')[0]}\n"
                 f"{ui.clip(r['text'], 120)}" for r in rows]
        await interaction.response.send_message(
            embed=discord.Embed(title="⏰ Your reminders",
                                description=ui.bullet_list(lines, 4000) if lines else "None yet.",
                                colour=ui.BLURPLE), ephemeral=True)

    @remind.command(name="delete", description="Delete one of your reminders")
    @app_commands.describe(reminder_id="The number from /remind list")
    async def delete(self, interaction: discord.Interaction, reminder_id: int) -> None:
        ok = self.bot.storage.delete_reminder(reminder_id, user_id=interaction.user.id)
        await interaction.response.send_message("🗑️ Deleted." if ok else
                                                "You don't have a reminder with that number.",
                                                ephemeral=True)

    # ------------------------------------------------------------------ #
    @tasks.loop(seconds=20)
    async def deliver(self) -> None:
        storage = self.bot.storage
        for row in storage.due_reminders(time.time()):
            try:
                await self._send(row)
            except Exception:
                log.exception("Reminder %s failed", row["id"])
            repeat, _, offset = row["repeat"].partition("@")
            tz = datetime.timezone(datetime.timedelta(minutes=int(offset or 0)))
            nxt = next_due(row["due"], repeat, tz)
            # Skip occurrences missed while the bot was offline instead of spamming them.
            while nxt is not None and nxt <= time.time():
                nxt = next_due(nxt, repeat, tz)
            if nxt is None:
                storage.delete_reminder(row["id"])
            else:
                storage.reschedule_reminder(row["id"], nxt)

    @deliver.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _send(self, row) -> None:
        guild = self.bot.get_guild(row["guild_id"])
        member = guild.get_member(row["user_id"]) if guild else None
        if member is None:
            return
        embed = discord.Embed(title="⏰ Reminder", description=row["text"], colour=ui.BLURPLE)
        if row["channel_id"] is None:
            embed.set_footer(text=f"From {guild.name}")
            await member.send(embed=embed)
            return
        channel = guild.get_channel(row["channel_id"])
        # Re-checked each time: whoever set it must still be allowed to post there.
        if not isinstance(channel, discord.TextChannel) or \
                not channel.permissions_for(member).send_messages:
            return
        embed.set_footer(text=f"Set by {member.display_name}")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
