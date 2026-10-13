"""/reset: delete only what this bot created (as recorded in storage), after confirmation."""

from __future__ import annotations

import logging
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.permissions import can_hand_out, owner_only
from core.retry import call_with_retry, describe_error
from core.storage import TrackedItem

log = logging.getLogger(__name__)

# Delete messages first, then channels, then categories (so they're empty), then roles.
DELETE_ORDER = {"message": 0, "automod": 0, "channel": 1, "category": 2, "role": 3}
KIND_LABELS = {"role": "roles", "category": "categories", "channel": "channels",
               "message": "bot messages", "automod": "AutoMod rules"}


class ResetConfirmView(discord.ui.View):
    def __init__(self, cog: Reset, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="Yes, delete everything", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self.cog.run_reset(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(description="Reset cancelled. Nothing was deleted.",
                                colour=ui.YELLOW),
            view=None)

    async def on_timeout(self) -> None:
        if self.interaction:
            try:
                await self.interaction.edit_original_response(
                    embed=discord.Embed(description="Reset timed out. Nothing was deleted.",
                                        colour=ui.YELLOW),
                    view=None)
            except discord.HTTPException:
                pass


class Reset(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _resolve(self, guild: discord.Guild, item: TrackedItem):
        if item.kind == "role":
            return guild.get_role(item.item_id)
        if item.kind in ("channel", "category"):
            return guild.get_channel(item.item_id)
        return item  # messages and AutoMod rules aren't cached; assume present

    @app_commands.command(name="reset", description="Delete everything the setup wizard created")
    @app_commands.guild_only()
    # Deletes everything the bot built: owner only.
    @app_commands.default_permissions(administrator=True)
    @owner_only()
    async def reset(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        storage = self.bot.storage

        # Forget items that were already deleted by hand.
        items = []
        for item in storage.items(guild.id):
            if self._resolve(guild, item) is None:
                storage.untrack(guild.id, item.item_id)
            else:
                items.append(item)
        if not items:
            storage.clear_settings(guild.id)
            await interaction.response.send_message(
                "There's nothing to reset: I haven't created anything here (or it was already "
                "deleted).", ephemeral=True)
            return

        counts = Counter(i.kind for i in items)
        summary = ", ".join(f"**{counts[k]}** {KIND_LABELS[k]}" for k in DELETE_ORDER if counts[k])
        prefix = {"role": "@", "category": "📁 ", "automod": "AutoMod: "}
        names = [f"{prefix.get(i.kind, '#')}{i.name}" for i in items if i.kind != "message"]
        embed = discord.Embed(
            title="🗑️ Reset server setup?",
            description=f"This permanently deletes {summary} that **this bot created**.\n"
                        "Anything made by people, or existing items the wizard reused, is not "
                        "touched.\n\n**Messages inside deleted channels are lost forever.**",
            colour=ui.RED)
        embed.add_field(name="Will be deleted", value=ui.bullet_list(names), inline=False)

        view = ResetConfirmView(self, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.interaction = interaction

    async def run_reset(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        storage = self.bot.storage
        lock = self.bot.guild_lock(guild.id)
        if lock.locked():
            await interaction.response.edit_message(
                embed=discord.Embed(description="A setup or reset is already running here. "
                                                "Try again when it finishes.", colour=ui.YELLOW),
                view=None)
            return

        async with lock:
            items = sorted(storage.items(guild.id), key=lambda i: DELETE_ORDER.get(i.kind, 9))
            channel_ids = {i.item_id for i in items if i.kind in ("channel", "category")}
            title = "🗑️ Resetting"
            await interaction.response.edit_message(
                embed=ui.progress_embed(title, "Deleting", 0, len(items), 0, len(items)), view=None)
            reporter = ui.ProgressReporter(interaction, title)

            deleted, errors = 0, []
            for n, item in enumerate(items, 1):
                role = guild.get_role(item.item_id) if item.kind == "role" else None
                if role is not None and not can_hand_out(interaction.user, role):
                    # Someone moved it above the invoker; they couldn't delete it themselves.
                    errors.append(f"@{role.name}: it's above your highest role, so I left it. "
                                  "Someone higher up can run /reset to remove it.")
                    await reporter("Deleting", n, len(items), n, len(items))
                    continue
                try:
                    if await self._delete(guild, item, channel_ids):
                        deleted += 1
                    storage.untrack(guild.id, item.item_id)
                except discord.NotFound:
                    storage.untrack(guild.id, item.item_id)
                except discord.HTTPException as exc:
                    errors.append(f"{item.kind} {item.name or item.item_id}: {describe_error(exc)}")
                await reporter("Deleting", n, len(items), n, len(items))

            if not storage.items(guild.id):
                storage.clear_settings(guild.id)

            embed = discord.Embed(
                title="✅ Reset complete" if not errors else "⚠️ Reset finished with problems",
                description=f"Deleted {deleted} item(s)."
                            + ("" if not errors else
                               "\nItems I couldn't delete are still tracked; fix the problem "
                               "and run `/reset` again."),
                colour=ui.GREEN if not errors else ui.YELLOW)
            if errors:
                embed.add_field(name="Errors", value=ui.bullet_list([f"• {e}" for e in errors]),
                                inline=False)
            await reporter.finish(embed)

    async def _delete(self, guild: discord.Guild, item: TrackedItem, channel_ids: set[int]) -> bool:
        """Delete one tracked item. Returns False if it was already gone."""
        reason = "Server setup /reset"
        if item.kind == "automod":
            rule = await guild.fetch_automod_rule(item.item_id)  # NotFound -> untracked by caller
            await call_with_retry(lambda: rule.delete(reason=reason), delay=0.4)
            return True
        if item.kind == "message":
            channel = guild.get_channel(item.parent_id)
            if item.parent_id in channel_ids or channel is None:
                return False  # deleted along with its channel
            await call_with_retry(lambda: channel.get_partial_message(item.item_id).delete(),
                                  delay=0.4)
            return True
        target = guild.get_role(item.item_id) if item.kind == "role" else guild.get_channel(item.item_id)
        if target is None:
            return False
        await call_with_retry(lambda: target.delete(reason=reason), delay=0.4)
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reset(bot))
