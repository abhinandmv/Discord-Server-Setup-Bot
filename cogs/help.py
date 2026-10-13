"""/help: lists the commands *this person* can use, grouped by who they're for."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.permissions import MOD_COMMAND_PERMISSIONS, is_server_owner

OWNER_COMMANDS = {"setup", "reset", "backup", "restore", "template apply"}


def required_permission(qualified_name: str) -> str | None:
    """The moderator permission a command needs, if any (see MOD_COMMAND_PERMISSIONS)."""
    return (MOD_COMMAND_PERMISSIONS.get(qualified_name.replace(" ", "_"))
            or MOD_COMMAND_PERMISSIONS.get(qualified_name.split()[0]))


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show the commands you can use")
    @app_commands.guild_only()
    async def help(self, interaction: discord.Interaction) -> None:
        user, guild = interaction.user, interaction.guild
        perms = user.guild_permissions
        owner = is_server_owner(user, guild)
        tiers: dict[str, list[str]] = {"owner": [], "mod": [], "everyone": []}
        for cmd in sorted(self.bot.tree.walk_commands(), key=lambda c: c.qualified_name):
            if isinstance(cmd, app_commands.Group):
                continue
            line = f"`/{cmd.qualified_name}` · {cmd.description}"
            if cmd.qualified_name in OWNER_COMMANDS:
                if owner:
                    tiers["owner"].append(line)
            elif (perm := required_permission(cmd.qualified_name)) is not None:
                if perms.administrator or getattr(perms, perm):
                    tiers["mod"].append(line)
            else:
                tiers["everyone"].append(line)

        embed = discord.Embed(title="🧙 What I can do for you", colour=ui.BLURPLE,
                              description="Only commands you're allowed to use are listed.")
        for key, title in (("owner", "🔒 Server owner"), ("mod", "🛡️ Moderators"),
                           ("everyone", "👥 Everyone")):
            if tiers[key]:
                embed.add_field(name=title, value=ui.bullet_list(tiers[key]), inline=False)
        tips = []
        if self.bot.storage.get_setting(guild.id, "voice_hubs"):
            tips.append("➕ Join the **Create a room** voice channel to get your own room.")
        if self.bot.storage.get_setting(guild.id, "reaction_roles"):
            tips.append("✨ React in the reaction-roles channel to pick your roles.")
        if tips:
            embed.add_field(name="Tips", value="\n".join(tips), inline=False)
        await interaction.response.send_message(embed=ui.fit_embed(embed), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
