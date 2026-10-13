"""Moderation: /mute, /unmute, /warn, /warnings, /clearwarnings, /purge, /lockdown, /unlock.

Muting uses the Muted role /setup created (it can't type, react or speak
anywhere). Timed mutes are stored in the database, so they still end on time
after a restart, and leaving and rejoining doesn't shake a mute off.
Warnings escalate: templates.WARN_ESCALATION auto-mutes at set warning counts.
Every action is posted to the mod-log channel.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import ui
from core.modlog import log_event
import templates
from core.permissions import (MOD_COMMAND_PERMISSIONS, is_access_role, is_safe_self_assign_role,
                              mod_command)

log = logging.getLogger(__name__)

# The staff role must be able to use every moderation command.
assert set(MOD_COMMAND_PERMISSIONS.values()) <= set(templates.DEFAULT_ROLES["staff"]["permissions"]), \
    "templates.DEFAULT_ROLES['staff'] is missing a moderation permission"

_DURATION = re.compile(r"^\s*(\d+)\s*(s|sec|m|min|h|hr|hour|d|day|w|week)s?\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600, "hour": 3600,
                 "d": 86400, "day": 86400, "w": 604800, "week": 604800}
MAX_MUTE_SECONDS = 28 * 86400


def parse_duration(text: str) -> int | None:
    """'10m' -> 600, '2 hours' -> 7200; None if it can't be parsed."""
    match = _DURATION.match(text or "")
    if not match:
        return None
    return int(match[1]) * _UNIT_SECONDS[match[2].lower()]


def human_duration(seconds: int) -> str:
    for unit, size in (("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size and seconds % size == 0:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{seconds} seconds"


def target_problem(actor: discord.Member, target: discord.Member) -> str | None:
    """Why ``actor`` may not moderate ``target``, or None if they may."""
    guild = actor.guild
    if target.id == actor.id:
        return "You can't do that to yourself."
    if target.bot:
        return "That's a bot."
    if target.id == guild.owner_id:
        return "You can't moderate the server owner."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "They have a role equal to or higher than yours."
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.expire_mutes.start()

    async def cog_unload(self) -> None:
        self.expire_mutes.cancel()

    def _muted_role(self, guild: discord.Guild) -> tuple[discord.Role | None, str | None]:
        raw = self.bot.storage.get_setting(guild.id, "muted_role_id")
        role = guild.get_role(int(raw)) if raw and raw.isdigit() else None
        if role is None:
            return None, "There's no Muted role yet. Run `/setup` first."
        # Moderators hand this role out through the bot, so it must stay harmless.
        if not is_safe_self_assign_role(role) or is_access_role(role):
            return None, (f"{role.mention} has been given extra permissions or channel access, so "
                          "I won't hand it out. Remove those and try again.")
        if role >= guild.me.top_role:
            return None, f"Move my role above {role.mention} so I can assign it."
        return role, None

    # ------------------------------------------------------------------ #
    @app_commands.command(name="mute", description="Stop a member from typing, reacting and speaking")
    @app_commands.guild_only()
    @mod_command("mute")
    @app_commands.describe(member="Who to mute", duration="e.g. 10m, 2h, 1d (empty = until /unmute)",
                           reason="Shown in the mod log")
    async def mute(self, interaction: discord.Interaction, member: discord.Member,
                   duration: str | None = None, reason: str | None = None) -> None:
        guild = interaction.guild
        problem = target_problem(interaction.user, member)
        role, role_problem = self._muted_role(guild)
        seconds = parse_duration(duration) if duration else None
        if duration and (seconds is None or not 0 < seconds <= MAX_MUTE_SECONDS):
            problem = problem or "Use a duration like `10m`, `2h` or `3d` (up to 28 days)."
        if problem or role_problem:
            await interaction.response.send_message(problem or role_problem, ephemeral=True)
            return

        error = await self.apply_mute(member, role, seconds,
                                      f"by {interaction.user}: {reason or 'no reason'}")
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        length = f" for {human_duration(seconds)}" if seconds else ""
        note = ("\n-# They have Administrator, so channel permissions don't apply to them."
                if member.guild_permissions.administrator else "")
        await interaction.response.send_message(f"🔇 Muted {member.mention}{length}.{note}",
                                                allowed_mentions=discord.AllowedMentions.none())
        await log_event(self.bot, guild, "🔇 Member muted",
                        f"{member.mention} ({member}){length}\nBy {interaction.user.mention}\n"
                        f"Reason: {reason or '—'}", colour=ui.YELLOW)

    async def apply_mute(self, member: discord.Member, role: discord.Role, seconds: int | None,
                         reason: str) -> str | None:
        """Give the Muted role and remember it. Returns an error message, or None."""
        try:
            await member.add_roles(role, reason=f"Muted {reason}"[:500])
        except discord.HTTPException as exc:
            return f"Couldn't mute them: {exc.text or exc}"
        # Indefinite mutes are stored too (never due), so rejoining can't escape them.
        self.bot.storage.set_mute(member.guild.id, member.id,
                                  time.time() + seconds if seconds else math.inf)
        return None

    @app_commands.command(name="unmute", description="Remove a member's mute")
    @app_commands.guild_only()
    @mod_command("unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild = interaction.guild
        problem = target_problem(interaction.user, member)
        role, role_problem = self._muted_role(guild)
        if problem or role_problem:
            await interaction.response.send_message(problem or role_problem, ephemeral=True)
            return
        self.bot.storage.clear_mute(guild.id, member.id)
        if role not in member.roles:
            await interaction.response.send_message("They aren't muted.", ephemeral=True)
            return
        try:
            await member.remove_roles(role, reason=f"Unmuted by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Couldn't unmute them: {exc.text or exc}",
                                                    ephemeral=True)
            return
        await interaction.response.send_message(f"🔊 Unmuted {member.mention}.",
                                                allowed_mentions=discord.AllowedMentions.none())
        await log_event(self.bot, guild, "🔊 Member unmuted",
                        f"{member.mention} ({member})\nBy {interaction.user.mention}",
                        colour=ui.GREEN)

    @tasks.loop(seconds=30)
    async def expire_mutes(self) -> None:
        storage = self.bot.storage
        for guild_id, user_id in storage.due_mutes(time.time()):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue  # bot not in that server (anymore); try again later
            storage.clear_mute(guild_id, user_id)
            member = guild.get_member(user_id)
            role, _ = self._muted_role(guild)
            if member is None or role is None or role not in member.roles:
                continue
            try:
                await member.remove_roles(role, reason="Timed mute ended")
            except discord.HTTPException as exc:
                log.warning("Couldn't end mute in %s: %s", guild_id, exc)
                continue
            await log_event(self.bot, guild, "🔊 Mute expired", f"{member.mention} ({member})",
                            colour=ui.GREEN)

    @expire_mutes.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Leaving and rejoining doesn't remove an active mute."""
        if not self.bot.storage.is_muted(member.guild.id, member.id, time.time()):
            return
        role, _ = self._muted_role(member.guild)
        if role is not None:
            try:
                await member.add_roles(role, reason="Rejoined while muted")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------ #
    @app_commands.command(name="warn", description="Give a member a formal warning")
    @app_commands.guild_only()
    @mod_command("warn")
    async def warn(self, interaction: discord.Interaction, member: discord.Member,
                   reason: app_commands.Range[str, 1, 500]) -> None:
        guild = interaction.guild
        problem = target_problem(interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        storage = self.bot.storage
        storage.add_warning(guild.id, member.id, interaction.user.id, reason)
        count = len(storage.warnings(guild.id, member.id))
        try:
            await member.send(embed=discord.Embed(
                title=f"⚠️ You were warned in {guild.name}", description=f"Reason: {reason}",
                colour=ui.YELLOW))
            dm = ""
        except discord.HTTPException:
            dm = " (I couldn't DM them)"
        escalation = await self._escalate(member, count)
        await interaction.response.send_message(
            f"⚠️ Warned {member.mention}. They now have **{count}** warning(s).{dm}"
            + (f"\n{escalation}" if escalation else ""),
            allowed_mentions=discord.AllowedMentions.none())
        await log_event(self.bot, guild, "⚠️ Member warned",
                        f"{member.mention} ({member}) · warning #{count}\n"
                        f"By {interaction.user.mention}\nReason: {reason}"
                        + (f"\n{escalation}" if escalation else ""), colour=ui.YELLOW)

    async def _escalate(self, member: discord.Member, count: int) -> str | None:
        """Auto-mute when the warning count hits a threshold in templates.WARN_ESCALATION."""
        seconds = dict(templates.WARN_ESCALATION).get(count)
        if not seconds:
            return None
        role, problem = self._muted_role(member.guild)
        if problem:
            return f"⚠️ Auto-mute skipped: {problem}"
        error = await self.apply_mute(member, role, seconds, f"automatically ({count} warnings)")
        if error:
            return f"⚠️ Auto-mute failed: {error}"
        return f"🔇 That's {count} warnings, so they're automatically muted for {human_duration(seconds)}."

    @app_commands.command(name="warnings", description="List a member's warnings")
    @app_commands.guild_only()
    @mod_command("warnings")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        rows = self.bot.storage.warnings(interaction.guild.id, member.id)
        lines = [f"**#{len(rows) - i}** · {row['created_at'][:10]} · by <@{row['moderator_id']}>\n"
                 f"{ui.clip(row['reason'], 200)}" for i, row in enumerate(rows)]
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name} ({len(rows)})",
                              description=ui.bullet_list(lines, 4000) if lines else "No warnings. 🎉",
                              colour=ui.YELLOW if rows else ui.GREEN)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="Delete all of a member's warnings")
    @app_commands.guild_only()
    @mod_command("clearwarnings")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        problem = target_problem(interaction.user, member)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        n = self.bot.storage.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(f"Cleared {n} warning(s) for {member.mention}.",
                                                ephemeral=True)
        if n:
            await log_event(self.bot, interaction.guild, "🧽 Warnings cleared",
                            f"{member.mention} ({member}) · {n} warning(s)\n"
                            f"By {interaction.user.mention}")

    # ------------------------------------------------------------------ #
    @app_commands.command(name="purge", description="Bulk-delete recent messages in this channel")
    @app_commands.guild_only()
    @mod_command("purge")
    @app_commands.describe(amount="How many recent messages to check (1-100)",
                           member="Only delete messages from this member")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100],
                    member: discord.Member | None = None) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
            await interaction.response.send_message("I can't purge here.", ephemeral=True)
            return
        if not channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.response.send_message("I need Manage Messages in this channel.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            deleted = await channel.purge(
                limit=amount, check=(lambda m: m.author.id == member.id) if member else (lambda m: True),
                reason=f"/purge by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Couldn't purge: {exc.text or exc}", ephemeral=True)
            return
        who = f" from {member.mention}" if member else ""
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s){who}.", ephemeral=True)
        await log_event(self.bot, interaction.guild, "🧹 Messages purged",
                        f"{len(deleted)} message(s){who} in {channel.mention}\n"
                        f"By {interaction.user.mention}")

    # ------------------------------------------------------------------ #
    # Lockdown
    # ------------------------------------------------------------------ #
    # Permissions switched off for @everyone during a lockdown.
    LOCK_PERMS = ("send_messages", "send_messages_in_threads", "create_public_threads",
                  "create_private_threads", "add_reactions", "speak")

    @app_commands.command(name="lockdown", description="Stop members from talking (raid protection)")
    @app_commands.guild_only()
    @mod_command("lockdown")
    @app_commands.describe(scope="Just this channel, or the whole server",
                           pause_invites="Server only: also stop new people from joining",
                           reason="Shown in the channel and the mod log")
    async def lockdown(self, interaction: discord.Interaction,
                       scope: Literal["channel", "server"] = "channel",
                       pause_invites: bool = False, reason: str | None = None) -> None:
        guild = interaction.guild
        storage = self.bot.storage
        staff = self._role_setting(guild, "staff_role_id")
        why = f"Lockdown by {interaction.user}: {reason or 'no reason'}"[:500]

        if scope == "channel":
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("Run this in a text channel.", ephemeral=True)
                return
            locked = storage.get_json(guild.id, "lockdown_channels", None) or {}
            if str(channel.id) in locked:
                await interaction.response.send_message("This channel is already locked.", ephemeral=True)
                return
            if not channel.permissions_for(guild.me).manage_roles:
                await interaction.response.send_message("I can't change permissions in this channel.",
                                                        ephemeral=True)
                return
            # Remember the exact previous values so /unlock restores them, not a guess.
            saved = {"everyone": self._overwrite_values(channel, guild.default_role)}
            ow = channel.overwrites_for(guild.default_role)
            for perm in self.LOCK_PERMS:
                setattr(ow, perm, False)
            try:
                await channel.set_permissions(guild.default_role, overwrite=ow, reason=why)
                if staff is not None:
                    saved["staff"] = self._overwrite_values(channel, staff)
                    sow = channel.overwrites_for(staff)
                    sow.send_messages = True
                    await channel.set_permissions(staff, overwrite=sow, reason=why)
            except discord.HTTPException as exc:
                await interaction.response.send_message(f"Couldn't lock this channel: {exc.text or exc}",
                                                        ephemeral=True)
                return
            locked[str(channel.id)] = saved
            storage.set_json(guild.id, "lockdown_channels", locked)
            where = channel.mention
        else:
            if storage.get_json(guild.id, "lockdown_server", None):
                await interaction.response.send_message("The server is already locked.", ephemeral=True)
                return
            everyone = guild.default_role
            saved = {"everyone": {p: getattr(everyone.permissions, p) for p in self.LOCK_PERMS}}
            try:
                perms = everyone.permissions
                perms.update(**{p: False for p in self.LOCK_PERMS})
                await everyone.edit(permissions=perms, reason=why)
                # Staff normally talk through @everyone's permissions; keep them talking.
                if staff is not None and staff < guild.me.top_role and not staff.permissions.send_messages:
                    saved["staff_send"] = True
                    sperms = staff.permissions
                    sperms.update(send_messages=True, speak=True)
                    await staff.edit(permissions=sperms, reason=why)
                if pause_invites:
                    if guild.me.guild_permissions.manage_guild:
                        await guild.edit(invites_disabled=True, reason=why)
                        saved["invites"] = True
                    else:
                        saved["invites_note"] = True
            except discord.HTTPException as exc:
                await interaction.response.send_message(f"Couldn't lock the server: {exc.text or exc}",
                                                        ephemeral=True)
                return
            storage.set_json(guild.id, "lockdown_server", saved)
            where = "the whole server"

        text = f"🔒 **Locked down {where}.** Only staff can talk until a moderator runs `/unlock`."
        if reason:
            text += f"\nReason: {reason}"
        if scope == "server" and saved.get("invites"):
            text += "\nNew joins are paused."
        if scope == "server" and saved.get("invites_note"):
            text += "\n-# I couldn't pause invites: I need the Manage Server permission."
        await interaction.response.send_message(text)
        await log_event(self.bot, guild, "🔒 Lockdown", f"{where} by {interaction.user.mention}\n"
                        f"Reason: {reason or '—'}", colour=ui.RED)

    @app_commands.command(name="unlock", description="End a lockdown")
    @app_commands.guild_only()
    @mod_command("unlock")
    @app_commands.describe(scope="Just this channel, or the whole server")
    async def unlock(self, interaction: discord.Interaction,
                     scope: Literal["channel", "server"] = "channel") -> None:
        guild = interaction.guild
        storage = self.bot.storage
        why = f"Unlocked by {interaction.user}"
        try:
            if scope == "channel":
                channel = interaction.channel
                locked = storage.get_json(guild.id, "lockdown_channels", None) or {}
                saved = locked.get(str(getattr(channel, "id", 0)))
                if saved is None:
                    await interaction.response.send_message("This channel isn't locked.", ephemeral=True)
                    return
                await self._restore_overwrite(channel, guild.default_role, saved["everyone"], why)
                staff = self._role_setting(guild, "staff_role_id")
                if staff is not None and "staff" in saved:
                    await self._restore_overwrite(channel, staff, saved["staff"], why)
                del locked[str(channel.id)]
                storage.set_json(guild.id, "lockdown_channels", locked)
                where = channel.mention
            else:
                saved = storage.get_json(guild.id, "lockdown_server", None)
                if not saved:
                    await interaction.response.send_message("The server isn't locked.", ephemeral=True)
                    return
                perms = guild.default_role.permissions
                perms.update(**saved["everyone"])
                await guild.default_role.edit(permissions=perms, reason=why)
                staff = self._role_setting(guild, "staff_role_id")
                if saved.get("staff_send") and staff is not None and staff < guild.me.top_role:
                    sperms = staff.permissions
                    sperms.update(send_messages=False, speak=False)
                    await staff.edit(permissions=sperms, reason=why)
                if saved.get("invites"):
                    await guild.edit(invites_disabled=False, reason=why)
                storage.delete_setting(guild.id, "lockdown_server")
                where = "the whole server"
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"Couldn't unlock: {exc.text or exc}", ephemeral=True)
            return
        await interaction.response.send_message(f"🔓 **Unlocked {where}.** Everyone can talk again.")
        await log_event(self.bot, guild, "🔓 Lockdown ended", f"{where} by {interaction.user.mention}",
                        colour=ui.GREEN)

    def _role_setting(self, guild: discord.Guild, key: str) -> discord.Role | None:
        raw = self.bot.storage.get_setting(guild.id, key)
        return guild.get_role(int(raw)) if raw and raw.isdigit() else None

    def _overwrite_values(self, channel: discord.abc.GuildChannel, target) -> dict:
        ow = channel.overwrites_for(target)
        return {p: getattr(ow, p) for p in self.LOCK_PERMS + ("send_messages",)}

    async def _restore_overwrite(self, channel, target, values: dict, reason: str) -> None:
        ow = channel.overwrites_for(target)
        for perm, value in values.items():
            setattr(ow, perm, value)
        await channel.set_permissions(target, overwrite=None if ow.is_empty() else ow, reason=reason)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
