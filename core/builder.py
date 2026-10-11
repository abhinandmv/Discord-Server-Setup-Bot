"""Execute a Plan against a guild: sequential creation, retries, tracking and progress."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import discord

import templates
from core.permissions import (PermissionContext, is_safe_self_assign_role, muted_overwrite,
                              overwrites_for)
from core.plan import Plan, RoleSpec, split_leading_emoji
from core.retry import call_with_retry, describe_error
from core.storage import Storage

log = logging.getLogger(__name__)

REASON = "Server setup wizard"

# (label, done in phase, phase total, done overall, total overall)
ProgressCallback = Callable[[str, int, int, int, int], Awaitable[None]]


@dataclass
class BuildResult:
    created: Counter = field(default_factory=Counter)  # keys: role, category, channel, message
    deleted: Counter = field(default_factory=Counter)  # fresh start: channel, role
    reused: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    home_channel: discord.TextChannel | None = None  # where to post the summary after a wipe


def normalize_emoji(emoji: str) -> str:
    """Discord may drop the U+FE0F variation selector when reporting reactions."""
    return emoji.replace("️", "")


class Builder:
    def __init__(self, guild: discord.Guild, plan: Plan, storage: Storage, *,
                 progress: ProgressCallback | None = None, delay: float = 0.6) -> None:
        self.guild = guild
        self.plan = plan
        self.storage = storage
        self.progress = progress
        self.delay = delay
        self.result = BuildResult()
        self.roles: dict[str, discord.Role] = {}
        self.categories: dict[str, discord.CategoryChannel] = {}
        self.specials: dict[str, discord.TextChannel] = {}
        self.ctx: PermissionContext | None = None
        self._deleted_ids: set[int] = set()
        self._done = 0
        self._total = 0

    # ------------------------------------------------------------------ #
    async def run(self) -> BuildResult:
        wipe_channels, wipe_roles = self._wipe_targets() if self.plan.wipe else ([], [])
        posts = int(any(r.self_assign for r in self.plan.roles)) + int(self.plan.ticket_role is not None)
        creates = len(self.plan.roles) + len(self.plan.categories) + len(self.plan.channels()) + posts
        self._total = len(wipe_channels) + len(wipe_roles) + creates

        if self.plan.wipe:
            await self._wipe(wipe_channels, wipe_roles)

        muted = self.plan.role("muted")
        # Snapshot before we create anything: these are the channels a human made
        # (after a fresh start, only ones that couldn't be deleted).
        existing = [] if muted is None or self._reusing(muted) else [
            c for c in self.guild.channels if c.id not in self._deleted_ids]  # cache may lag
        self._total += len(existing)

        await self._create_roles()
        self.ctx = PermissionContext(
            guild=self.guild,
            staff=self.roles.get("staff"),
            muted=self.roles.get("muted"),
            ticket_role=self._resolve_ticket_role(),
        )
        await self._create_categories()
        await self._create_channels()
        await self._mute_existing(existing)
        await self._post_menus()
        self._save_settings()
        return self.result

    async def _tick(self, label: str, done: int, total: int) -> None:
        self._done += 1
        if self.progress:
            await self.progress(label, done, total, self._done, self._total)

    def _track(self, obj: discord.abc.Snowflake, kind: str, name: str,
               parent_id: int | None = None) -> None:
        self.storage.track(self.guild.id, obj.id, kind, name, parent_id)
        self.result.created[kind] += 1

    def _reusing(self, spec) -> bool:
        return self.plan.reuses(spec) and spec.existing_id not in self._deleted_ids

    # ------------------------------------------------------------------ #
    # Fresh start
    # ------------------------------------------------------------------ #
    def _wipe_targets(self) -> tuple[list[discord.abc.GuildChannel], list[discord.Role]]:
        # Children before categories, so each category is empty when deleted.
        channels = sorted(self.guild.channels, key=lambda c: isinstance(c, discord.CategoryChannel))
        # Only roles this bot made earlier. Other roles hold members' assignments
        # and permissions, so a fresh start leaves them alone.
        roles = []
        for item in self.storage.items(self.guild.id):
            role = self.guild.get_role(item.item_id) if item.kind == "role" else None
            if role is not None and role < self.guild.me.top_role:
                roles.append(role)
        return channels, roles

    async def _wipe(self, channels: list[discord.abc.GuildChannel], roles: list[discord.Role]) -> None:
        failed: list[str] = []
        for i, channel in enumerate(channels, 1):
            try:
                await call_with_retry(lambda: channel.delete(reason=f"{REASON} (fresh start)"),
                                      delay=self.delay)
                self._forget(channel.id)
                self.result.deleted["channel"] += 1
            except discord.NotFound:
                self._forget(channel.id)
            except discord.HTTPException as exc:
                # e.g. a Community server's required rules/updates channel.
                failed.append(f"#{channel.name} ({describe_error(exc)})")
            await self._tick("Deleting old channels", i, len(channels))

        for i, role in enumerate(roles, 1):
            try:
                await call_with_retry(lambda: role.delete(reason=f"{REASON} (fresh start)"),
                                      delay=self.delay)
                self._forget(role.id)
                self.result.deleted["role"] += 1
            except discord.NotFound:
                self._forget(role.id)
            except discord.HTTPException as exc:
                failed.append(f"@{role.name} ({describe_error(exc)})")
            await self._tick("Deleting old bot roles", i, len(roles))

        if failed:
            self.result.warnings.append("Couldn't delete: " + ", ".join(failed))
        # Menus and ticket channels from earlier runs are gone now.
        for key in ("reaction_roles", "ticket_category_id"):
            self.storage.delete_setting(self.guild.id, key)

    def _forget(self, item_id: int) -> None:
        self._deleted_ids.add(item_id)
        self.storage.untrack(self.guild.id, item_id)

    # ------------------------------------------------------------------ #
    # Roles
    # ------------------------------------------------------------------ #
    async def _create_roles(self) -> None:
        total = len(self.plan.roles)
        for i, spec in enumerate(self.plan.roles, 1):
            try:
                role = await self._ensure_role(spec)
                if role is not None:
                    self.roles[spec.key] = role
            except discord.HTTPException as exc:
                self.result.errors.append(f"Role @{spec.name}: {describe_error(exc)}")
            await self._tick("Creating roles", i, total)

    async def _ensure_role(self, spec: RoleSpec) -> discord.Role | None:
        if self._reusing(spec) and (role := self.guild.get_role(spec.existing_id)):
            if spec.self_assign and not is_safe_self_assign_role(role):
                self.result.warnings.append(
                    f"@{role.name} already exists with moderator/admin permissions, so it was "
                    "left out of the self-assign menu.")
                return None
            self.result.reused.append(f"@{role.name}")
            return role

        perms = self._grantable(spec)
        role = await call_with_retry(
            lambda: self.guild.create_role(
                name=spec.name, permissions=perms, colour=discord.Colour(spec.color),
                hoist=spec.hoist, mentionable=spec.mentionable, reason=REASON),
            delay=self.delay)
        self._track(role, "role", role.name)
        return role

    def _grantable(self, spec: RoleSpec) -> discord.Permissions:
        """A bot can only grant permissions it has itself; drop the rest and warn."""
        wanted = discord.Permissions(**{p: True for p in spec.permissions})
        have = self.guild.me.guild_permissions
        if have.administrator:
            return wanted
        granted = discord.Permissions(wanted.value & have.value)
        dropped = [p for p in spec.permissions if not getattr(granted, p)]
        if dropped:
            self.result.warnings.append(
                f"@{spec.name} was created without {', '.join(dropped)} because I don't have "
                "those permissions myself. Add them manually if you want them.")
        return granted

    def _resolve_ticket_role(self) -> discord.Role | None:
        value = self.plan.ticket_role
        if not value:
            return None
        role = None
        if value.startswith("plan:"):
            role = self.roles.get(value[5:])
        elif value.startswith("id:"):
            role = self.guild.get_role(int(value[3:]))
        if role is None:
            role = self.roles.get("staff")
            self.result.warnings.append("The chosen ticket role wasn't available; tickets use the "
                                        "staff role instead.")
        return role

    # ------------------------------------------------------------------ #
    # Categories & channels
    # ------------------------------------------------------------------ #
    async def _create_categories(self) -> None:
        total = len(self.plan.categories)
        for i, spec in enumerate(self.plan.categories, 1):
            try:
                existing = self.guild.get_channel(spec.existing_id) if spec.existing_id else None
                if self._reusing(spec) and isinstance(existing, discord.CategoryChannel):
                    # Reused categories keep their own permissions. Channels we put in
                    # them still get explicit overwrites below, so a staff channel
                    # stays private even inside a public category of the same name.
                    self.categories[spec.key] = existing
                    self.result.reused.append(f"📁 {existing.name}")
                else:
                    overwrites = overwrites_for(spec.preset, self.ctx)
                    category = await call_with_retry(
                        lambda: self.guild.create_category(spec.name, overwrites=overwrites,
                                                           reason=REASON),
                        delay=self.delay)
                    self._track(category, "category", category.name)
                    self.categories[spec.key] = category
            except discord.HTTPException as exc:
                self.result.errors.append(f"Category {spec.name}: {describe_error(exc)}")
            await self._tick("Creating categories", i, total)

    async def _create_channels(self) -> None:
        pairs = self.plan.channels()
        total = len(pairs)
        first_text: discord.TextChannel | None = None
        for i, (cat, spec) in enumerate(pairs, 1):
            try:
                parent = self.categories.get(cat.key)
                existing = self.guild.get_channel(spec.existing_id) if spec.existing_id else None
                if parent is None:
                    self.result.errors.append(
                        f"{spec.display}: skipped because category {cat.name} wasn't created")
                elif self._reusing(spec) and existing is not None:
                    self.result.reused.append(spec.display)
                    if spec.special and isinstance(existing, discord.TextChannel):
                        self.specials[spec.special] = existing
                else:
                    # Always pass explicit overwrites. If they match the category's,
                    # Discord shows the channel as synced anyway.
                    overwrites = overwrites_for(spec.preset or cat.preset, self.ctx)
                    if spec.kind == "voice":
                        factory = lambda: self.guild.create_voice_channel(  # noqa: E731
                            spec.name, category=parent, overwrites=overwrites, reason=REASON)
                    else:
                        kwargs = {"topic": spec.topic} if spec.topic else {}
                        factory = lambda: self.guild.create_text_channel(  # noqa: E731
                            spec.name, category=parent, overwrites=overwrites, reason=REASON,
                            **kwargs)
                    channel = await call_with_retry(factory, delay=self.delay)
                    self._track(channel, "channel", channel.name, parent.id)
                    if spec.special:
                        self.specials[spec.special] = channel
                    if spec.kind == "text":
                        first_text = first_text or channel
                        if cat.key == "staff" and self.result.home_channel is None:
                            self.result.home_channel = channel
            except discord.HTTPException as exc:
                self.result.errors.append(f"{spec.display}: {describe_error(exc)}")
            await self._tick("Creating channels", i, total)
        self.result.home_channel = self.result.home_channel or first_text

    async def _mute_existing(self, channels: list[discord.abc.GuildChannel]) -> None:
        """Make the new Muted role apply in channels that existed before setup.

        Every channel gets its own overwrite. Editing a category's overwrites
        through the API does not update its child channels.
        """
        muted = self.roles.get("muted")
        if muted is None or not channels:
            return
        skipped = 0
        total = len(channels)
        for i, channel in enumerate(channels, 1):
            try:
                if channel.permissions_for(self.guild.me).manage_roles:
                    await call_with_retry(
                        lambda: channel.set_permissions(muted, overwrite=muted_overwrite(),
                                                        reason=REASON),
                        delay=self.delay)
                else:
                    skipped += 1
            except discord.HTTPException:
                skipped += 1
            await self._tick("Applying Muted to existing channels", i, total)
        if skipped:
            self.result.warnings.append(
                f"Couldn't apply @{muted.name} to {skipped} existing channel(s) I can't manage. "
                "Add a deny overwrite there manually.")

    # ------------------------------------------------------------------ #
    # Interactive messages
    # ------------------------------------------------------------------ #
    async def _post_menus(self) -> None:
        # Imported here: the cogs import core, so importing them at module load would be circular.
        from cogs.role_menu import build_role_menu
        from cogs.tickets import build_ticket_panel

        posts: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self_roles = [self.roles[r.key] for r in self.plan.roles
                      if r.self_assign and r.key in self.roles]
        if any(r.self_assign for r in self.plan.roles):
            posts.append(("role menu", lambda: self._post_role_menu(self_roles, build_role_menu)))
        if self.plan.ticket_role is not None:
            posts.append(("ticket panel", lambda: self._post_ticket_panel(build_ticket_panel)))

        for i, (what, post) in enumerate(posts, 1):
            try:
                await post()
            except discord.HTTPException as exc:
                self.result.errors.append(f"Posting the {what}: {describe_error(exc)}")
            await self._tick("Posting menus", i, len(posts))

    @staticmethod
    def _assign_emojis(roles: list[discord.Role]) -> list[tuple[discord.Role, str]]:
        """Use the emoji a role name starts with, else the next unused palette emoji."""
        wanted = [split_leading_emoji(r.name)[0] for r in roles]
        used = {normalize_emoji(e) for e in wanted if e}
        palette = (e for e in templates.REACTION_PALETTE if normalize_emoji(e) not in used)
        pairs = []
        seen: set[str] = set()
        for role, emoji in zip(roles, wanted):
            if not emoji or normalize_emoji(emoji) in seen:
                emoji = next(palette)
            seen.add(normalize_emoji(emoji))
            pairs.append((role, emoji))
        return pairs

    async def _post_role_menu(self, roles: list[discord.Role], build) -> None:
        channel = self.specials.get("role_menu")
        if channel is None or not roles:
            self.result.warnings.append("Self-assign menu not posted (no roles channel or roles).")
            return
        pairs = self._assign_emojis(roles)
        embed, view = build(pairs)
        message = await call_with_retry(lambda: channel.send(embed=embed, view=view),
                                        delay=self.delay)
        self._track(message, "message", "role menu", channel.id)

        # Reaction roles on the same message: react to add, un-react to remove.
        mapping: dict[str, int] = {}
        for role, emoji in pairs:
            try:
                await call_with_retry(lambda: message.add_reaction(emoji), delay=0.35)
                mapping[normalize_emoji(emoji)] = role.id
            except discord.HTTPException as exc:
                self.result.warnings.append(f"Couldn't add reaction {emoji} for @{role.name}: "
                                            f"{describe_error(exc)} (its button still works)")
        all_maps = self.storage.get_json(self.guild.id, "reaction_roles", None) or {}
        all_maps[str(message.id)] = mapping
        self.storage.set_json(self.guild.id, "reaction_roles", all_maps)

        allowed = set(self.storage.get_json(self.guild.id, "self_roles", None) or [])
        allowed.update(r.id for r in roles)
        self.storage.set_json(self.guild.id, "self_roles", sorted(allowed))

    async def _post_ticket_panel(self, build) -> None:
        channel = self.specials.get("ticket_panel")
        if channel is None:
            self.result.warnings.append("Ticket panel not posted (ticket channel missing).")
            return
        embed, view = build()
        message = await call_with_retry(lambda: channel.send(embed=embed, view=view),
                                        delay=self.delay)
        self._track(message, "message", "ticket panel", channel.id)

    def _save_settings(self) -> None:
        """Settings the ticket and role-menu cogs read later."""
        gid = self.guild.id
        for key, role in (("staff_role_id", self.ctx.staff), ("muted_role_id", self.ctx.muted)):
            if role:
                self.storage.set_setting(gid, key, str(role.id))
        if self.plan.ticket_role is not None:
            self.storage.set_setting(gid, "tickets_enabled", "1")
            self.storage.set_setting(gid, "ticket_category_name", self.plan.ticket_category_name)
            if self.ctx.ticket_role:
                self.storage.set_setting(gid, "ticket_role_id", str(self.ctx.ticket_role.id))
