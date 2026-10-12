"""Welcome messages, the verification gate and the member role.

* New members are greeted in the welcome channel with the server type's
  themed message.
* With verification on, they only see the welcome/rules/verify channels until
  they click Verify, which gives them the member role.
* Without verification, new members get the member role automatically.
* Joins and leaves go to the mod log.

Needs the Server Members intent (Developer Portal -> Bot -> Privileged Gateway Intents).
"""

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

import templates
from core import ui
from core.modlog import log_event
from core.permissions import is_safe_self_assign_role

log = logging.getLogger(__name__)


def member_role(bot, guild: discord.Guild) -> discord.Role | None:
    """The member role, if the bot may still hand it out automatically."""
    raw = bot.storage.get_setting(guild.id, "member_role_id")
    role = guild.get_role(int(raw)) if raw and raw.isdigit() else None
    # Re-checked on every use in case someone gave the role extra powers later.
    if role is None or not is_safe_self_assign_role(role) or role >= guild.me.top_role:
        return None
    return role


class VerifyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"verify:member"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(label="I've read the rules, let me in", emoji="✅",
                                           style=discord.ButtonStyle.success,
                                           custom_id="verify:member"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> VerifyButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        bot, guild, member = interaction.client, interaction.guild, interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        role = member_role(bot, guild)
        if bot.storage.get_setting(guild.id, "verify_enabled") != "1" or role is None:
            await interaction.response.send_message(
                "Verification isn't working right now. Please tell a moderator.", ephemeral=True)
            return
        if role in member.roles:
            await interaction.response.send_message("You're already verified. 🎉", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="Verified via button")
        except discord.HTTPException as exc:
            log.warning("Verify failed in %s: %s", guild.id, exc)
            await interaction.response.send_message(
                "I couldn't verify you. Please tell a moderator.", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ You're verified! The rest of the server is now unlocked.", ephemeral=True)
        await log_event(bot, guild, "✅ Member verified", f"{member.mention} ({member})",
                        colour=ui.GREEN)


def build_verify_panel(role: discord.Role,
                       rules: discord.abc.GuildChannel | None) -> tuple[discord.Embed, discord.ui.View]:
    rules_text = f"Read {rules.mention}, then" if rules else "Read the rules, then"
    embed = discord.Embed(
        title="✅ Verify to enter",
        description=f"{rules_text} click the button below to get {role.mention} and unlock the "
                    "rest of the server.",
        colour=ui.GREEN)
    view = discord.ui.View(timeout=None)
    view.add_item(VerifyButton())
    return embed, view


def build_rules_embed(server_type: str) -> tuple[discord.Embed, None] | None:
    """The server type's themed rules, or None if it has none."""
    rules = templates.SERVER_TYPES.get(server_type, {}).get("rules")
    if not rules:
        return None
    embed = discord.Embed(title=rules["title"], colour=ui.BLURPLE,
                          description="Breaking these can get you warned, muted or removed.")
    for n, (emoji, rule, details) in enumerate(rules["items"], 1):
        embed.add_field(name=f"{emoji} {n}. {rule}"[:256], value=details[:1024], inline=False)
    embed.set_footer(text="Moderators may act on anything that harms the community, "
                          "even if it isn't listed here.")
    return embed, None


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(VerifyButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(VerifyButton)

    def _channel(self, guild: discord.Guild, key: str) -> discord.TextChannel | None:
        raw = self.bot.storage.get_setting(guild.id, key)
        channel = guild.get_channel(int(raw)) if raw and raw.isdigit() else None
        return channel if isinstance(channel, discord.TextChannel) else None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        storage = self.bot.storage
        if not storage.get_setting(guild.id, "server_type"):
            return  # /setup hasn't run here
        verify = storage.get_setting(guild.id, "verify_enabled") == "1"

        if not verify and not member.bot and (role := member_role(self.bot, guild)):
            try:
                await member.add_roles(role, reason="Auto-role for new members")
            except discord.HTTPException as exc:
                log.warning("Auto-role failed in %s: %s", guild.id, exc)

        channel = self._channel(guild, "welcome_channel_id")
        if channel is not None and not member.bot:
            await self._greet(channel, member, verify)

        await log_event(self.bot, guild, "📥 Member joined",
                        f"{member.mention} ({member})\nAccount created "
                        f"{discord.utils.format_dt(member.created_at, 'R')}", colour=ui.GREEN)

    async def _greet(self, channel: discord.TextChannel, member: discord.Member,
                     verify: bool) -> None:
        server_type = self.bot.storage.get_setting(member.guild.id, "server_type")
        message = templates.SERVER_TYPES.get(server_type, {}).get(
            "welcome_message", "👋 Welcome to the server, **{user}**!")
        text = message.format(user=discord.utils.escape_markdown(member.display_name))
        if verify and (verify_channel := self._channel(member.guild, "verify_channel_id")):
            text += f"\n\nHead to {verify_channel.mention} to unlock the rest of the server."
        embed = discord.Embed(description=text, colour=ui.BLURPLE)
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.guild.member_count:
            embed.set_footer(text=f"Member #{member.guild.member_count:,}")
        try:
            await channel.send(content=member.mention, embed=embed,
                               allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException as exc:
            log.info("Couldn't post welcome in %s: %s", member.guild.id, exc)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not self.bot.storage.get_setting(member.guild.id, "server_type"):
            return
        await log_event(self.bot, member.guild, "📤 Member left", f"{member.mention} ({member})",
                        colour=ui.YELLOW)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
