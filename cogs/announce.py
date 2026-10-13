"""/announce: staff write a styled announcement in a pop-up form and the bot posts it."""

from __future__ import annotations

import re
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.modlog import log_event
from core.permissions import mod_command

COLOURS = {"blurple": ui.BLURPLE, "green": ui.GREEN, "yellow": ui.YELLOW, "red": ui.RED,
           "gold": 0xF1C40F, "pink": 0xFF69B4, "purple": 0x9B59B6, "teal": 0x1ABC9C}


def parse_colour(text: str) -> int | None:
    text = (text or "").strip().lower()
    if not text:
        return ui.BLURPLE
    if text in COLOURS:
        return COLOURS[text]
    if re.fullmatch(r"#?[0-9a-f]{6}", text):
        return int(text.lstrip("#"), 16)
    return None


class AnnounceModal(discord.ui.Modal, title="New announcement"):
    heading = discord.ui.TextInput(label="Title", max_length=256)
    body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=4000)
    colour = discord.ui.TextInput(label="Colour (name like gold/red, or #hex)", required=False,
                                  max_length=20, placeholder="blurple")

    def __init__(self, channel: discord.TextChannel, ping: str) -> None:
        super().__init__()
        self.channel, self.ping = channel, ping

    async def on_submit(self, interaction: discord.Interaction) -> None:
        colour = parse_colour(self.colour.value)
        if colour is None:
            await interaction.response.send_message(
                f"I don't know the colour `{self.colour.value}`. Use one of "
                f"{', '.join(COLOURS)} or a hex code like #ff8800.", ephemeral=True)
            return
        embed = discord.Embed(title=self.heading.value, description=self.body.value, colour=colour)
        embed.set_footer(text=f"Posted by {interaction.user.display_name}",
                         icon_url=interaction.user.display_avatar.url)
        content = {"everyone": "@everyone", "here": "@here"}.get(self.ping)
        try:
            message = await self.channel.send(
                content=content, embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=content is not None))
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Couldn't post it: {exc.text or exc}",
                                                    ephemeral=True)
            return
        await interaction.response.send_message(f"📣 Posted: {message.jump_url}", ephemeral=True)
        await log_event(interaction.client, interaction.guild, "📣 Announcement posted",
                        f"**{self.heading.value}** in {self.channel.mention} by "
                        f"{interaction.user.mention}")


class Announce(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="announce", description="Post a styled announcement")
    @app_commands.guild_only()
    @mod_command("announce")
    @app_commands.describe(channel="Where to post it (default: here)",
                           ping="Who to notify")
    async def announce(self, interaction: discord.Interaction,
                       channel: discord.TextChannel | None = None,
                       ping: Literal["none", "here", "everyone"] = "none") -> None:
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Pick a text channel.", ephemeral=True)
            return
        # The bot must not post where the person couldn't post themselves.
        mine = channel.permissions_for(interaction.user)
        if not (mine.view_channel and mine.send_messages):
            await interaction.response.send_message(f"You can't post in {channel.mention}.",
                                                    ephemeral=True)
            return
        if ping != "none" and not mine.mention_everyone:
            await interaction.response.send_message(
                "You don't have permission to ping @everyone or @here there.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnounceModal(channel, ping))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Announce(bot))
