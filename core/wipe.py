"""Deleting a server's channels, used by fresh start, /restore and /template apply."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import discord

from core.permissions import can_hand_out
from core.retry import call_with_retry, describe_error
from core.storage import Storage

# Settings that point at channels or messages. They're stale once every
# channel is gone, so a wipe forgets them (a new setup writes fresh ones).
CHANNEL_SETTINGS = ("reaction_roles", "exclusive_role_groups", "ticket_category_id",
                    "mod_log_channel_id", "welcome_channel_id", "level_channel_id",
                    "verify_channel_id", "stat_channels", "verify_enabled", "tickets_enabled",
                    "suggestions_channel_id", "birthday_channel_id", "message_log_channel_id",
                    "voice_hubs", "temp_voice_channels")

Tick = Callable[[str, int, int], Awaitable[None]]


@dataclass
class WipeResult:
    deleted: Counter = field(default_factory=Counter)  # channel, role
    failed: list[str] = field(default_factory=list)
    deleted_ids: set[int] = field(default_factory=set)
    skipped: int = 0  # channels left alone because the actor couldn't delete them

    @property
    def complete(self) -> bool:
        """True if every channel is gone (nothing failed or was skipped)."""
        return not self.failed and not self.skipped


@dataclass
class WipeTargets:
    channels: list[discord.abc.GuildChannel]
    roles: list[discord.Role]
    skipped: int = 0  # channels the actor can't see or manage


def can_delete_channel(actor: discord.Member | None, channel: discord.abc.GuildChannel) -> bool:
    """Could ``actor`` delete this channel themselves? The bot must not delete
    channels hidden from the person asking (e.g. a private admin channel)."""
    if actor is None:
        return False
    if actor.guild.owner_id == actor.id or actor.guild_permissions.administrator:
        return True
    perms = channel.permissions_for(actor)
    return perms.view_channel and perms.manage_channels


def deletable_count(guild: discord.Guild, actor: discord.Member | None) -> int:
    """How many channels a fresh start by ``actor`` would delete (for confirmations)."""
    return sum(can_delete_channel(actor, c) for c in guild.channels)


def wipe_targets(guild: discord.Guild, storage: Storage, actor: discord.Member | None, *,
                 include_roles: bool = True) -> WipeTargets:
    """The channels ``actor`` could delete themselves (children before
    categories) plus, optionally, the roles this bot made earlier that both
    the bot and ``actor`` may delete.

    Other roles hold members' assignments and permissions, so they're never wiped.
    """
    allowed = [c for c in guild.channels if can_delete_channel(actor, c)]
    channels = sorted(allowed, key=lambda c: isinstance(c, discord.CategoryChannel))
    roles: list[discord.Role] = []
    if include_roles:
        for item in storage.items(guild.id):
            role = guild.get_role(item.item_id) if item.kind == "role" else None
            if (role is not None and role < guild.me.top_role
                    and actor is not None and can_hand_out(actor, role)):
                roles.append(role)
    return WipeTargets(channels, roles, skipped=len(guild.channels) - len(allowed))


async def wipe(guild: discord.Guild, storage: Storage, targets: WipeTargets, *, reason: str,
               delay: float = 0.6, tick: Tick | None = None) -> WipeResult:
    result = WipeResult(skipped=targets.skipped)
    channels, roles = targets.channels, targets.roles

    def forget(item_id: int) -> None:
        result.deleted_ids.add(item_id)
        storage.untrack(guild.id, item_id)

    for label, kind, targets in (("Deleting old channels", "channel", channels),
                                 ("Deleting old bot roles", "role", roles)):
        for i, target in enumerate(targets, 1):
            try:
                await call_with_retry(lambda: target.delete(reason=reason), delay=delay)
                forget(target.id)
                result.deleted[kind] += 1
            except discord.NotFound:
                forget(target.id)
            except discord.HTTPException as exc:
                # e.g. a Community server's required rules/updates channel.
                prefix = "@" if kind == "role" else "#"
                result.failed.append(f"{prefix}{target.name} ({describe_error(exc)})")
            if tick:
                await tick(label, i, len(targets))

    for key in CHANNEL_SETTINGS:
        # If any channel survived, it may still be gated behind verification.
        # Forgetting the flag would switch on auto-role for new members and
        # unlock those channels without verifying, so keep it (fail closed).
        if key == "verify_enabled" and not result.complete:
            continue
        storage.delete_setting(guild.id, key)
    return result


def report_wipe(warnings: list[str], wiped: WipeResult) -> None:
    """Add a fresh start's problems to a build summary's warnings."""
    if wiped.failed:
        warnings.append("Couldn't delete: " + ", ".join(wiped.failed))
    if wiped.skipped:
        warnings.append(f"Left {wiped.skipped} channel(s) alone because you can't see or manage "
                        "them yourself. Someone with access can delete them.")
