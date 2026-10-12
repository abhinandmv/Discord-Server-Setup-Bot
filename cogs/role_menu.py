"""Reaction roles: one message per group in the reaction-roles channel. React to
get a role, remove the reaction to drop it; pick-one groups swap roles.

Role menus posted by older versions (toggle buttons and dropdowns) keep working
through the persistent handlers below, but new setups only post reaction roles."""

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from core import ui
from core.builder import normalize_emoji
from core.permissions import is_safe_self_assign_role

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


class RoleGroupSelect(discord.ui.DynamicItem[discord.ui.Select],
                      template=r"rolegroup:(?P<index>[0-9]+)"):
    """One dropdown per role group. Choosing sets your roles *within this group*
    to exactly what you picked; roles outside the group are untouched.

    The group's role IDs are the dropdown's own option values, so nothing extra
    needs storing: discord.py rebuilds the select from the message on each use.
    """

    def __init__(self, index: int, *, placeholder: str = "Pick roles…",
                 options: list[discord.SelectOption] | None = None,
                 max_values: int = 1) -> None:
        options = options or [discord.SelectOption(label="(none)", value="0")]
        super().__init__(discord.ui.Select(
            custom_id=f"rolegroup:{index}", placeholder=placeholder, options=options,
            min_values=0, max_values=max(1, min(max_values, len(options)))))
        self.index = index

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select,
                             match: re.Match[str], /) -> RoleGroupSelect:
        return cls(int(match["index"]), placeholder=item.placeholder or "Pick roles…",
                   options=item.options, max_values=item.max_values)

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        allowed = interaction.client.storage.get_json(guild.id, "self_roles", None) or []
        group_ids = [int(o.value) for o in self.item.options if o.value.isdigit()]
        chosen = {int(v) for v in self.item.values if v.isdigit()}

        add, remove, problems = [], [], []
        for role_id in group_ids:
            role = guild.get_role(role_id)
            wanted, has = role_id in chosen, role is not None and role in member.roles
            if wanted == has:
                continue
            problem = _assignable_problem(guild, role, allowed)
            if problem:
                if wanted:
                    problems.append(problem)
                continue
            (add if wanted else remove).append(role)

        try:
            if remove:
                await member.remove_roles(*remove, reason="Self-assign role menu")
            if add:
                await member.add_roles(*add, reason="Self-assign role menu")
        except discord.HTTPException as exc:
            log.warning("Role menu failed in %s: %s", guild.id, exc)
            await interaction.response.send_message(
                "I couldn't change your roles. Please tell a moderator.", ephemeral=True)
            return

        lines = [f"Added {r.mention}" for r in add] + [f"Removed {r.mention}" for r in remove]
        lines += sorted(set(problems))
        await interaction.response.send_message("\n".join(lines) or "No changes.", ephemeral=True)


RoleGroup = tuple[str, bool, list[tuple[discord.Role, str]]]


def build_reaction_message(group: RoleGroup, *, first: bool = False) -> discord.Embed:
    """One reaction-roles message: (group name, pick-one?, [(role, emoji)])."""
    name, exclusive, pairs = group
    how = ("React to **pick one**. Choosing another swaps it." if exclusive
           else "React to get a role. Remove your reaction to drop it.")
    embed = discord.Embed(
        title=f"✨ {name}"[:256],
        description=how + "\n\n" + "\n".join(f"{emoji}  {role.mention}" for role, emoji in pairs[:20]),
        colour=ui.BLURPLE)
    if first:
        embed.set_author(name="Reaction roles")
    return embed


class RoleMenu(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RoleToggleButton, RoleGroupSelect)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleToggleButton, RoleGroupSelect)

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
                await self._enforce_pick_one(guild, member, role, mapping, payload)
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="Reaction role removed")
        except discord.HTTPException as exc:
            log.warning("Reaction role failed in %s: %s", guild.id, exc)


    async def _enforce_pick_one(self, guild: discord.Guild, member: discord.Member,
                                role: discord.Role, mapping: dict[str, int],
                                payload: discord.RawReactionActionEvent) -> None:
        """In a pick-one group, reacting for one role drops the others (and their reactions)."""
        groups = self.bot.storage.get_json(guild.id, "exclusive_role_groups", None) or []
        group = next((g for g in groups if role.id in g), None)
        if not group:
            return
        others = [r for r in member.roles if r.id in group and r.id != role.id]
        if others:
            await member.remove_roles(*others, reason="Pick-one role group")
        channel = guild.get_channel(payload.channel_id)
        if channel is None:
            return
        message = channel.get_partial_message(payload.message_id)
        dropped = {r.id for r in others}
        for emoji, role_id in mapping.items():
            if role_id in dropped:  # only reactions they actually had
                try:
                    await message.remove_reaction(emoji, member)
                except discord.HTTPException:
                    pass  # cosmetic only; the role is already gone


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleMenu(bot))
