"""Support tickets: members open a private channel with a button; only mods close it.

The ticket category only exists while at least one ticket is open: it's
created with the first ticket and deleted when the last one closes. A ticket
channel is visible to the ticket role, the member who opened it, and the bot.
Everything here is tracked, so /reset removes it too.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict

import discord
from discord.ext import commands

import templates
from core import ui
from core.permissions import PermissionContext, overwrites_for
from core.plan import text_channel_name
from core.retry import call_with_retry, describe_error

log = logging.getLogger(__name__)

OWNER_MARKER = "owner:"


def _owner_id(channel: discord.abc.GuildChannel) -> int | None:
    topic = getattr(channel, "topic", None) or ""
    if OWNER_MARKER not in topic:
        return None
    raw = topic.rsplit(OWNER_MARKER, 1)[1].strip()
    return int(raw) if raw.isdigit() else None


class OpenTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:open"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(label="Open a ticket", emoji="🎫",
                                           style=discord.ButtonStyle.primary,
                                           custom_id="ticket:open"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> OpenTicketButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.client.get_cog("Tickets").open_ticket(interaction)


class CloseTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:close"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(label="Close ticket (staff)", emoji="🔒",
                                           style=discord.ButtonStyle.danger,
                                           custom_id="ticket:close"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> CloseTicketButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.client.get_cog("Tickets").close_ticket(interaction)


def build_ticket_panel() -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(
        title="🎫 Need help?",
        description="Click the button below to open a **private ticket** with the team.\n"
                    "Only you and the staff can see it. A moderator will close it once your "
                    "issue is resolved.",
        colour=ui.BLURPLE)
    view = discord.ui.View(timeout=None)
    view.add_item(OpenTicketButton())
    return embed, view


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # One open/close at a time per guild, so two members can't race to
        # create (or delete) the ticket category.
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(OpenTicketButton, CloseTicketButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(OpenTicketButton, CloseTicketButton)

    def _role(self, guild: discord.Guild, key: str) -> discord.Role | None:
        raw = self.bot.storage.get_setting(guild.id, key)
        return guild.get_role(int(raw)) if raw and raw.isdigit() else None

    def _is_staff(self, member: discord.Member, channel: discord.abc.GuildChannel) -> bool:
        roles = [self._role(member.guild, "ticket_role_id"), self._role(member.guild, "staff_role_id")]
        return (channel.permissions_for(member).manage_channels
                or any(r is not None and r in member.roles for r in roles))

    async def _ticket_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        """Return the ticket category, creating it if no ticket is open right now."""
        storage = self.bot.storage
        raw = storage.get_setting(guild.id, "ticket_category_id")
        category = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        if isinstance(category, discord.CategoryChannel):
            return category

        ctx = PermissionContext(guild=guild, staff=self._role(guild, "staff_role_id"),
                                muted=self._role(guild, "muted_role_id"),
                                ticket_role=self._role(guild, "ticket_role_id"))
        name = (storage.get_setting(guild.id, "ticket_category_name")
                or templates.CATEGORIES[templates.TICKET_CATEGORY]["name"])
        category = await call_with_retry(
            lambda: guild.create_category(name, overwrites=overwrites_for("tickets", ctx),
                                          reason="First open ticket"),
            delay=0)
        storage.track(guild.id, category.id, "category", category.name)
        storage.set_setting(guild.id, "ticket_category_id", str(category.id))
        return category

    async def open_ticket(self, interaction: discord.Interaction) -> None:
        guild, user = interaction.guild, interaction.user
        if self.bot.storage.get_setting(guild.id, "tickets_enabled") != "1":
            await interaction.response.send_message("Tickets aren't set up in this server.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        async with self._locks[guild.id]:
            raw = self.bot.storage.get_setting(guild.id, "ticket_category_id")
            current = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
            if isinstance(current, discord.CategoryChannel):
                existing = next((c for c in current.text_channels if _owner_id(c) == user.id), None)
                if existing:
                    await interaction.followup.send(
                        f"You already have an open ticket: {existing.mention}", ephemeral=True)
                    return
            try:
                category = await self._ticket_category(guild)
                overwrites = dict(category.overwrites)
                overwrites[user] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    attach_files=True, embed_links=True)
                name = text_channel_name(
                    f"{templates.TICKET_CHANNEL_EMOJI}{templates.SEP}ticket-{user.name}")
                channel = await call_with_retry(
                    lambda: guild.create_text_channel(
                        name, category=category, overwrites=overwrites,
                        topic=f"Support ticket for {user} · {OWNER_MARKER}{user.id}",
                        reason=f"Ticket opened by {user}"),
                    delay=0)
            except discord.HTTPException as exc:
                await interaction.followup.send(f"Couldn't create your ticket: {describe_error(exc)}",
                                                ephemeral=True)
                return
            self.bot.storage.track(guild.id, channel.id, "channel", channel.name, category.id)

        role = self._role(guild, "ticket_role_id")
        view = discord.ui.View(timeout=None)
        view.add_item(CloseTicketButton())
        await channel.send(
            content=" ".join(m for m in (user.mention, role.mention if role else "") if m),
            embed=discord.Embed(
                title="🎫 Ticket opened",
                description="Describe your issue and a moderator will be with you soon.\n"
                            "The team will close this ticket once it's resolved.",
                colour=ui.BLURPLE),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        channel, member = interaction.channel, interaction.user
        owner_id = _owner_id(channel) if isinstance(channel, discord.TextChannel) else None
        if owner_id is None:
            await interaction.response.send_message("This isn't a ticket channel.", ephemeral=True)
            return
        if not self._is_staff(member, channel):
            await interaction.response.send_message(
                "Only moderators can close tickets. A moderator will close this one once your "
                "issue is resolved.", ephemeral=True)
            return

        await interaction.response.send_message(f"🔒 Ticket closed by {member.mention}. "
                                                "Deleting this channel in 5 seconds…")
        await asyncio.sleep(5)
        guild = interaction.guild
        storage = self.bot.storage
        async with self._locks[guild.id]:
            category = channel.category
            try:
                await channel.delete(reason=f"Ticket closed by {member}")
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                await interaction.followup.send(f"Couldn't delete the channel: {describe_error(exc)}")
                return
            storage.untrack(guild.id, channel.id)

            # Last ticket closed -> remove the category so it disappears for everyone.
            if (category is not None
                    and str(category.id) == storage.get_setting(guild.id, "ticket_category_id")
                    and not [c for c in category.channels if c.id != channel.id]):
                try:
                    await category.delete(reason="No open tickets")
                except discord.NotFound:
                    pass
                except discord.HTTPException as exc:
                    log.warning("Couldn't delete empty ticket category in %s: %s", guild.id, exc)
                    return
                storage.untrack(guild.id, category.id)
                storage.delete_setting(guild.id, "ticket_category_id")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
