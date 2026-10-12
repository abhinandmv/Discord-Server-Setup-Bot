"""Leveling: XP for chatting, themed rank roles as rewards, /rank and /leaderboard.

Message events arrive without the Message Content intent; the bot only counts
messages, it never reads them.
"""

from __future__ import annotations

import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import templates
from core import ui
from core.permissions import is_safe_self_assign_role

log = logging.getLogger(__name__)


def xp_to_next(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1`` (gentle quadratic curve)."""
    return 5 * level * level + 50 * level + 100


def level_for_xp(xp: int) -> tuple[int, int, int]:
    """(level, XP into the current level, XP needed for the next level)."""
    level = 0
    while xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    return level, xp, xp_to_next(level)


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_xp: dict[tuple[int, int], float] = {}

    def _enabled(self, guild: discord.Guild) -> bool:
        return self.bot.storage.get_setting(guild.id, "leveling_enabled") == "1"

    def _rewards(self, guild: discord.Guild) -> list[tuple[int, discord.Role]]:
        """(level, role) pairs the bot may still hand out, lowest level first."""
        raw = self.bot.storage.get_json(guild.id, "level_roles", None) or {}
        out = []
        for level, role_id in raw.items():
            role = guild.get_role(role_id)
            # Re-checked on every use in case someone gave the role extra powers later.
            if role and is_safe_self_assign_role(role) and role < guild.me.top_role:
                out.append((int(level), role))
        return sorted(out, key=lambda p: p[0])

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        guild = message.guild
        if (guild is None or message.author.bot or message.webhook_id
                or not isinstance(message.author, discord.Member) or not self._enabled(guild)):
            return
        key = (guild.id, message.author.id)
        now = time.monotonic()
        if now - self._last_xp.get(key, 0.0) < templates.XP_COOLDOWN_SECONDS:
            return
        self._last_xp[key] = now

        storage = self.bot.storage
        before = level_for_xp(storage.get_xp(guild.id, message.author.id))[0]
        after = level_for_xp(storage.add_xp(guild.id, message.author.id,
                                            random.randint(*templates.XP_PER_MESSAGE)))[0]
        if after > before:
            await self._level_up(message, after)

    async def _level_up(self, message: discord.Message, level: int) -> None:
        member, guild = message.author, message.guild
        earned = [role for need, role in self._rewards(guild)
                  if need <= level and role not in member.roles]
        if earned:
            try:
                await member.add_roles(*earned, reason=f"Reached level {level}")
            except discord.HTTPException as exc:
                log.warning("Level reward failed in %s: %s", guild.id, exc)
                earned = []

        text = f"⭐ {member.mention} reached **level {level}**!"
        if earned:
            text += "\nUnlocked " + ", ".join(r.mention for r in earned) + " 🎉"
        raw = self.bot.storage.get_setting(guild.id, "level_channel_id")
        channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            channel = message.channel
        try:
            # Mentions render but don't ping, so level-ups never get noisy.
            await channel.send(embed=discord.Embed(description=text, colour=ui.GREEN),
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @app_commands.command(name="rank", description="Show your level and XP (or someone else's)")
    @app_commands.guild_only()
    @app_commands.describe(member="Whose rank to show (default: you)")
    async def rank(self, interaction: discord.Interaction,
                   member: discord.Member | None = None) -> None:
        guild = interaction.guild
        if not self._enabled(guild):
            await interaction.response.send_message("Leveling isn't turned on in this server.",
                                                    ephemeral=True)
            return
        member = member or interaction.user
        storage = self.bot.storage
        xp = storage.get_xp(guild.id, member.id)
        level, into, needed = level_for_xp(xp)
        embed = discord.Embed(
            title=f"⭐ {member.display_name}",
            description=(f"**Level {level}** · rank **#{storage.xp_rank(guild.id, member.id)}**\n"
                         f"{ui.progress_bar(into / needed)} {into:,}/{needed:,} XP\n"
                         f"Total: {xp:,} XP"),
            colour=ui.BLURPLE)
        embed.set_thumbnail(url=member.display_avatar.url)
        upcoming = [(need, role) for need, role in self._rewards(guild) if need > level]
        if upcoming:
            need, role = upcoming[0]
            embed.add_field(name="Next reward", value=f"{role.mention} at level {need}")
        await interaction.response.send_message(embed=embed,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="leaderboard", description="Top 10 most active members")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not self._enabled(guild):
            await interaction.response.send_message("Leveling isn't turned on in this server.",
                                                    ephemeral=True)
            return
        top = self.bot.storage.leaderboard(guild.id, 10)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [f"{medals.get(i, f'`#{i}`')} <@{user_id}> · level **{level_for_xp(xp)[0]}** "
                 f"({xp:,} XP)" for i, (user_id, xp) in enumerate(top, 1)]
        embed = discord.Embed(title="🏆 Leaderboard",
                              description="\n".join(lines) or "Nobody has earned XP yet. Start chatting!",
                              colour=ui.BLURPLE)
        await interaction.response.send_message(embed=embed,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Leveling(bot))
