"""Join-to-create voice: joining the "Create a room" channel makes you your own
voice channel (named after the server theme), which is deleted once empty.

The owner of a room can rename it, set a user limit, or kick people from it
(Discord's own channel settings), because they get Manage Channels on it.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

import templates
from core.retry import describe_error

log = logging.getLogger(__name__)


class TempVoice(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _rooms(self, guild: discord.Guild) -> set[int]:
        return set(self.bot.storage.get_json(guild.id, "temp_voice_channels", None) or [])

    def _save_rooms(self, guild: discord.Guild, rooms: set[int]) -> None:
        self.bot.storage.set_json(guild.id, "temp_voice_channels", sorted(rooms))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Rooms that emptied while the bot was offline.
        for guild in self.bot.guilds:
            for channel_id in self._rooms(guild):
                channel = guild.get_channel(channel_id)
                if channel is None or not channel.members:
                    await self._delete_room(guild, channel_id, channel)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        if member.bot or before.channel == after.channel:
            return
        guild = member.guild
        hubs = set(self.bot.storage.get_json(guild.id, "voice_hubs", None) or [])
        if after.channel is not None and after.channel.id in hubs:
            await self._create_room(member, after.channel)
        if before.channel is not None and before.channel.id in self._rooms(guild) \
                and not before.channel.members:
            await self._delete_room(guild, before.channel.id, before.channel)

    async def _create_room(self, member: discord.Member, hub: discord.VoiceChannel) -> None:
        guild = member.guild
        server_type = self.bot.storage.get_setting(guild.id, "server_type")
        pattern = templates.SERVER_TYPES.get(server_type, {}).get("room_name",
                                                                  templates.DEFAULT_ROOM_NAME)
        name = pattern.format(user=member.display_name)[:100]
        # Same permissions as the hub's category, plus room controls for its owner.
        overwrites = dict(hub.category.overwrites if hub.category else hub.overwrites)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True)
        try:
            room = await guild.create_voice_channel(name, category=hub.category,
                                                    overwrites=overwrites,
                                                    reason=f"Join-to-create room for {member}")
        except discord.HTTPException as exc:
            log.warning("Couldn't create a voice room in %s: %s", guild.id, describe_error(exc))
            return
        rooms = self._rooms(guild) | {room.id}
        self._save_rooms(guild, rooms)
        # Tracked so /reset removes rooms that happen to be open.
        self.bot.storage.track(guild.id, room.id, "channel", room.name,
                               hub.category.id if hub.category else None)
        try:
            await member.move_to(room, reason="Join-to-create room")
        except discord.HTTPException:
            await self._delete_room(guild, room.id, room)  # they left before we could move them

    async def _delete_room(self, guild: discord.Guild, channel_id: int,
                           channel: discord.abc.GuildChannel | None) -> None:
        if channel is not None:
            try:
                await channel.delete(reason="Join-to-create room is empty")
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.warning("Couldn't delete empty voice room in %s: %s", guild.id, exc)
                return
        self._save_rooms(guild, self._rooms(guild) - {channel_id})
        self.bot.storage.untrack(guild.id, channel_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVoice(bot))
