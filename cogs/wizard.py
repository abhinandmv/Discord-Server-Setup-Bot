"""/setup: an interactive wizard that plans and builds roles, categories and channels.

Flow: server type (buttons) -> features (multi-select) -> details (modal)
      -> follow-ups (ticket role / subjects / self roles, only when relevant)
      -> build mode (fresh start or keep existing channels)
      -> duplicate check (if anything already exists) -> preview -> build.

Every step edits the same ephemeral message. One session exists per
(guild, user); each step's view times out after 10 minutes of inactivity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import partial
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

import templates
from core import ui
from core.builder import Builder, BuildResult
from core.permissions import PRESET_LABELS, missing_bot_permissions
from core.plan import (MAX_EXTRA_CHANNELS, MAX_SELF_ROLES, MAX_SUBJECTS, Plan, WizardAnswers,
                       build_plan, find_conflicts, followups_for, parse_list)

log = logging.getLogger(__name__)

TIMEOUT = 600  # seconds of inactivity before a wizard expires
FOOTER = "Nothing is created until you confirm · times out after 10 minutes of inactivity"


@dataclass
class WizardSession:
    guild_id: int
    user_id: int
    answers: WizardAnswers = field(default_factory=WizardAnswers)
    answered: set[str] = field(default_factory=set)
    create_duplicates: bool | None = None  # None = not asked yet
    wipe: bool | None = None  # fresh start? None = not asked yet
    view: discord.ui.View | None = None
    interaction: discord.Interaction | None = None  # latest, used to show the timeout notice
    last_active: float = field(default_factory=time.monotonic)

    @property
    def key(self) -> tuple[int, int]:
        return (self.guild_id, self.user_id)


def _button(label: str, style: discord.ButtonStyle,
            callback: Callable[[discord.Interaction], Awaitable[None]], *,
            emoji: str | None = None, row: int | None = None) -> discord.ui.Button:
    button = discord.ui.Button(label=label, style=style, emoji=emoji, row=row)
    button.callback = callback
    return button


class WizardView(discord.ui.View):
    """Base view for every wizard step: ownership checks, timeout and a Cancel button."""

    def __init__(self, cog: Wizard, session: WizardSession, *, cancel: bool = True) -> None:
        super().__init__(timeout=TIMEOUT)
        self.cog = cog
        self.session = session
        if cancel:
            self.add_item(_button("Cancel", discord.ButtonStyle.danger,
                                  partial(cog.on_cancel, session=session), row=4))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self.cog.is_current(self.session, self):
            await interaction.response.send_message(
                "This wizard is no longer active. Run `/setup` to start again.", ephemeral=True)
            return False
        self.session.last_active = time.monotonic()
        return True

    async def on_timeout(self) -> None:
        await self.cog.expire(self.session, self)

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        await self.cog.report_error(interaction, error)


class DetailsModal(discord.ui.Modal):
    def __init__(self, cog: Wizard, session: WizardSession) -> None:
        super().__init__(title="Server details", timeout=TIMEOUT)
        self.cog, self.session = cog, session
        a = session.answers
        self.staff = discord.ui.TextInput(label="Staff role name", default=a.staff_role or None,
                                          max_length=100)
        self.member = discord.ui.TextInput(label="Member role name", default=a.member_role or None,
                                           max_length=100)
        self.extra = discord.ui.TextInput(
            label="Extra channels (optional, comma-separated)", style=discord.TextStyle.paragraph,
            required=False, default=", ".join(a.extra_channels) or None,
            placeholder=f"e.g. art, music, book-club (max {MAX_EXTRA_CHANNELS})", max_length=500)
        for item in (self.staff, self.member, self.extra):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.check_active(interaction, self.session):
            return
        staff, member = self.staff.value.strip(), self.member.value.strip()
        if staff.lower() == member.lower():
            await interaction.response.send_message(
                "The staff and member roles need different names. Click **Next** to try again.",
                ephemeral=True)
            return
        a = self.session.answers
        a.staff_role, a.member_role = staff, member
        a.extra_channels = parse_list(self.extra.value)[:MAX_EXTRA_CHANNELS]
        self.session.answered.add("details")
        await self.cog.advance(interaction, self.session)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await self.cog.report_error(interaction, error)


class ListModal(discord.ui.Modal):
    """One paragraph field holding a comma-separated list (subjects, self roles)."""

    def __init__(self, cog: Wizard, session: WizardSession, *, step: str, attr: str,
                 title: str, label: str, placeholder: str, limit: int) -> None:
        super().__init__(title=title, timeout=TIMEOUT)
        self.cog, self.session = cog, session
        self.step, self.attr, self.limit = step, attr, limit
        self.field = discord.ui.TextInput(
            label=label, style=discord.TextStyle.paragraph, placeholder=placeholder,
            default=", ".join(getattr(session.answers, attr)) or None, max_length=1000)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.check_active(interaction, self.session):
            return
        setattr(self.session.answers, self.attr, parse_list(self.field.value)[: self.limit])
        self.session.answered.add(self.step)
        await self.cog.advance(interaction, self.session)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await self.cog.report_error(interaction, error)


class WipeConfirmModal(discord.ui.Modal):
    """Typed confirmation before a fresh start deletes every channel."""

    def __init__(self, cog: Wizard, session: WizardSession, channel_count: int) -> None:
        super().__init__(title="Confirm fresh start", timeout=TIMEOUT)
        self.cog, self.session = cog, session
        self.confirm = discord.ui.TextInput(
            label=f"Type DELETE to remove {channel_count} channel(s)", placeholder="DELETE",
            min_length=1, max_length=10)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await self.cog.check_active(interaction, self.session):
            return
        if self.confirm.value.strip().upper() != "DELETE":
            await interaction.response.send_message(
                "Not confirmed, so nothing was deleted. Press **Confirm & build** to try again.",
                ephemeral=True)
            return
        await self.cog.start_build(interaction, self.session)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await self.cog.report_error(interaction, error)


class Wizard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions: dict[tuple[int, int], WizardSession] = {}
        # Follow-up questions referenced by templates.py ("followups": [...]).
        self.followups: dict[str, Callable[[discord.Interaction, WizardSession], Awaitable[None]]] = {
            "ticket_role": self.step_ticket_role,
            "subjects": self.step_subjects,
            "self_roles": self.step_self_roles,
        }
        assert set(self.followups) == templates.FOLLOWUPS, "templates.FOLLOWUPS out of sync with wizard"

    # ------------------------------------------------------------------ #
    # /setup
    # ------------------------------------------------------------------ #
    @app_commands.command(name="setup", description="Run the server setup wizard")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_command(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None

        missing = missing_bot_permissions(guild.me.guild_permissions)
        if missing:
            await interaction.response.send_message(embed=missing_permissions_embed(missing),
                                                    ephemeral=True)
            return
        if self.bot.guild_lock(guild.id).locked():
            await interaction.response.send_message(
                "A setup or reset is already running in this server. Try again when it finishes.",
                ephemeral=True)
            return

        old = self.sessions.pop((guild.id, interaction.user.id), None)
        if old:
            await self._close_message(old, "This wizard was replaced by a newer `/setup`.")

        session = WizardSession(guild.id, interaction.user.id)
        self.sessions[session.key] = session
        await self.step_type(interaction, session, new=True)

    # ------------------------------------------------------------------ #
    # Session plumbing
    # ------------------------------------------------------------------ #
    def is_current(self, session: WizardSession, view: discord.ui.View | None = None) -> bool:
        if self.sessions.get(session.key) is not session:
            return False
        return view is None or session.view is view

    async def check_active(self, interaction: discord.Interaction, session: WizardSession) -> bool:
        if self.is_current(session):
            session.last_active = time.monotonic()
            return True
        await interaction.response.send_message(
            "This wizard has expired. Run `/setup` to start again.", ephemeral=True)
        return False

    async def render(self, interaction: discord.Interaction, session: WizardSession,
                     embed: discord.Embed, view: discord.ui.View, *, new: bool = False) -> None:
        old, session.view = session.view, view
        if old is not None and old is not view:
            old.stop()
        session.interaction = interaction
        session.last_active = time.monotonic()
        embed.set_footer(text=FOOTER)
        if new:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        elif interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)

    def end(self, session: WizardSession) -> None:
        if self.sessions.get(session.key) is session:
            del self.sessions[session.key]
        if session.view is not None:
            session.view.stop()
            session.view = None

    async def _close_message(self, session: WizardSession, text: str) -> None:
        self.end(session)
        if session.interaction is None:
            return
        try:
            await session.interaction.edit_original_response(
                embed=discord.Embed(description=text, colour=ui.YELLOW), view=None)
        except discord.HTTPException:
            pass  # message deleted or token expired; nothing to update

    async def expire(self, session: WizardSession, view: discord.ui.View) -> None:
        if self.is_current(session, view):
            await self._close_message(
                session, "⏰ **Setup wizard timed out** after 10 minutes of inactivity. "
                         "Nothing was created. Run `/setup` to start again.")

    async def report_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Wizard error", exc_info=error)
        text = "⚠️ Something went wrong in the wizard. Check the bot logs and try `/setup` again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_cancel(self, interaction: discord.Interaction, *, session: WizardSession) -> None:
        self.end(session)
        await interaction.response.edit_message(
            embed=discord.Embed(description="Setup cancelled. Nothing was created.",
                                colour=ui.YELLOW),
            view=None)

    # ------------------------------------------------------------------ #
    # Q1: server type
    # ------------------------------------------------------------------ #
    async def step_type(self, interaction: discord.Interaction, session: WizardSession, *,
                        new: bool = False) -> None:
        embed = discord.Embed(
            title="🧙 Server setup wizard",
            description="**Step 1: What kind of server is this?**\n"
                        "Pick the closest match. You can fine-tune everything in the next steps.",
            colour=ui.BLURPLE)
        for t in templates.SERVER_TYPES.values():
            embed.add_field(name=f"{t.get('emoji', '')} {t['label']}".strip(),
                            value=t["description"], inline=True)

        tracked = len(self.bot.storage.items(session.guild_id))
        if tracked:
            embed.add_field(
                name="ℹ️ Heads up",
                value=f"I've already created {tracked} item(s) here. Running setup again adds to "
                      "them. Use `/reset` first if you want a clean slate.",
                inline=False)

        view = WizardView(self, session)
        for key, t in templates.SERVER_TYPES.items():
            selected = key == session.answers.server_type
            view.add_item(_button(
                t["label"], discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
                partial(self.on_type_chosen, session=session, key=key), emoji=t.get("emoji")))
        await self.render(interaction, session, embed, view, new=new)

    async def on_type_chosen(self, interaction: discord.Interaction, *, session: WizardSession,
                             key: str) -> None:
        a = session.answers
        if a.server_type != key:
            # New type: reset type-specific answers to the template's defaults.
            t = templates.SERVER_TYPES[key]
            a.server_type = key
            a.features = list(t["default_features"])
            a.staff_role, a.member_role = t["staff_role"], t["member_role"]
            a.subjects = parse_list(t.get("default_subjects", ""))
            a.self_roles = parse_list(t.get("default_self_roles", ""))
            a.ticket_role = None
        await self.step_features(interaction, session)

    # ------------------------------------------------------------------ #
    # Q2: features
    # ------------------------------------------------------------------ #
    async def step_features(self, interaction: discord.Interaction, session: WizardSession) -> None:
        a = session.answers
        t = templates.SERVER_TYPES[a.server_type]
        embed = discord.Embed(
            title=f"{t.get('emoji', '')} {t['label']}: features".strip(),
            description="**Step 2: Which features do you want?**\n"
                        "I've pre-selected sensible defaults for this server type. "
                        "Change the selection, then press **Next**.",
            colour=ui.BLURPLE)

        view = WizardView(self, session)
        select = discord.ui.Select(
            placeholder="Choose features…", min_values=0, max_values=len(templates.FEATURES), row=0,
            options=[discord.SelectOption(label=f["label"], value=k, emoji=f.get("emoji"),
                                          description=f["description"][:100],
                                          default=k in a.features)
                     for k, f in templates.FEATURES.items()])

        async def on_select(i: discord.Interaction) -> None:
            a.features = [k for k in templates.FEATURES if k in select.values]
            await i.response.defer()  # just remember the choice; the menu shows it already

        select.callback = on_select
        view.add_item(select)
        view.add_item(_button("Back", discord.ButtonStyle.secondary,
                              partial(self.on_back_to_type, session=session), row=1))
        view.add_item(_button("Next", discord.ButtonStyle.primary,
                              partial(self.on_open_details, session=session), row=1))
        await self.render(interaction, session, embed, view)

    async def on_back_to_type(self, interaction: discord.Interaction, *,
                              session: WizardSession) -> None:
        await self.step_type(interaction, session)

    # ------------------------------------------------------------------ #
    # Q3: details (modal opened straight from the Next button)
    # ------------------------------------------------------------------ #
    async def on_open_details(self, interaction: discord.Interaction, *,
                              session: WizardSession) -> None:
        await interaction.response.send_modal(DetailsModal(self, session))

    # ------------------------------------------------------------------ #
    # Conditional follow-ups
    # ------------------------------------------------------------------ #
    async def advance(self, interaction: discord.Interaction, session: WizardSession) -> None:
        """Show the next unanswered follow-up, then the duplicate check, then the preview."""
        for step in followups_for(session.answers):
            if step not in session.answered:
                await self.followups[step](interaction, session)
                return

        if session.wipe is None:
            await self.step_mode(interaction, session)
            return

        plan = self.make_plan(interaction.guild, session)
        if plan.conflicts() and session.create_duplicates is None:
            await self.step_duplicates(interaction, session, plan)
        else:
            await self.step_preview(interaction, session, plan)

    async def step_ticket_role(self, interaction: discord.Interaction, session: WizardSession) -> None:
        a = session.answers
        plan = build_plan(a)
        current = a.ticket_role or "plan:staff"

        options: list[discord.SelectOption] = []
        for r in plan.roles:
            if r.key != "muted" and not r.self_assign:
                value = f"plan:{r.key}"
                options.append(discord.SelectOption(
                    label=f"@{r.name}"[:100], value=value, description="Part of this setup",
                    default=current == value))
        planned_names = {r.name.lower() for r in plan.roles}
        for role in sorted(interaction.guild.roles, reverse=True):
            if len(options) >= 25:
                break
            if role.is_default() or role.managed or role.name.lower() in planned_names:
                continue
            value = f"id:{role.id}"
            options.append(discord.SelectOption(label=f"@{role.name}"[:100], value=value,
                                                description="Existing role",
                                                default=current == value))

        embed = discord.Embed(
            title="🎫 Support tickets",
            description="**Which role should be able to see support tickets?**\n"
                        "Each ticket is a private channel visible only to this role and the "
                        "member who opened it.",
            colour=ui.BLURPLE)
        view = WizardView(self, session)
        select = discord.ui.Select(placeholder="Choose the ticket role…", options=options, row=0)

        async def on_select(i: discord.Interaction) -> None:
            a.ticket_role = select.values[0]
            session.answered.add("ticket_role")
            await self.advance(i, session)

        select.callback = on_select
        view.add_item(select)
        await self.render(interaction, session, embed, view)

    async def step_subjects(self, interaction: discord.Interaction, session: WizardSession) -> None:
        embed = discord.Embed(
            title="📚 Study subjects",
            description=f"**Which subjects does your group study?**\n"
                        f"I'll create a text channel for each one (up to {MAX_SUBJECTS}) in a "
                        f"**{templates.CATEGORIES[templates.SUBJECT_CATEGORY]['name']}** category.",
            colour=ui.BLURPLE)
        modal = partial(ListModal, self, session, step="subjects", attr="subjects",
                        title="Study subjects", label="Subjects (comma-separated)",
                        placeholder="Math, Physics, History", limit=MAX_SUBJECTS)
        await self._render_list_step(interaction, session, embed, modal, "Enter subjects",
                                     attr="subjects", step="subjects")

    async def step_self_roles(self, interaction: discord.Interaction, session: WizardSession) -> None:
        embed = discord.Embed(
            title="🏷️ Self-assign roles",
            description=f"**Which roles can members give themselves?**\n"
                        f"I'll create them (up to {MAX_SELF_ROLES}) and post a button menu in "
                        f"**#roles**. Clicking a button toggles that role.",
            colour=ui.BLURPLE)
        modal = partial(ListModal, self, session, step="self_roles", attr="self_roles",
                        title="Self-assign roles", label="Role names (comma-separated)",
                        placeholder="PC, Console, Event Pings", limit=MAX_SELF_ROLES)
        await self._render_list_step(interaction, session, embed, modal, "Enter role names",
                                     attr="self_roles", step="self_roles")

    async def _render_list_step(self, interaction: discord.Interaction, session: WizardSession,
                                embed: discord.Embed, modal_factory: Callable[[], discord.ui.Modal],
                                label: str, *, attr: str, step: str) -> None:
        current = getattr(session.answers, attr)
        if current:
            embed.add_field(name="Current", value=ui.clip(", ".join(current)), inline=False)
        view = WizardView(self, session)

        async def open_modal(i: discord.Interaction) -> None:
            await i.response.send_modal(modal_factory())

        async def skip(i: discord.Interaction) -> None:
            setattr(session.answers, attr, [])
            session.answered.add(step)
            await self.advance(i, session)

        view.add_item(_button(label, discord.ButtonStyle.primary, open_modal, emoji="✏️"))
        view.add_item(_button("Skip", discord.ButtonStyle.secondary, skip))
        await self.render(interaction, session, embed, view)

    # ------------------------------------------------------------------ #
    # Duplicates
    # ------------------------------------------------------------------ #
    def make_plan(self, guild: discord.Guild, session: WizardSession) -> Plan:
        plan = build_plan(session.answers)
        plan.create_duplicates = bool(session.create_duplicates)
        plan.wipe = bool(session.wipe)
        # A fresh start deletes the bot's old roles first, so they can't conflict.
        ignore = ({i.item_id for i in self.bot.storage.items(guild.id) if i.kind == "role"}
                  if plan.wipe else set())
        find_conflicts(guild, plan, ignore_ids=ignore)
        return plan

    async def step_mode(self, interaction: discord.Interaction, session: WizardSession) -> None:
        guild = interaction.guild
        tracked_roles = sum(1 for i in self.bot.storage.items(guild.id) if i.kind == "role")
        embed = discord.Embed(
            title="🏗️ How should I build?",
            description=(
                f"Your server currently has **{len(guild.channels)}** channels and categories.\n\n"
                "🧹 **Fresh start**: delete **every** existing channel and category "
                + (f"(plus the {tracked_roles} role(s) I made in earlier setups) " if tracked_roles else "")
                + "and build everything new. Other roles are kept. "
                "**Deleted channels and their messages can't be recovered.**\n\n"
                "➕ **Keep existing**: leave current channels alone and add the new ones."),
            colour=ui.BLURPLE)
        view = WizardView(self, session)

        async def choose(i: discord.Interaction, wipe: bool) -> None:
            session.wipe = wipe
            await self.advance(i, session)

        view.add_item(_button("Fresh start", discord.ButtonStyle.danger,
                              partial(choose, wipe=True), emoji="🧹"))
        view.add_item(_button("Keep existing", discord.ButtonStyle.primary,
                              partial(choose, wipe=False), emoji="➕"))
        await self.render(interaction, session, embed, view)

    async def step_duplicates(self, interaction: discord.Interaction, session: WizardSession,
                              plan: Plan) -> None:
        conflicts = plan.conflicts()
        embed = discord.Embed(
            title="⚠️ Some of these already exist",
            description=f"**{len(conflicts)}** item(s) in this setup have the same name as "
                        "something already in your server.\n\n"
                        "**Skip existing**: leave them alone and reuse them (e.g. new channels "
                        "go into an existing category of the same name).\n"
                        "**Create anyway**: make new ones with the same names.",
            colour=ui.YELLOW)
        embed.add_field(name="Already exists", value=ui.bullet_list([f"• {c}" for c in conflicts]),
                        inline=False)

        view = WizardView(self, session)

        async def choose(i: discord.Interaction, create: bool) -> None:
            session.create_duplicates = create
            await self.advance(i, session)

        view.add_item(_button("Skip existing", discord.ButtonStyle.primary,
                              partial(choose, create=False), emoji="♻️"))
        view.add_item(_button("Create anyway", discord.ButtonStyle.secondary,
                              partial(choose, create=True), emoji="➕"))
        await self.render(interaction, session, embed, view)

    # ------------------------------------------------------------------ #
    # Preview
    # ------------------------------------------------------------------ #
    async def step_preview(self, interaction: discord.Interaction, session: WizardSession,
                           plan: Plan) -> None:
        embed = self.preview_embed(interaction.guild, session, plan)
        view = WizardView(self, session)
        view.add_item(_button("Confirm & build", discord.ButtonStyle.success,
                              partial(self.on_confirm, session=session), emoji="✅"))
        view.add_item(_button("Edit (restart)", discord.ButtonStyle.secondary,
                              partial(self.on_restart, session=session), emoji="✏️"))
        await self.render(interaction, session, embed, view)

    def preview_embed(self, guild: discord.Guild, session: WizardSession, plan: Plan) -> discord.Embed:
        a = session.answers
        t = templates.SERVER_TYPES[a.server_type]

        def mark(spec) -> str:
            if spec.existing_id is None:
                return "➕"
            return "♻️" if plan.reuses(spec) else "➕⚠️"

        features = ", ".join(templates.FEATURES[f]["label"] for f in plan.features) or "none"
        new_roles, new_cats, new_chans = plan.new_counts()
        embed = discord.Embed(
            title="📋 Review your setup",
            description=(f"**Type:** {t.get('emoji', '')} {t['label']}\n"
                         f"**Features:** {features}\n"
                         f"**Will create:** {new_roles} roles · {new_cats} categories · "
                         f"{new_chans} channels\n\n"
                         "➕ new · ♻️ already exists, will be reused · ➕⚠️ duplicate name"),
            colour=ui.RED if plan.wipe else ui.BLURPLE)
        if plan.wipe:
            embed.description = (f"🧹 **FRESH START: all {len(guild.channels)} existing channels "
                                 "and categories will be deleted first.** You'll be asked to type "
                                 "DELETE to confirm.\n\n" + embed.description)

        role_lines = []
        for r in plan.roles:
            note = {"staff": "staff", "member": "members", "muted": "can't send or speak anywhere"
                    }.get(r.key, "self-assign" if r.self_assign else "")
            role_lines.append(f"{mark(r)} @{r.name}" + (f" · {note}" if note else ""))
        embed.add_field(name=f"Roles ({len(plan.roles)})", value=ui.bullet_list(role_lines),
                        inline=False)

        for cat in plan.categories:
            label = PRESET_LABELS.get(cat.preset)
            lines = []
            for ch in cat.channels:
                ch_label = PRESET_LABELS.get(ch.preset) if ch.preset and ch.preset != cat.preset else ""
                lines.append(f"{mark(ch)} {ch.display}" + (f" · {ch_label}" if ch_label else ""))
            if not lines:
                lines = ["*(empty; ticket channels will appear here)*"]
            embed.add_field(name=ui.clip(f"{mark(cat)} 📁 {cat.name}" + (f" ({label})" if label else ""), 256),
                            value=ui.bullet_list(lines), inline=False)

        notes = []
        if plan.ticket_role:
            notes.append(f"🎫 Tickets visible to **@{self._ticket_role_name(guild, plan)}** + the "
                         f"member who opened them; only mods can close them. The "
                         f"**{plan.ticket_category_name}** category only appears while a ticket "
                         "is open.")
        muted = plan.role("muted")
        if muted and not plan.reuses(muted) and not plan.wipe:
            notes.append(f"🔇 **@{muted.name}** will also be applied to your "
                         f"{len(guild.channels)} existing channel(s).")
        if any(r.self_assign for r in plan.roles):
            notes.append("🏷️ A self-assign menu (buttons + emoji reactions) will be posted.")
        if notes:
            embed.add_field(name="Also", value=ui.clip("\n".join(notes)), inline=False)
        return ui.fit_embed(embed)

    @staticmethod
    def _ticket_role_name(guild: discord.Guild, plan: Plan) -> str:
        value = plan.ticket_role or ""
        if value.startswith("plan:") and (spec := plan.role(value[5:])):
            return spec.name
        if value.startswith("id:") and (role := guild.get_role(int(value[3:]))):
            return role.name
        staff = plan.role("staff")
        return staff.name if staff else "staff"

    async def on_restart(self, interaction: discord.Interaction, *, session: WizardSession) -> None:
        # Keep previous answers as defaults, but ask every question again.
        session.answered.clear()
        session.create_duplicates = None
        session.wipe = None
        await self.step_type(interaction, session)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #
    async def on_confirm(self, interaction: discord.Interaction, *, session: WizardSession) -> None:
        if session.wipe:
            await interaction.response.send_modal(
                WipeConfirmModal(self, session, len(interaction.guild.channels)))
        else:
            await self.start_build(interaction, session)

    async def start_build(self, interaction: discord.Interaction, session: WizardSession) -> None:
        guild = interaction.guild
        lock = self.bot.guild_lock(guild.id)
        if lock.locked():
            await interaction.response.send_message(
                "A setup or reset is already running in this server. Try again when it finishes.",
                ephemeral=True)
            return

        async with lock:
            self.end(session)
            missing = missing_bot_permissions(guild.me.guild_permissions)
            if missing:  # permissions may have changed while the wizard was open
                await interaction.response.edit_message(embed=missing_permissions_embed(missing),
                                                        view=None)
                return

            plan = self.make_plan(guild, session)  # re-check duplicates against the live server
            title = "🔨 Building your server"
            await interaction.response.edit_message(
                embed=ui.progress_embed(title, "Starting", 0, 1, 0, 1), view=None)
            reporter = ui.ProgressReporter(interaction, title)
            try:
                result = await Builder(guild, plan, self.bot.storage, progress=reporter).run()
            except Exception:
                log.exception("Build crashed in guild %s", guild.id)
                await reporter.finish(discord.Embed(
                    title="❌ Setup stopped unexpectedly",
                    description="Something went wrong part-way through. Everything created so far "
                                "is tracked, so `/reset` can remove it. Check the bot logs.",
                    colour=ui.RED))
                return
            embed = result_embed(result)
            # After a fresh start the wizard's channel is gone, so post the summary
            # in the new staff channel (or the first new channel) instead.
            if not await reporter.finish(embed) and result.home_channel:
                try:
                    await result.home_channel.send(content=interaction.user.mention, embed=embed,
                                                   allowed_mentions=discord.AllowedMentions(users=True))
                except discord.HTTPException as exc:
                    log.warning("Couldn't post setup summary: %s", exc)


def result_embed(result: BuildResult) -> discord.Embed:
    c = result.created
    ok = not result.errors
    embed = discord.Embed(
        title="✅ Server setup complete" if ok else "⚠️ Setup finished with problems",
        description=(("🧹 Fresh start: deleted **{}** old channels and **{}** old bot roles.\n"
                      .format(result.deleted["channel"], result.deleted["role"])
                      if result.deleted else "")
                     + f"Created **{c['role']}** roles, **{c['category']}** categories and "
                       f"**{c['channel']}** channels."),
        colour=ui.GREEN if ok else ui.YELLOW)
    if result.reused:
        embed.add_field(name=f"♻️ Reused existing ({len(result.reused)})",
                        value=ui.bullet_list(result.reused), inline=False)
    if result.warnings:
        embed.add_field(name="⚠️ Warnings", value=ui.bullet_list([f"• {w}" for w in result.warnings]),
                        inline=False)
    if result.errors:
        embed.add_field(name="❌ Errors", value=ui.bullet_list([f"• {e}" for e in result.errors]),
                        inline=False)
    embed.set_footer(text="Run /reset to remove everything this bot created.")
    return ui.fit_embed(embed)


def missing_permissions_embed(missing: list[str]) -> discord.Embed:
    return discord.Embed(
        title="🔒 I'm missing some permissions",
        description=(
            "To build channels and roles I need these server permissions:\n"
            + "\n".join(f"• **{p}**" for p in missing)
            + "\n\n**How to fix:** Server Settings → Roles → select my role → enable the "
              "permissions above (or re-invite me with the URL from the README).\n"
              "Also drag my role **above** any role I should manage."),
        colour=ui.RED)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Wizard(bot))
