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
                    "verify_channel_id", "stat_channels", "verify_enabled", "tickets_enabled")

Tick = Callable[[str, int, int], Awaitable[None]]


@dataclass
class WipeResult:
    deleted: Counter = field(default_factory=Counter)  # channel, role
    failed: list[str] = field(default_factory=list)
    deleted_ids: set[int] = field(default_factory=set)


def wipe_targets(guild: discord.Guild, storage: Storage, actor: discord.Member | None, *,
                 include_roles: bool = True) -> tuple[list[discord.abc.GuildChannel], list[discord.Role]]:
    """Every channel (children before categories) plus, optionally, the roles
    this bot made earlier that both the bot and ``actor`` may delete.

    Other roles hold members' assignments and permissions, so they're never wiped.
    """
    channels = sorted(guild.channels, key=lambda c: isinstance(c, discord.CategoryChannel))
    roles: list[discord.Role] = []
    if include_roles:
        for item in storage.items(guild.id):
            role = guild.get_role(item.item_id) if item.kind == "role" else None
            if (role is not None and role < guild.me.top_role
                    and actor is not None and can_hand_out(actor, role)):
                roles.append(role)
    return channels, roles


async def wipe(guild: discord.Guild, storage: Storage, channels: list[discord.abc.GuildChannel],
               roles: list[discord.Role], *, reason: str, delay: float = 0.6,
               tick: Tick | None = None) -> WipeResult:
    result = WipeResult()

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
        storage.delete_setting(guild.id, key)
    return result
