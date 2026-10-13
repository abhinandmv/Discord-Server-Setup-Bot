"""Suggestions: /suggest posts an idea in the suggestions channel. Members vote
with 👍/👎, and staff mark it ✅ approved or ❌ declined (with an optional reason)."""

from __future__ import annotations

import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.modlog import log_event

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 300
STATUS = {"open": ("💡 Open for votes", ui.BLURPLE), "approved": ("✅ Approved", ui.GREEN),
          "declined": ("❌ Declined", ui.RED)}


def suggestion_embed(row, author: discord.abc.User | None, *, note: str | None = None,
                     by: discord.abc.User | None = None) -> discord.Embed:
    label, colour = STATUS[row["status"]]
    embed = discord.Embed(description=row["text"], colour=colour)
    if author is not None:
        embed.set_author(name=f"{author.display_name} suggests…", icon_url=author.display_avatar.url)
    embed.add_field(name="Status", value=label + (f" by {by.mention}" if by else ""), inline=True)
    if note:
        embed.add_field(name="Staff note", value=ui.clip(note), inline=False)
    embed.set_footer(text=f"Suggestion #{row['id']} · vote with 👍 / 👎")
    return embed


class DecisionButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"suggestion:(?P<action>approve|decline):(?P<id>[0-9]+)"):
    def __init__(self, action: str, suggestion_id: int) -> None:
        approve = action == "approve"
        super().__init__(discord.ui.Button(
            label="Approve" if approve else "Decline", emoji="✅" if approve else "❌",
            style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
            custom_id=f"suggestion:{action}:{suggestion_id}"))
        self.action, self.suggestion_id = action, suggestion_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> DecisionButton:
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Suggestions")
        if not cog.is_staff(interaction.user):
            await interaction.response.send_message("Only staff can approve or decline suggestions.",
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(DecisionModal(cog, self.action, self.suggestion_id))


class DecisionModal(discord.ui.Modal):
    def __init__(self, cog: Suggestions, action: str, suggestion_id: int) -> None:
        super().__init__(title=("Approve" if action == "approve" else "Decline") + " suggestion")
        self.cog, self.action, self.suggestion_id = cog, action, suggestion_id
        self.note = discord.ui.TextInput(label="Note (optional, shown publicly)", required=False,
                                         style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.decide(interaction, self.suggestion_id,
                              "approved" if self.action == "approve" else "declined",
                              self.note.value.strip() or None)


def decision_view(suggestion_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DecisionButton("approve", suggestion_id))
    view.add_item(DecisionButton("decline", suggestion_id))
    return view


class Suggestions(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last: dict[tuple[int, int], float] = {}

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(DecisionButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(DecisionButton)

    def _channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        raw = self.bot.storage.get_setting(guild.id, "suggestions_channel_id")
        channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def is_staff(self, member: discord.Member) -> bool:
        raw = self.bot.storage.get_setting(member.guild.id, "staff_role_id")
        staff = member.guild.get_role(int(raw)) if raw and raw.isdigit() else None
        return (member.guild_permissions.manage_messages
                or (staff is not None and staff in member.roles))

    @app_commands.command(name="suggest", description="Share an idea for the server")
    @app_commands.guild_only()
    @app_commands.describe(idea="Your suggestion")
    async def suggest(self, interaction: discord.Interaction,
                      idea: app_commands.Range[str, 10, 1500]) -> None:
        guild = interaction.guild
        channel = self._channel(guild)
        if channel is None:
            await interaction.response.send_message(
                "This server doesn't have a suggestions channel. Ask the owner to enable "
                "**Suggestions** in /setup.", ephemeral=True)
            return
        key = (guild.id, interaction.user.id)
        wait = COOLDOWN_SECONDS - (time.monotonic() - self._last.get(key, -COOLDOWN_SECONDS))
        if wait > 0:
            await interaction.response.send_message(
                f"Slow down a little: you can suggest again in {int(wait // 60) + 1} minute(s).",
                ephemeral=True)
            return
        storage = self.bot.storage
        sid = storage.add_suggestion(guild.id, interaction.user.id, idea)
        row = storage.suggestion(sid)
        try:
            message = await channel.send(embed=suggestion_embed(row, interaction.user),
                                         view=decision_view(sid))
            for emoji in ("👍", "👎"):
                await message.add_reaction(emoji)
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Couldn't post your suggestion: {exc.text or exc}",
                                                    ephemeral=True)
            return
        self._last[key] = time.monotonic()
        storage.set_suggestion_message(sid, message.id)
        await interaction.response.send_message(f"💡 Posted! See {message.jump_url}", ephemeral=True)

    async def decide(self, interaction: discord.Interaction, suggestion_id: int, status: str,
                     note: str | None) -> None:
        storage = self.bot.storage
        row = storage.suggestion(suggestion_id)
        if row is None or row["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("That suggestion no longer exists.", ephemeral=True)
            return
        if not self.is_staff(interaction.user):  # re-checked: the modal may have sat open
            await interaction.response.send_message("Only staff can do that.", ephemeral=True)
            return
        storage.set_suggestion_status(suggestion_id, status)
        row = storage.suggestion(suggestion_id)
        author = interaction.guild.get_member(row["author_id"])
        await interaction.response.edit_message(
            embed=suggestion_embed(row, author, note=note, by=interaction.user), view=None)
        await log_event(self.bot, interaction.guild, f"💡 Suggestion #{suggestion_id} {status}",
                        f"By {interaction.user.mention}" + (f"\nNote: {note}" if note else ""))
        if author is not None:
            try:
                await author.send(f"Your suggestion in **{interaction.guild.name}** was **{status}**."
                                  + (f"\nNote: {note}" if note else ""))
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Suggestions(bot))
