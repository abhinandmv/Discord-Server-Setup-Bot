"""/backup and /restore: save the server's channel layout and bring it back.

A backup is taken automatically before anything deletes channels (fresh start,
restore, template apply). Backups hold channel names, settings, order and
permissions, not messages: Discord has no way to bring deleted messages back.
"""

from __future__ import annotations

import logging
from typing import Callable

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.layout import LayoutApplier, LayoutResult, layout_counts, snapshot
from core.permissions import is_server_owner, missing_bot_permissions, owner_only
from core.wipe import deletable_count

log = logging.getLogger(__name__)



def counts_text(layout: dict) -> str:
    roles, cats, chans = layout_counts(layout)
    return f"**{chans}** channels in **{cats}** categories"


def layout_result_embed(result: LayoutResult, title: str) -> discord.Embed:
    ok = not result.errors
    c = result.created
    lines = []
    if result.deleted:
        lines.append(f"🧹 Deleted **{result.deleted['channel']}** channels"
                     + (f" and **{result.deleted['role']}** old bot roles" if result.deleted["role"] else "")
                     + ".")
    lines.append(f"Created **{c['role']}** roles, **{c['category']}** categories and "
                 f"**{c['channel']}** channels.")
    if result.backup_id:
        lines.append(f"💾 The previous layout was saved as backup **#{result.backup_id}** "
                     "(`/restore` to go back).")
    embed = discord.Embed(title=title if ok else "⚠️ Finished with problems",
                          description="\n".join(lines), colour=ui.GREEN if ok else ui.YELLOW)
    if result.reused:
        embed.add_field(name=f"♻️ Already existed ({len(result.reused)})",
                        value=ui.bullet_list(result.reused), inline=False)
    if result.warnings:
        embed.add_field(name="⚠️ Warnings", value=ui.bullet_list([f"• {w}" for w in result.warnings]),
                        inline=False)
    if result.errors:
        embed.add_field(name="❌ Errors", value=ui.bullet_list([f"• {e}" for e in result.errors]),
                        inline=False)
    return ui.fit_embed(embed)


async def run_layout_job(bot, interaction: discord.Interaction,
                         make_applier: Callable[[ui.ProgressReporter], LayoutApplier],
                         title: str, done_title: str) -> None:
    """Run a LayoutApplier with the guild lock, live progress and a summary."""
    guild = interaction.guild
    lock = bot.guild_lock(guild.id)

    async def reply(embed: discord.Embed) -> None:
        if interaction.message is not None:
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    if lock.locked():
        await reply(discord.Embed(description="A setup, reset or restore is already running here. "
                                              "Try again when it finishes.", colour=ui.YELLOW))
        return
    async with lock:
        # Permissions may have changed while the confirmation was open.
        if not is_server_owner(interaction.user, guild):
            await reply(discord.Embed(description="Only the server owner can do this. Nothing was "
                                                  "changed.", colour=ui.RED))
            return
        missing = missing_bot_permissions(guild.me.guild_permissions)
        if missing:
            await reply(discord.Embed(description="I'm missing permissions: " + ", ".join(missing),
                                      colour=ui.RED))
            return

        await reply(ui.progress_embed(title, "Starting", 0, 1, 0, 1))
        reporter = ui.ProgressReporter(interaction, title)
        try:
            result = await make_applier(reporter).run()
        except Exception:
            log.exception("Layout job crashed in guild %s", guild.id)
            await reporter.finish(discord.Embed(
                title="❌ Stopped unexpectedly",
                description="Something went wrong part-way through. Check the bot logs. A backup "
                            "was saved before anything was deleted; see `/restore`.",
                colour=ui.RED))
            return
        embed = layout_result_embed(result, done_title)
        # The channel this started in may have been deleted; post the summary elsewhere.
        if not await reporter.finish(embed) and result.home_channel:
            try:
                await result.home_channel.send(content=interaction.user.mention, embed=embed,
                                               allowed_mentions=ui.PING_USERS)
            except discord.HTTPException as exc:
                log.warning("Couldn't post summary: %s", exc)


class RestoreView(discord.ui.View):
    def __init__(self, cog: Backup, owner_id: int, backups: list) -> None:
        super().__init__(timeout=600)
        self.cog, self.owner_id = cog, owner_id
        self.chosen: int | None = None
        select = discord.ui.Select(
            placeholder="Choose a backup…",
            options=[discord.SelectOption(label=f"#{b['id']} · {b['label']}"[:100], value=str(b["id"]),
                                          description=f"Saved {b['created_at']} UTC")
                     for b in backups[:25]])
        select.callback = self.on_select
        self.select = select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def on_select(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        self.chosen = int(self.select.values[0])
        layout = self.cog.bot.storage.get_backup(guild.id, self.chosen)
        if layout is None:
            await interaction.response.edit_message(
                embed=discord.Embed(description="That backup no longer exists.", colour=ui.RED),
                view=None)
            return
        embed = discord.Embed(
            title=f"♻️ Restore backup #{self.chosen}?",
            description=(f"This **deletes {deletable_count(guild, interaction.user)} current "
                         f"channels and categories** (any you can't manage are left alone) and "
                         f"recreates {counts_text(layout)} from the backup, with "
                         "their original names, order and permissions.\n\n"
                         "• Your current layout is backed up first, so you can undo this.\n"
                         "• Messages can't be restored; the channels come back empty.\n"
                         "• Roles aren't changed. Use `/reset` to remove the roles /setup made."),
            colour=ui.RED)
        restore = discord.ui.Button(label="Restore", style=discord.ButtonStyle.danger, emoji="♻️")
        restore.callback = self.on_restore
        self.clear_items()
        self.add_item(self.select)
        self.add_item(restore)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_restore(self, interaction: discord.Interaction) -> None:
        backup_id = self.chosen
        self.stop()

        async def confirmed(i: discord.Interaction) -> None:
            layout = self.cog.bot.storage.get_backup(i.guild.id, backup_id)
            if layout is None:
                await i.response.send_message("That backup no longer exists.", ephemeral=True)
                return
            await run_layout_job(
                self.cog.bot, i,
                lambda progress: LayoutApplier(i.guild, layout, self.cog.bot.storage, actor=i.user,
                                               mode="restore", wipe=True, reason="Restore backup",
                                               progress=progress),
                "♻️ Restoring backup", f"✅ Backup #{backup_id} restored")

        await interaction.response.send_modal(ui.ConfirmDeleteModal(
            title="Confirm restore", label=f"Type DELETE to replace "
                  f"{deletable_count(interaction.guild, interaction.user)} channels",
            on_confirm=confirmed))


class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="backup", description="Save the current channel layout")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    async def backup(self, interaction: discord.Interaction) -> None:
        layout = snapshot(interaction.guild)
        backup_id = self.bot.storage.add_backup(interaction.guild.id,
                                                f"Saved by {interaction.user.display_name}"[:80],
                                                layout)
        await interaction.response.send_message(
            f"💾 Saved backup **#{backup_id}**: {counts_text(layout)}. Use `/restore` to bring it "
            "back. (The 10 newest backups are kept.)", ephemeral=True)

    @app_commands.command(name="restore", description="Rebuild the channels from a saved backup")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    async def restore(self, interaction: discord.Interaction) -> None:
        backups = self.bot.storage.backups(interaction.guild.id)
        if not backups:
            await interaction.response.send_message(
                "There are no backups yet. One is saved automatically before a fresh start, or "
                "use `/backup`.", ephemeral=True)
            return
        embed = discord.Embed(title="♻️ Restore a backup",
                              description="Pick a backup to see what it contains. Nothing changes "
                                          "until you confirm.", colour=ui.BLURPLE)
        await interaction.response.send_message(
            embed=embed, view=RestoreView(self, interaction.user.id, backups), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backup(bot))
