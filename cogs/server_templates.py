"""/template: save a server's layout as a reusable template and apply it elsewhere.

Anyone can save a template of a server they're in (only the channels they can
see are included). Templates belong to the person who saved them, not to a
server, so you can save one in server A and apply it in your own server B.
Applying deletes/creates channels, so it only works in a server you own.
/template export and import turn a template into a .json file to share.
"""

from __future__ import annotations

import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import ui
from core.layout import LayoutApplier, as_template, layout_counts, snapshot, validate_layout
from cogs.backup import run_layout_job
from core.permissions import owner_only
from core.wipe import deletable_count

log = logging.getLogger(__name__)

MAX_TEMPLATES_PER_USER = 25
MAX_IMPORT_BYTES = 256 * 1024


def describe(layout: dict) -> str:
    roles, cats, chans = layout_counts(layout)
    return f"{roles} roles · {cats} categories · {chans} channels"


class ApplyView(discord.ui.View):
    def __init__(self, cog: Templates, owner_id: int, name: str, layout: dict) -> None:
        super().__init__(timeout=600)
        self.cog, self.owner_id, self.name, self.layout = cog, owner_id, name, layout

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    def _job(self, interaction: discord.Interaction, wipe: bool):
        return run_layout_job(
            self.cog.bot, interaction,
            lambda progress: LayoutApplier(interaction.guild, self.layout, self.cog.bot.storage,
                                           actor=interaction.user, mode="template", wipe=wipe,
                                           reason=f"Template {self.name}", progress=progress),
            f"📐 Applying template {self.name}", f"✅ Template {self.name} applied")

    @discord.ui.button(label="Keep existing", style=discord.ButtonStyle.primary, emoji="➕")
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await self._job(interaction, wipe=False)

    @discord.ui.button(label="Fresh start", style=discord.ButtonStyle.danger, emoji="🧹")
    async def fresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.send_modal(ui.ConfirmDeleteModal(
            title="Confirm fresh start",
            label=f"Type DELETE to remove "
                  f"{deletable_count(interaction.guild, interaction.user)} channels",
            on_confirm=lambda i: self._job(i, wipe=True)))


class Templates(commands.Cog):
    # Anyone can save a layout and keep it in their own list; applying it is
    # only possible in a server you own (see apply).
    template = app_commands.Group(
        name="template", description="Save and reuse server layouts", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def name_autocomplete(self, interaction: discord.Interaction,
                                current: str) -> list[app_commands.Choice[str]]:
        names = self.bot.storage.template_names(interaction.user.id)
        return [app_commands.Choice(name=n, value=n) for n in names
                if current.lower() in n.lower()][:25]

    def _get(self, user_id: int, name: str) -> dict | None:
        return self.bot.storage.get_template(user_id, name)

    def _room_for(self, user_id: int, name: str) -> bool:
        names = self.bot.storage.template_names(user_id)
        return name in names or len(names) < MAX_TEMPLATES_PER_USER

    @template.command(name="save", description="Save this server's roles and channels as a template")
    @app_commands.describe(name="A name for the template (saving again with the same name overwrites)")
    async def save(self, interaction: discord.Interaction,
                   name: app_commands.Range[str, 1, 50]) -> None:
        name = name.strip()
        if not self._room_for(interaction.user.id, name):
            await interaction.response.send_message(
                f"You already have {MAX_TEMPLATES_PER_USER} templates. Delete one first.",
                ephemeral=True)
            return
        layout = as_template(snapshot(interaction.guild, viewer=interaction.user))
        self.bot.storage.save_template(interaction.user.id, name, layout)
        await interaction.response.send_message(
            f"📐 Saved template **{name}** ({describe(layout)}).\n"
            "Apply it in any server with `/template apply`, or share it with `/template export`.",
            ephemeral=True)

    @template.command(name="list", description="Show your saved templates")
    async def list_(self, interaction: discord.Interaction) -> None:
        storage = self.bot.storage
        names = storage.template_names(interaction.user.id)
        lines = [f"📐 **{n}** · {describe(storage.get_template(interaction.user.id, n))}"
                 for n in names]
        await interaction.response.send_message(
            embed=discord.Embed(title="Your templates",
                                description=ui.bullet_list(lines, 4000) if lines else
                                "You have no templates yet. Use `/template save`.",
                                colour=ui.BLURPLE),
            ephemeral=True)

    @template.command(name="apply", description="Build one of your templates in a server you own")
    @owner_only()
    @app_commands.autocomplete(name=name_autocomplete)
    async def apply(self, interaction: discord.Interaction, name: str) -> None:
        layout = self._get(interaction.user.id, name)
        if layout is None:
            await interaction.response.send_message("You don't have a template with that name.",
                                                    ephemeral=True)
            return
        embed = discord.Embed(
            title=f"📐 Apply template {name}?",
            description=(f"It contains **{describe(layout)}**.\n\n"
                         "➕ **Keep existing**: add what's missing. Roles, categories and channels "
                         "with the same name are reused.\n"
                         f"🧹 **Fresh start**: delete the "
                         f"{deletable_count(interaction.guild, interaction.user)} current channels "
                         "you can manage first (a backup is saved, so `/restore` can undo it).\n\n"
                         "New roles only get permissions you have yourself. Everything created is "
                         "tracked, so `/reset` can remove it."),
            colour=ui.BLURPLE)
        await interaction.response.send_message(
            embed=embed, view=ApplyView(self, interaction.user.id, name, layout), ephemeral=True)

    @template.command(name="delete", description="Delete one of your templates")
    @app_commands.autocomplete(name=name_autocomplete)
    async def delete(self, interaction: discord.Interaction, name: str) -> None:
        deleted = self.bot.storage.delete_template(interaction.user.id, name)
        await interaction.response.send_message(
            f"🗑️ Deleted template **{name}**." if deleted else "You don't have a template with that name.",
            ephemeral=True)

    @template.command(name="export", description="Download a template as a file you can share")
    @app_commands.autocomplete(name=name_autocomplete)
    async def export(self, interaction: discord.Interaction, name: str) -> None:
        layout = self._get(interaction.user.id, name)
        if layout is None:
            await interaction.response.send_message("You don't have a template with that name.",
                                                    ephemeral=True)
            return
        data = json.dumps(layout, ensure_ascii=False, indent=1).encode()
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "template"
        await interaction.response.send_message(
            f"📐 **{name}**: anyone can bring this into their own list with `/template import`.",
            file=discord.File(io.BytesIO(data), filename=f"{safe}.json"), ephemeral=True)

    @template.command(name="import", description="Add a template from a .json file")
    @app_commands.describe(file="A file made with /template export", name="Name to save it as")
    async def import_(self, interaction: discord.Interaction, file: discord.Attachment,
                      name: app_commands.Range[str, 1, 50]) -> None:
        name = name.strip()
        if file.size > MAX_IMPORT_BYTES:
            await interaction.response.send_message("That file is too big to be a template.",
                                                    ephemeral=True)
            return
        if not self._room_for(interaction.user.id, name):
            await interaction.response.send_message(
                f"You already have {MAX_TEMPLATES_PER_USER} templates. Delete one first.",
                ephemeral=True)
            return
        try:
            layout = validate_layout(json.loads(await file.read()))
        except (ValueError, RecursionError, discord.HTTPException) as exc:
            await interaction.response.send_message(f"That file isn't a valid template: {exc}"[:1900],
                                                    ephemeral=True)
            return
        self.bot.storage.save_template(interaction.user.id, name, layout)
        await interaction.response.send_message(
            f"📐 Imported **{name}** ({describe(layout)}). Use `/template apply` to build it.",
            ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Templates(bot))
