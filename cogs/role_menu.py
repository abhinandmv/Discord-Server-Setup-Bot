"""Self-assign roles: persistent toggle buttons and reaction roles on the same message."""

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from core import ui
from core.builder import normalize_emoji
from core.permissions import is_safe_self_assign_role
from core.plan import split_leading_emoji

log = logging.getLogger(__name__)


def _assignable_problem(guild: discord.Guild, role: discord.Role | None, allowed: list[int]) -> str | None:
    """Why this role can't be self-assigned right now, or None if it can."""
    if role is None or role.id not in allowed:
        return "That role isn't available anymore."
    # Re-checked on every use in case someone gave the role extra powers later.
    if not is_safe_self_assign_role(role):
        return "That role has moderator permissions now, so it can't be self-assigned."
    if role >= guild.me.top_role:
        return "I can't manage that role. Ask an admin to move my role above it."
    return None


class RoleToggleButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"rolemenu:(?P<role_id>[0-9]+)"):
    """Survives restarts: discord.py rebuilds it from the custom_id on every click."""

    def __init__(self, role_id: int, label: str = "Role",
                 emoji: str | discord.PartialEmoji | None = None) -> None:
        super().__init__(discord.ui.Button(label=label, emoji=emoji,
                                           style=discord.ButtonStyle.secondary,
                                           custom_id=f"rolemenu:{role_id}"))
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> RoleToggleButton:
        return cls(int(match["role_id"]), label=item.label or "Role", emoji=item.emoji)

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        allowed = interaction.client.storage.get_json(guild.id, "self_roles", None) or []
        role = guild.get_role(self.role_id)
        problem = _assignable_problem(guild, role, allowed)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Self-assign role menu")
                text = f"Removed {role.mention}."
            else:
                await member.add_roles(role, reason="Self-assign role menu")
                text = f"Gave you {role.mention}."
        except discord.HTTPException as exc:
            log.warning("Role toggle failed in %s: %s", guild.id, exc)
            text = "I couldn't change your roles. Please tell a moderator."
        await interaction.response.send_message(text, ephemeral=True)


def build_role_menu(pairs: list[tuple[discord.Role, str]]) -> tuple[discord.Embed, discord.ui.View]:
    """pairs = [(role, emoji)]. The same emoji is used for the button and the reaction."""
    pairs = pairs[:20]
    embed = discord.Embed(
        title="🏷️ Pick your roles",
        description="**Click a button** to add or remove a role, "
                    "or **react with the emoji** (remove your reaction to drop the role).\n\n"
                    + "\n".join(f"{emoji}  {role.mention}" for role, emoji in pairs),
        colour=ui.BLURPLE)
    view = discord.ui.View(timeout=None)
    for role, emoji in pairs:
        _, label = split_leading_emoji(role.name)
        view.add_item(RoleToggleButton(role.id, label=label[:80], emoji=emoji))
    return embed, view


class RoleMenu(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RoleToggleButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleToggleButton)

    # Raw events fire even for messages that aren't in the bot's cache
    # (e.g. after a restart), and need no privileged intents.
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._on_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._on_reaction(payload, add=False)

    async def _on_reaction(self, payload: discord.RawReactionActionEvent, *, add: bool) -> None:
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        storage = self.bot.storage
        mapping = (storage.get_json(payload.guild_id, "reaction_roles", None) or {}).get(
            str(payload.message_id))
        if not mapping:
            return
        role_id = mapping.get(normalize_emoji(str(payload.emoji)))
        guild = self.bot.get_guild(payload.guild_id)
        if role_id is None or guild is None:
            return

        role = guild.get_role(role_id)
        allowed = storage.get_json(guild.id, "self_roles", None) or []
        problem = _assignable_problem(guild, role, allowed)
        if problem:
            log.info("Reaction role %s skipped in %s: %s", role_id, guild.id, problem)
            return

        try:
            # payload.member is only sent for additions.
            member = payload.member or guild.get_member(payload.user_id) \
                or await guild.fetch_member(payload.user_id)
            if member.bot:
                return
            if add and role not in member.roles:
                await member.add_roles(role, reason="Reaction role")
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="Reaction role removed")
        except discord.HTTPException as exc:
            log.warning("Reaction role failed in %s: %s", guild.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleMenu(bot))
