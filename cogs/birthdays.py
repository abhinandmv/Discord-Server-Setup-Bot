"""Birthdays: members save theirs with /birthday set (day and month only, no year).
On the day (UTC) they get the 🎂 Birthday role and a themed shout-out in the
birthdays channel; the role comes off again the next day."""

from __future__ import annotations

import calendar
import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import templates
from core import ui
from core.permissions import is_safe_self_assign_role

log = logging.getLogger(__name__)

MONTHS = [app_commands.Choice(name=calendar.month_name[m], value=m) for m in range(1, 13)]


def today_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def is_birthday(month: int, day: int, date: datetime.date) -> bool:
    """29 February birthdays are celebrated on 28 February in non-leap years."""
    if (month, day) == (date.month, date.day):
        return True
    return ((month, day) == (2, 29) and not calendar.isleap(date.year)
            and (date.month, date.day) == (2, 28))


class Birthdays(commands.Cog):
    birthday = app_commands.Group(name="birthday", description="Birthday shout-outs",
                                  guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.daily.start()

    async def cog_unload(self) -> None:
        self.daily.cancel()

    def _enabled(self, guild: discord.Guild) -> bool:
        raw = self.bot.storage.get_setting(guild.id, "birthday_channel_id")
        return bool(raw) or bool(self.bot.storage.get_setting(guild.id, "birthday_role_id"))

    @birthday.command(name="set", description="Save your birthday (no year needed)")
    @app_commands.choices(month=MONTHS)
    async def set_(self, interaction: discord.Interaction, month: app_commands.Choice[int],
                   day: app_commands.Range[int, 1, 31]) -> None:
        if day > calendar.monthrange(2024, month.value)[1]:  # 2024 is a leap year: allows 29 Feb
            await interaction.response.send_message(f"{month.name} doesn't have {day} days.",
                                                    ephemeral=True)
            return
        if not self._enabled(interaction.guild):
            await interaction.response.send_message(
                "Birthdays aren't turned on here. Ask the owner to enable them in /setup.",
                ephemeral=True)
            return
        self.bot.storage.set_birthday(interaction.guild.id, interaction.user.id, month.value, day)
        await interaction.response.send_message(f"🎂 Saved: **{day} {month.name}**. "
                                                "I'll celebrate you on the day!", ephemeral=True)

    @birthday.command(name="remove", description="Forget your birthday")
    async def remove(self, interaction: discord.Interaction) -> None:
        removed = self.bot.storage.remove_birthday(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message("Done, your birthday is forgotten." if removed
                                                else "I didn't have your birthday saved.",
                                                ephemeral=True)

    @birthday.command(name="upcoming", description="Birthdays in the next 30 days")
    async def upcoming(self, interaction: discord.Interaction) -> None:
        today = today_utc()
        soon = []
        for user_id, month, day in self.bot.storage.birthdays(interaction.guild.id):
            if interaction.guild.get_member(user_id) is None:
                continue
            for offset in range(31):
                date = today + datetime.timedelta(days=offset)
                if is_birthday(month, day, date):
                    soon.append((offset, date, user_id))
                    break
        soon.sort()
        lines = [f"{'🎉 **Today**' if o == 0 else f'**{d.day} {calendar.month_abbr[d.month]}**'} · <@{u}>"
                 for o, d, u in soon]
        await interaction.response.send_message(
            embed=discord.Embed(title="🎂 Upcoming birthdays",
                                description=ui.bullet_list(lines, 4000) if lines else
                                "No birthdays in the next 30 days.", colour=0xFF69B4),
            ephemeral=True)

    # ------------------------------------------------------------------ #
    @tasks.loop(minutes=30)
    async def daily(self) -> None:
        today = today_utc()
        for guild in self.bot.guilds:
            try:
                await self._run_for(guild, today)
            except Exception:
                log.exception("Birthday check failed in %s", guild.id)

    @daily.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _run_for(self, guild: discord.Guild, today: datetime.date) -> None:
        storage = self.bot.storage
        if not self._enabled(guild) or storage.get_setting(guild.id, "birthday_last_run") == today.isoformat():
            return
        storage.set_setting(guild.id, "birthday_last_run", today.isoformat())

        raw = storage.get_setting(guild.id, "birthday_role_id")
        role = guild.get_role(int(raw)) if raw and raw.isdigit() else None
        if role is not None and (not is_safe_self_assign_role(role) or role >= guild.me.top_role):
            role = None  # someone gave it powers (or moved it above me): stop handing it out

        # Yesterday's birthday people lose the role.
        holders = set(storage.get_json(guild.id, "birthday_role_holders", None) or [])
        if role is not None:
            for user_id in holders:
                member = guild.get_member(user_id)
                if member is not None and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Birthday is over")
                    except discord.HTTPException:
                        pass

        celebrating = [guild.get_member(u) for u, m, d in storage.birthdays(guild.id)
                       if is_birthday(m, d, today)]
        celebrating = [m for m in celebrating if m is not None]
        storage.set_json(guild.id, "birthday_role_holders", [m.id for m in celebrating])
        if not celebrating:
            return
        if role is not None:
            for member in celebrating:
                try:
                    await member.add_roles(role, reason="Happy birthday!")
                except discord.HTTPException:
                    pass

        raw = storage.get_setting(guild.id, "birthday_channel_id")
        channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return
        server_type = storage.get_setting(guild.id, "server_type")
        pattern = templates.SERVER_TYPES.get(server_type, {}).get(
            "birthday_message", templates.DEFAULT_BIRTHDAY_MESSAGE)
        for member in celebrating:
            embed = discord.Embed(description=pattern.format(user=member.mention), colour=0xFF69B4)
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await channel.send(content=member.mention, embed=embed,
                                   allowed_mentions=ui.PING_USERS)
            except discord.HTTPException as exc:
                log.info("Couldn't post birthday in %s: %s", guild.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Birthdays(bot))
