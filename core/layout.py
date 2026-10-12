"""Server layouts: snapshot a server's channels and roles as JSON, and rebuild them.

The same format is used for two things:

* backups  - taken automatically before anything deletes channels, and by
             /backup. /restore rebuilds the channels with the same names,
             settings, order and permission overwrites (matching roles by ID).
* templates - /template save. /template apply rebuilds the roles (matched by
             name, created if missing) and channels in any server.

Messages are never part of a layout: Discord has no way to bring them back.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import discord

from core.permissions import grantable_by
from core.retry import call_with_retry, describe_error
from core.storage import Storage
from core.wipe import report_wipe, wipe, wipe_targets

log = logging.getLogger(__name__)

LAYOUT_VERSION = 1
MAX_ROLES = 250
MAX_CATEGORIES = 50
MAX_CHANNELS = 500
MAX_OVERWRITES = 100
CHANNEL_TYPES = {"text", "news", "voice", "stage_voice", "forum"}
_ALL_PERMS = discord.Permissions.all().value


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #
def _overwrite_entry(target: Any, ow: discord.PermissionOverwrite) -> dict | None:
    allow, deny = ow.pair()
    if hasattr(target, "is_default"):  # a Role
        if target.is_default():
            return {"kind": "everyone", "allow": allow.value, "deny": deny.value}
        return {"kind": "role", "id": target.id, "name": target.name,
                "allow": allow.value, "deny": deny.value}
    if getattr(target, "type", None) is discord.Role:  # discord.Object for an uncached role
        return {"kind": "role", "id": target.id, "name": None, "allow": allow.value, "deny": deny.value}
    return {"kind": "member", "id": target.id, "allow": allow.value, "deny": deny.value}


def _overwrites(channel: discord.abc.GuildChannel) -> list[dict]:
    return [e for target, ow in channel.overwrites.items() if (e := _overwrite_entry(target, ow))]


def _channel_entry(channel: discord.abc.GuildChannel) -> dict:
    return {
        "type": str(channel.type),
        "name": channel.name,
        "topic": getattr(channel, "topic", None),
        "nsfw": bool(getattr(channel, "nsfw", False)),
        "slowmode": int(getattr(channel, "slowmode_delay", 0) or 0),
        "bitrate": getattr(channel, "bitrate", None),
        "user_limit": getattr(channel, "user_limit", None),
        "overwrites": _overwrites(channel),
    }


def snapshot(guild: discord.Guild, *, viewer: discord.Member | None = None) -> dict:
    """The guild's roles and channels as plain JSON-able data.

    With ``viewer``, channels they can't see are left out, so a template never
    reveals hidden channels to someone who couldn't open them.
    """
    def visible(channel: discord.abc.GuildChannel) -> bool:
        return viewer is None or channel.permissions_for(viewer).view_channel

    roles = [r for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
             if not r.is_default() and not r.managed]
    layout: dict = {
        "version": LAYOUT_VERSION,
        "source_bot_id": guild.me.id,
        "roles": [{"id": r.id, "name": r.name, "color": r.colour.value, "hoist": r.hoist,
                   "mentionable": r.mentionable, "permissions": r.permissions.value}
                  for r in roles],
        "categories": [],
        "channels": [],
    }
    for category, channels in guild.by_category():
        entries = [_channel_entry(c) for c in channels
                   if str(c.type) in CHANNEL_TYPES and visible(c)]
        if category is not None and not entries and not visible(category):
            continue
        if category is None:
            layout["channels"] = entries
        else:
            layout["categories"].append({"id": category.id, "name": category.name,
                                         "overwrites": _overwrites(category), "channels": entries})
    return layout


def layout_counts(layout: dict) -> tuple[int, int, int]:
    """(roles, categories, channels)"""
    channels = len(layout["channels"]) + sum(len(c["channels"]) for c in layout["categories"])
    return len(layout["roles"]), len(layout["categories"]), channels


# --------------------------------------------------------------------------- #
# Validation (for imported template files)
# --------------------------------------------------------------------------- #
def validate_layout(data: Any) -> dict:
    """Return ``data`` if it's a well-formed layout, else raise ValueError.

    Imported files are untrusted, so every field is type- and range-checked.
    """
    def fail(msg: str) -> None:
        raise ValueError(msg)

    def check_int(value: Any, lo: int, hi: int, what: str, optional: bool = False) -> None:
        if value is None and optional:
            return
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            fail(f"{what} must be a whole number from {lo} to {hi}")

    def check_str(value: Any, limit: int, what: str, optional: bool = False) -> None:
        if value is None and optional:
            return
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            fail(f"{what} must be text of 1-{limit} characters")

    def check_overwrites(items: Any, where: str) -> None:
        if not isinstance(items, list) or len(items) > MAX_OVERWRITES:
            fail(f"{where}: overwrites must be a list of at most {MAX_OVERWRITES}")
        for ow in items:
            if not isinstance(ow, dict) or ow.get("kind") not in ("everyone", "role", "member"):
                fail(f"{where}: bad overwrite")
            check_int(ow.get("allow"), 0, _ALL_PERMS, f"{where}: overwrite allow")
            check_int(ow.get("deny"), 0, _ALL_PERMS, f"{where}: overwrite deny")
            if ow["kind"] != "everyone":
                check_int(ow.get("id"), 0, 2**64 - 1, f"{where}: overwrite id")
            if ow["kind"] == "role":
                check_str(ow.get("name"), 100, f"{where}: overwrite role name", optional=True)

    def check_channel(ch: Any, where: str) -> None:
        if not isinstance(ch, dict) or ch.get("type") not in CHANNEL_TYPES:
            fail(f"{where}: unknown channel type")
        check_str(ch.get("name"), 100, f"{where}: name")
        check_str(ch.get("topic"), 1024, f"{where}: topic", optional=True)
        if not isinstance(ch.get("nsfw", False), bool):
            fail(f"{where}: nsfw must be true or false")
        check_int(ch.get("slowmode", 0), 0, 21600, f"{where}: slowmode")
        check_int(ch.get("bitrate"), 8000, 384000, f"{where}: bitrate", optional=True)
        check_int(ch.get("user_limit"), 0, 99, f"{where}: user limit", optional=True)
        check_overwrites(ch.get("overwrites", []), where)

    if not isinstance(data, dict) or data.get("version") != LAYOUT_VERSION:
        fail("this isn't a server template file from this bot")
    for key in ("roles", "categories", "channels"):
        if not isinstance(data.get(key), list):
            fail(f"missing {key!r} list")
    check_int(data.get("source_bot_id"), 0, 2**64 - 1, "source_bot_id", optional=True)
    if len(data["roles"]) > MAX_ROLES:
        fail(f"at most {MAX_ROLES} roles")
    for role in data["roles"]:
        if not isinstance(role, dict):
            fail("bad role")
        check_str(role.get("name"), 100, "role name")
        check_int(role.get("id"), 0, 2**64 - 1, "role id", optional=True)
        check_int(role.get("color", 0), 0, 0xFFFFFF, f"role {role['name']!r} color")
        check_int(role.get("permissions", 0), 0, _ALL_PERMS, f"role {role['name']!r} permissions")
        for flag in ("hoist", "mentionable"):
            if not isinstance(role.get(flag, False), bool):
                fail(f"role {role['name']!r}: {flag} must be true or false")
    if len(data["categories"]) > MAX_CATEGORIES:
        fail(f"at most {MAX_CATEGORIES} categories")
    for cat in data["categories"]:
        if not isinstance(cat, dict) or not isinstance(cat.get("channels"), list):
            fail("bad category")
        check_str(cat.get("name"), 100, "category name")
        check_overwrites(cat.get("overwrites", []), f"category {cat['name']!r}")
        for ch in cat["channels"]:
            check_channel(ch, f"channel in {cat['name']!r}")
    for ch in data["channels"]:
        check_channel(ch, "channel")
    if layout_counts(data)[2] > MAX_CHANNELS:
        fail(f"at most {MAX_CHANNELS} channels")
    return data


def as_template(layout: dict) -> dict:
    """Strip server-specific IDs so the layout can be applied anywhere."""
    def clean(overwrites: list[dict]) -> list[dict]:
        out = []
        for ow in overwrites:
            if ow["kind"] == "member":
                # Only the bot's own overwrite carries over (it keeps hidden
                # channels manageable); other members don't exist elsewhere.
                if ow["id"] == layout.get("source_bot_id"):
                    out.append({**ow, "kind": "member", "id": 0})
            elif ow["kind"] == "role" and ow.get("name"):
                out.append({"kind": "role", "id": 0, "name": ow["name"],
                            "allow": ow["allow"], "deny": ow["deny"]})
            elif ow["kind"] == "everyone":
                out.append(ow)
        return out

    def channel(ch: dict) -> dict:
        return {**ch, "overwrites": clean(ch.get("overwrites", []))}

    return {
        "version": LAYOUT_VERSION,
        "source_bot_id": 0,  # member overwrite id 0 = "this bot"
        "roles": [{k: v for k, v in r.items() if k != "id"} for r in layout["roles"]],
        "categories": [{"name": c["name"], "overwrites": clean(c.get("overwrites", [])),
                        "channels": [channel(ch) for ch in c["channels"]]}
                       for c in layout["categories"]],
        "channels": [channel(ch) for ch in layout["channels"]],
    }


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
@dataclass
class LayoutResult:
    created: Counter = field(default_factory=Counter)
    deleted: Counter = field(default_factory=Counter)
    reused: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    home_channel: discord.TextChannel | None = None
    backup_id: int | None = None


class LayoutApplier:
    """Rebuild a layout in ``guild``.

    mode="restore": channels only; roles are matched by ID. Nothing is tracked,
                    because these are the server's own channels coming back.
    mode="template": roles are matched by name (created if missing); everything
                    created is tracked so /reset can remove it.
    wipe=True deletes every existing channel first (after taking a backup).
    """

    def __init__(self, guild: discord.Guild, layout: dict, storage: Storage, *,
                 actor: discord.Member, mode: str, wipe: bool, reason: str,
                 progress: Any = None, delay: float = 0.6) -> None:
        assert mode in ("restore", "template")
        self.guild, self.layout, self.storage = guild, layout, storage
        self.actor, self.mode, self.wipe, self.reason = actor, mode, wipe, reason
        self.progress, self.delay = progress, delay
        self.result = LayoutResult()
        self.roles_by_name: dict[str, discord.Role] = {}
        self._dropped_perms = 0
        self._missing_targets = 0
        self._above_actor = 0
        self._done = 0
        self._total = 0

    async def run(self) -> LayoutResult:
        targets = (wipe_targets(self.guild, self.storage, self.actor,
                                include_roles=self.mode == "template") if self.wipe else None)
        n_roles, n_cats, n_chans = layout_counts(self.layout)
        self._total = n_cats + n_chans + (len(targets.channels) + len(targets.roles) if targets else 0)
        if self.mode == "template":
            self._total += n_roles

        if self.wipe:
            self.result.backup_id = self.storage.add_backup(
                self.guild.id, f"Before {self.reason.lower()}", snapshot(self.guild))
            wiped = await wipe(self.guild, self.storage, targets,
                               reason=f"{self.reason} (fresh start)", delay=self.delay,
                               tick=self._tick)
            self.result.deleted = wiped.deleted
            report_wipe(self.result.warnings, wiped)

        if self.mode == "template":
            await self._create_roles()
        await self._create_channels()

        if self._dropped_perms:
            self.result.warnings.append(
                f"{self._dropped_perms} permission setting(s) were left out because you or I "
                "don't have those permissions.")
        if self._above_actor:
            self.result.warnings.append(
                f"{self._above_actor} permission overwrite(s) for roles at or above your highest "
                "role were left out. Someone higher up can add them.")
        if self._missing_targets:
            self.result.warnings.append(
                f"{self._missing_targets} permission overwrite(s) were skipped because their "
                "role or member no longer exists.")
        return self.result

    async def _tick(self, label: str, done: int, total: int) -> None:
        self._done += 1
        if self.progress:
            await self.progress(label, done, total, self._done, self._total)

    def _track(self, obj: discord.abc.Snowflake, kind: str, name: str,
               parent_id: int | None = None) -> None:
        self.result.created[kind] += 1
        if self.mode == "template":
            self.storage.track(self.guild.id, obj.id, kind, name, parent_id)

    # ------------------------------------------------------------------ #
    def _cap(self, allow: int, deny: int, *, for_role: bool = False) -> tuple[int, int]:
        """Never set a permission the person running this (or the bot) lacks."""
        bot = self.guild.me.guild_permissions
        bot_limit = _ALL_PERMS if bot.administrator else bot.value
        if not bot.administrator and not for_role:
            # Granting Manage Permissions in an overwrite needs Administrator.
            bot_limit &= ~discord.Permissions(manage_roles=True).value
        capped_allow = allow & grantable_by(self.actor, discord.Permissions.all()).value & bot_limit
        capped_deny = deny & bot_limit
        if (capped_allow, capped_deny) != (allow, deny):
            self._dropped_perms += 1
        return capped_allow, capped_deny

    async def _create_roles(self) -> None:
        existing = {r.name.lower(): r for r in self.guild.roles if not r.is_default()}
        specs = self.layout["roles"]
        for i, spec in enumerate(specs, 1):
            try:
                role = existing.get(spec["name"].lower())
                if role is not None:
                    self.result.reused.append(f"@{role.name}")
                else:
                    perms, _ = self._cap(spec.get("permissions", 0), 0, for_role=True)
                    role = await call_with_retry(
                        lambda: self.guild.create_role(
                            name=spec["name"], permissions=discord.Permissions(perms),
                            colour=discord.Colour(spec.get("color", 0)),
                            hoist=spec.get("hoist", False), mentionable=spec.get("mentionable", False),
                            reason=self.reason),
                        delay=self.delay)
                    self._track(role, "role", role.name)
                    existing[role.name.lower()] = role
                self.roles_by_name[spec["name"].lower()] = role
            except discord.HTTPException as exc:
                self.result.errors.append(f"Role @{spec['name']}: {describe_error(exc)}")
            await self._tick("Creating roles", i, len(specs))

    def _target(self, ow: dict) -> discord.abc.Snowflake | None:
        if ow["kind"] == "everyone":
            return self.guild.default_role
        if ow["kind"] == "role":
            if self.mode == "restore":
                return self.guild.get_role(ow["id"])
            return self.roles_by_name.get((ow.get("name") or "").lower())
        # member: the bot's own overwrite maps to this bot; in templates, others are dropped
        if ow["id"] in (0, self.layout.get("source_bot_id")):
            return self.guild.me
        if self.mode == "restore":
            return discord.Object(id=ow["id"], type=discord.Member)
        return None

    def _may_set_for(self, target) -> bool:
        """Discord only lets you edit overwrites for roles below your highest role
        (unless you own the server); the bot must not be a way around that."""
        if not hasattr(target, "is_default") or target.is_default():
            return True  # @everyone, members and the bot itself
        actor = self.actor
        if actor.guild.owner_id == actor.id:
            return True
        return target < actor.top_role

    def _build_overwrites(self, entries: list[dict]) -> dict:
        out = {}
        for ow in entries:
            target = self._target(ow)
            if target is None:
                self._missing_targets += 1
                continue
            if not self._may_set_for(target):
                self._above_actor += 1
                continue
            allow, deny = self._cap(ow["allow"], ow["deny"])
            out[target] = discord.PermissionOverwrite.from_pair(discord.Permissions(allow),
                                                                discord.Permissions(deny))
        return out

    async def _create_channels(self) -> None:
        names_in: dict[int | None, set[tuple[str, str]]] = {}
        if not self.wipe:  # keep mode: skip channels that already exist by name
            for category, chans in self.guild.by_category():
                names_in[category.id if category else None] = {
                    (_family(str(c.type)), c.name.lower()) for c in chans}
        existing_cats = {c.name.lower(): c for c in self.guild.categories} if not self.wipe else {}

        await self._create_channel_list(None, self.layout["channels"], names_in)
        cats = self.layout["categories"]
        for i, spec in enumerate(cats, 1):
            category = existing_cats.get(spec["name"].lower())
            try:
                if category is not None:
                    self.result.reused.append(f"📁 {category.name}")
                else:
                    overwrites = self._build_overwrites(spec.get("overwrites", []))
                    category = await call_with_retry(
                        lambda: self.guild.create_category(spec["name"], overwrites=overwrites,
                                                           reason=self.reason),
                        delay=self.delay)
                    self._track(category, "category", category.name)
            except discord.HTTPException as exc:
                self.result.errors.append(f"Category {spec['name']}: {describe_error(exc)}")
                category = None
            await self._tick("Creating categories", i, len(cats))
            if category is None:
                for ch in spec["channels"]:
                    self.result.errors.append(f"#{ch['name']}: skipped because its category failed")
                    await self._tick("Creating channels", 0, 0)
                continue
            await self._create_channel_list(category, spec["channels"], names_in)

    async def _create_channel_list(self, category: discord.CategoryChannel | None,
                                   specs: list[dict], names_in: dict) -> None:
        taken = names_in.get(category.id if category else None, set())
        for i, spec in enumerate(specs, 1):
            kind = spec["type"]
            try:
                if (_family(kind), spec["name"].lower()) in taken:
                    self.result.reused.append(f"#{spec['name']}")
                else:
                    channel = await self._create_channel(category, spec)
                    self._track(channel, "channel", channel.name, category.id if category else None)
                    if (self.result.home_channel is None
                            and isinstance(channel, discord.TextChannel)):
                        self.result.home_channel = channel
            except discord.HTTPException as exc:
                self.result.errors.append(f"#{spec['name']}: {describe_error(exc)}")
            await self._tick("Creating channels", i, len(specs))

    async def _create_channel(self, category: discord.CategoryChannel | None, spec: dict):
        guild, kind = self.guild, spec["type"]
        overwrites = self._build_overwrites(spec.get("overwrites", []))
        common = {"category": category, "overwrites": overwrites, "reason": self.reason}
        if kind in ("voice", "stage_voice"):
            if kind == "stage_voice":
                self.result.warnings.append(f"Stage channel {spec['name']} was recreated as a "
                                            "voice channel.")
            extra = {}
            if spec.get("bitrate"):
                extra["bitrate"] = min(spec["bitrate"], int(guild.bitrate_limit))
            if spec.get("user_limit"):
                extra["user_limit"] = spec["user_limit"]
            return await call_with_retry(
                lambda: guild.create_voice_channel(spec["name"], **common, **extra), delay=self.delay)

        extra = {"nsfw": spec.get("nsfw", False)}
        if spec.get("topic"):
            extra["topic"] = spec["topic"]
        if spec.get("slowmode"):
            extra["slowmode_delay"] = spec["slowmode"]
        if kind == "forum":
            try:
                return await call_with_retry(
                    lambda: guild.create_forum(spec["name"], **common, **extra), delay=self.delay)
            except discord.HTTPException:
                self.result.warnings.append(f"Forum {spec['name']} was recreated as a text channel.")
        return await call_with_retry(
            lambda: guild.create_text_channel(spec["name"], **common, **extra), delay=self.delay)


def _family(kind: str) -> str:
    return "voice" if kind in ("voice", "stage_voice") else "text"
