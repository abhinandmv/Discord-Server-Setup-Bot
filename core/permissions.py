"""Permission presets (templates.PRESETS) turned into concrete channel overwrites."""

from __future__ import annotations

from dataclasses import dataclass

import discord

# Permissions the bot needs at server level for /setup. Overwrites can only
# allow/deny permissions the bot itself has, which is why voice/reaction perms
# are here even though the bot never uses them.
REQUIRED_PERMISSIONS: dict[str, str] = {
    "view_channel": "View Channels",
    "manage_channels": "Manage Channels",
    "manage_roles": "Manage Roles",
    "send_messages": "Send Messages",
    "send_messages_in_threads": "Send Messages in Threads",
    "create_public_threads": "Create Public Threads",
    "create_private_threads": "Create Private Threads",
    "embed_links": "Embed Links",
    "attach_files": "Attach Files",
    "read_message_history": "Read Message History",
    "add_reactions": "Add Reactions",
    "connect": "Connect",
    "speak": "Speak",
}

# Shown next to channels in the preview.
PRESET_LABELS: dict[str, str] = {
    "public": "",
    "announcement": "staff post, everyone reads",
    "readonly": "read-only",
    "staff_only": "staff only",
    "tickets": "private: ticket role + creator",
    "locked": "display only",
}

# Presets that the verification gate hides from unverified members. The other
# presets are already hidden from @everyone.
GATEABLE_PRESETS = {"public", "announcement", "readonly", "locked"}


def missing_bot_permissions(perms: discord.Permissions) -> list[str]:
    if perms.administrator:
        return []
    return [label for attr, label in REQUIRED_PERMISSIONS.items() if not getattr(perms, attr)]


def muted_overwrite() -> discord.PermissionOverwrite:
    """Muted: can still read, but can't type, react, use threads or speak."""
    return discord.PermissionOverwrite(
        send_messages=False,
        send_messages_in_threads=False,
        create_public_threads=False,
        create_private_threads=False,
        add_reactions=False,
        speak=False,
    )


def _bot_overwrite() -> discord.PermissionOverwrite:
    # Without this the bot couldn't see hidden channels or post its menus in
    # read-only ones (an @everyone deny beats the bot role's server-level allow).
    # Connect matters for voice channels: Discord won't let a bot edit (e.g.
    # rename a live stat channel) a voice channel it isn't allowed to join.
    return discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                       read_message_history=True, manage_channels=True,
                                       connect=True)


@dataclass
class PermissionContext:
    guild: discord.Guild
    staff: discord.Role | None
    muted: discord.Role | None
    ticket_role: discord.Role | None
    gate: discord.Role | None = None  # verification: the role that unlocks gated channels


Overwrites = dict[discord.Role | discord.Member, discord.PermissionOverwrite]


def overwrites_for(preset: str, ctx: PermissionContext, *, gated: bool = False) -> Overwrites:
    everyone = ctx.guild.default_role
    ow: Overwrites = {}

    if preset == "public":
        pass
    elif preset == "announcement":
        ow[everyone] = discord.PermissionOverwrite(
            send_messages=False, create_public_threads=False, create_private_threads=False)
        if ctx.staff:
            ow[ctx.staff] = discord.PermissionOverwrite(send_messages=True)
        ow[ctx.guild.me] = _bot_overwrite()
    elif preset == "readonly":
        ow[everyone] = discord.PermissionOverwrite(
            send_messages=False, add_reactions=False, create_public_threads=False,
            create_private_threads=False, send_messages_in_threads=False)
        if ctx.staff:
            ow[ctx.staff] = discord.PermissionOverwrite(send_messages=True)
        ow[ctx.guild.me] = _bot_overwrite()
    elif preset == "staff_only":
        ow[everyone] = discord.PermissionOverwrite(view_channel=False)
        if ctx.staff:
            ow[ctx.staff] = discord.PermissionOverwrite(view_channel=True)
        ow[ctx.guild.me] = _bot_overwrite()
    elif preset == "tickets":
        ow[everyone] = discord.PermissionOverwrite(view_channel=False)
        if ctx.ticket_role:
            ow[ctx.ticket_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True)
        ow[ctx.guild.me] = _bot_overwrite()
    elif preset == "locked":
        ow[everyone] = discord.PermissionOverwrite(connect=False)
        ow[ctx.guild.me] = _bot_overwrite()
    else:
        raise ValueError(f"Unknown permission preset {preset!r}")

    if gated and ctx.gate is not None and preset in GATEABLE_PRESETS:
        # Only view_channel is allowed for the gate role, never send_messages,
        # so the Muted role's send deny still wins (see muted_overwrite).
        for target, view in ((everyone, False), (ctx.gate, True), (ctx.staff, True)):
            if target is not None:
                current = ow.get(target) or discord.PermissionOverwrite()
                current.view_channel = view
                ow[target] = current
        ow[ctx.guild.me] = _bot_overwrite()

    # Added last so that it doesn't replace another overwrite if Muted somehow equals another key.
    if ctx.muted and ctx.muted not in ow:
        ow[ctx.muted] = muted_overwrite()
    return ow


def is_safe_self_assign_role(role: discord.Role) -> bool:
    """Never let members self-assign a role that carries moderation/admin power."""
    if role.is_default() or role.managed:
        return False
    return (role.permissions.value & discord.Permissions.elevated().value) == 0


def can_hand_out(actor: discord.Member, role: discord.Role) -> bool:
    """Could ``actor`` assign this role themselves? (owner, or Manage Roles and above it)

    Used before turning an *existing* role into a self-assign role: otherwise
    the wizard would let every member grab a role (e.g. a "Verified" access
    role) that even the admin running /setup isn't allowed to give out.
    """
    if actor.guild.owner_id == actor.id:
        return True
    return actor.guild_permissions.manage_roles and role < actor.top_role


def grantable_by(actor: discord.Member | None, wanted: discord.Permissions) -> discord.Permissions:
    """Permissions ``actor`` may put on a new role: Discord itself only lets you
    grant permissions you hold, and the bot must not be a way around that."""
    if actor is None:
        return discord.Permissions.none()
    if actor.guild.owner_id == actor.id or actor.guild_permissions.administrator:
        return wanted
    return discord.Permissions(wanted.value & actor.guild_permissions.value)


def is_access_role(role: discord.Role) -> bool:
    """True if any channel overwrite *allows* something for this role, i.e. the
    role unlocks channels (staff, ticket, "Verified"-style roles)."""
    return any(allow.value for ch in role.guild.channels
               if (ow := ch.overwrites.get(role)) is not None
               for allow, _deny in [ow.pair()])
