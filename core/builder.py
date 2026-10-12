"""Execute a Plan against a guild: sequential creation, retries, tracking and progress."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import discord

import templates
from core.layout import snapshot
from core.permissions import (PermissionContext, can_hand_out, grantable_by, is_access_role,
                              is_safe_self_assign_role, muted_overwrite, overwrites_for)
from core.plan import Plan, RoleSpec, split_leading_emoji
from core.retry import call_with_retry, describe_error
from core.storage import Storage
from core.wipe import wipe, wipe_targets

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
    backup_id: int | None = None  # layout saved before a fresh start (for /restore)


def normalize_emoji(emoji: str) -> str:
    """Discord may drop the U+FE0F variation selector when reporting reactions."""
    return emoji.replace("️", "")


class Builder:
    def __init__(self, guild: discord.Guild, plan: Plan, storage: Storage, *,
                 progress: ProgressCallback | None = None, delay: float = 0.6,
                 actor: discord.Member | None = None) -> None:
        self.guild = guild
        self.actor = actor  # the admin who ran /setup; limits which existing roles we expose
        self.plan = plan
        self.storage = storage
        self.progress = progress
        self.delay = delay
        self.result = BuildResult()
        self.roles: dict[str, discord.Role] = {}
        self.categories: dict[str, discord.CategoryChannel] = {}
        self.specials: dict[str, discord.abc.GuildChannel] = {}
        self.ctx: PermissionContext | None = None
        self._created_keys: set[str] = set()  # plan role keys created (not reused) this run
        self._new_channels: set[int] = set()  # channels created (not reused) this run
        self._deleted_ids: set[int] = set()
        self._done = 0
        self._total = 0

    # ------------------------------------------------------------------ #
    async def run(self) -> BuildResult:
        wipe_channels, wipe_roles = (wipe_targets(self.guild, self.storage, self.actor)
                                     if self.plan.wipe else ([], []))
        posts = (int(bool(self.plan.reaction_groups))
                 + int(self.plan.ticket_role is not None) + int("verification" in self.plan.features)
                 + int("rules_welcome" in self.plan.features))  # upper bound; rules may be skipped
        creates = len(self.plan.roles) + len(self.plan.categories) + len(self.plan.channels()) + posts
        self._total = len(wipe_channels) + len(wipe_roles) + creates

        if self.plan.wipe:
            self.result.backup_id = self.storage.add_backup(
                self.guild.id, "Before fresh start", snapshot(self.guild))
            wiped = await wipe(self.guild, self.storage, wipe_channels, wipe_roles,
                               reason=f"{REASON} (fresh start)", delay=self.delay,
                               tick=self._tick)
            self.result.deleted = wiped.deleted
            self._deleted_ids = wiped.deleted_ids
            if wiped.failed:
                self.result.warnings.append("Couldn't delete: " + ", ".join(wiped.failed))

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
            gate=self._resolve_gate(),
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
            if spec.self_assign and not self._may_expose(role):
                self.result.warnings.append(
                    f"@{role.name} already exists and isn't safe to make self-assignable (it has "
                    "moderator permissions, unlocks channels, or you couldn't assign it "
                    "yourself), so it was left out of the self-assign menu.")
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
        self._created_keys.add(spec.key)
        return role

    def _may_expose(self, role: discord.Role) -> bool:
        """May this pre-existing role become self-assignable by every member?"""
        # Applies to roles the bot made earlier too: an old staff role has no
        # "elevated" permissions but unlocks the staff channels.
        return (is_safe_self_assign_role(role)
                and not is_access_role(role)
                and self.actor is not None and can_hand_out(self.actor, role))

    def _bot_can_give(self, key: str) -> discord.Role | None:
        """The planned role ``key`` if the bot may hand it to members automatically
        (verify button, auto-role on join, level rewards), else None.

        Roles created this run are always fine. A reused role must pass the same
        checks as a self-assign role, except that the member role is allowed to
        unlock channels (that's its job with verification).
        """
        role = self.roles.get(key)
        if role is None or role >= self.guild.me.top_role:
            return None
        if key in self._created_keys:
            return role
        if key == "member":
            ok = (is_safe_self_assign_role(role) and self.actor is not None
                  and can_hand_out(self.actor, role))
        else:
            ok = self._may_expose(role)
        return role if ok else None

    def _resolve_gate(self) -> discord.Role | None:
        if "verification" not in self.plan.features:
            return None
        gate = self._bot_can_give("member")
        if gate is None:
            self.result.warnings.append(
                "Verification was turned off: the member role already existed and isn't safe for "
                "me to hand out (it has moderator permissions or is above your role), so channels "
                "were left visible to everyone.")
        return gate

    def _grantable(self, spec: RoleSpec) -> discord.Permissions:
        """Grant only permissions both the bot and the person running /setup hold.

        Otherwise someone with Manage Roles could have the bot mint a role with
        powers they lack and then assign it to themselves.
        """
        wanted = discord.Permissions(**{p: True for p in spec.permissions})
        bot = self.guild.me.guild_permissions
        granted = grantable_by(self.actor, wanted)
        if not bot.administrator:
            granted = discord.Permissions(granted.value & bot.value)
        dropped = [p for p in spec.permissions if not getattr(granted, p)]
        if dropped:
            self.result.warnings.append(
                f"@{spec.name} was created without {', '.join(dropped)} because you or I don't "
                "have those permissions. A server admin can add them manually.")
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
                    overwrites = overwrites_for(spec.preset, self.ctx, gated=spec.gated)
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
                    if spec.special:
                        self.specials[spec.special] = existing
                else:
                    # Always pass explicit overwrites. If they match the category's,
                    # Discord shows the channel as synced anyway.
                    overwrites = overwrites_for(spec.preset or cat.preset, self.ctx,
                                                gated=spec.gated)
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
                    self._new_channels.add(channel.id)
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
        from cogs.role_menu import build_reaction_message
        from cogs.tickets import build_ticket_panel
        from cogs.welcome import build_rules_embed, build_verify_panel

        posts: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        # Rules go first so they sit at the top of the rules channel.
        # Only into a new rules channel: a reused one already has whatever rules it needs.
        rules_channel = self.specials.get("rules")
        if (rules_channel is not None and rules_channel.id in self._new_channels
                and build_rules_embed(self.plan.server_type)):
            posts.append(("rules", lambda: self._post_panel(
                "rules", lambda: build_rules_embed(self.plan.server_type))))
        if self.plan.reaction_groups:
            posts.append(("reaction roles", lambda: self._post_reaction_menus(build_reaction_message)))
        if self.plan.ticket_role is not None:
            posts.append(("ticket panel", lambda: self._post_panel("ticket_panel", build_ticket_panel)))
        if "verification" in self.plan.features:
            posts.append(("verify panel", lambda: self._post_verify_panel(build_verify_panel)))

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

    def _menu_groups(self, groups: list):
        """[(group name, pick-one?, [(role, emoji)])], in the order typed."""
        specs = [r for r in self.plan.roles if r.reaction and r.key in self.roles]
        out = []
        for group in groups:
            roles = [self.roles[r.key] for r in specs if r.group == group.name]
            if roles:
                # Emoji only need to be unique within one message.
                out.append((group.name, group.exclusive, self._assign_emojis(roles)))
        return out

    def _remember_menu(self, groups) -> None:
        """Let the role-menu cog hand these roles out, and enforce pick-one groups."""
        gid = self.guild.id
        exclusive = self.storage.get_json(gid, "exclusive_role_groups", None) or []
        exclusive += [[role.id for role, _ in pairs] for _, excl, pairs in groups if excl]
        self.storage.set_json(gid, "exclusive_role_groups", exclusive)
        allowed = set(self.storage.get_json(gid, "self_roles", None) or [])
        allowed.update(role.id for _, _, pairs in groups for role, _ in pairs)
        self.storage.set_json(gid, "self_roles", sorted(allowed))

    async def _post_reaction_menus(self, build) -> None:
        """One message per group in the reaction-roles channel, each with its emoji added."""
        channel = self.specials.get("reaction_menu")
        groups = self._menu_groups(self.plan.reaction_groups)
        if not isinstance(channel, discord.TextChannel) or not groups:
            self.result.warnings.append("Reaction roles not posted (no channel or roles).")
            return
        all_maps = self.storage.get_json(self.guild.id, "reaction_roles", None) or {}
        for index, group in enumerate(groups):
            message = await call_with_retry(
                lambda: channel.send(embed=build(group, first=index == 0)), delay=self.delay)
            self._track(message, "message", f"reaction roles: {group[0]}", channel.id)
            mapping: dict[str, int] = {}
            for role, emoji in group[2]:
                try:
                    await call_with_retry(lambda: message.add_reaction(emoji), delay=0.35)
                    mapping[normalize_emoji(emoji)] = role.id
                except discord.HTTPException as exc:
                    self.result.warnings.append(
                        f"Couldn't add reaction {emoji} for @{role.name}: {describe_error(exc)}")
            all_maps[str(message.id)] = mapping
            # Saved after every message, so a failure part-way still leaves working menus.
            self.storage.set_json(self.guild.id, "reaction_roles", all_maps)
        self._remember_menu(groups)

    async def _post_panel(self, special: str, build) -> None:
        channel = self.specials.get(special)
        if not isinstance(channel, discord.TextChannel):
            self.result.warnings.append(f"The {special.replace('_', ' ')} wasn't posted "
                                        "(its channel is missing).")
            return
        embed, view = build()
        message = await call_with_retry(lambda: channel.send(embed=embed, view=view),
                                        delay=self.delay)
        self._track(message, "message", special.replace("_", " "), channel.id)

    async def _post_verify_panel(self, build) -> None:
        if self.ctx.gate is None:
            return  # verification was turned off, see _resolve_gate
        rules = self.specials.get("rules")
        await self._post_panel("verify", lambda: build(self.ctx.gate, rules))

    def _save_settings(self) -> None:
        """Settings the other cogs (tickets, role menu, welcome, leveling, stats) read later."""
        gid = self.guild.id
        store = self.storage
        features = set(self.plan.features)
        store.set_setting(gid, "server_type", self.plan.server_type)

        # A fresh start defines the server from scratch; "keep existing" only adds.
        def flag(key: str, on: bool) -> None:
            if on:
                store.set_setting(gid, key, "1")
            elif self.plan.wipe:
                store.delete_setting(gid, key)

        member = self._bot_can_give("member")
        if member is not None:
            store.set_setting(gid, "member_role_id", str(member.id))
        flag("verify_enabled", self.ctx.gate is not None)
        flag("leveling_enabled", "leveling" in features)
        if "leveling" in features:
            rewards = {}
            for spec in self.plan.roles:
                if spec.level and (role := self._bot_can_give(spec.key)):
                    rewards[str(spec.level)] = role.id
                elif spec.level and spec.key in self.roles:
                    self.result.warnings.append(
                        f"@{spec.name} already existed and isn't safe to give out automatically, "
                        "so it isn't a level reward.")
            store.set_json(gid, "level_roles", rewards)

        for special, key in (("welcome", "welcome_channel_id"), ("mod_log", "mod_log_channel_id"),
                             ("level_up", "level_channel_id"), ("verify", "verify_channel_id")):
            if (channel := self.specials.get(special)) is not None:
                store.set_setting(gid, key, str(channel.id))
        # The label is the name without a count, in case an old stat channel was reused.
        stats = {str(ch.id): {"kind": special[len("stat_"):],
                              "label": re.sub(r":\s*[\d,]+$", "", ch.name)}
                 for special, ch in self.specials.items() if special.startswith("stat_")}
        if stats:
            current = store.get_json(gid, "stat_channels", None) or {}
            store.set_json(gid, "stat_channels", {**current, **stats})

        for key, role in (("staff_role_id", self.ctx.staff), ("muted_role_id", self.ctx.muted)):
            if role:
                self.storage.set_setting(gid, key, str(role.id))
        if self.plan.ticket_role is not None:
            self.storage.set_setting(gid, "tickets_enabled", "1")
            self.storage.set_setting(gid, "ticket_category_name", self.plan.ticket_category_name)
            if self.ctx.ticket_role:
                self.storage.set_setting(gid, "ticket_role_id", str(self.ctx.ticket_role.id))
