"""Giveaways: /giveaway start, entered with a button, winners drawn automatically.

After it ends, the message gets a 🔁 Reroll button: if a winner doesn't claim
their prize, the host (or the server owner) can draw a replacement. Rerolls
never pick someone who already won this giveaway. Everything is stored in the
database, so giveaways end on time and buttons work after a restart.
"""

from __future__ import annotations

import logging
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import ui
from core.modlog import log_event
from core.permissions import is_server_owner, mod_command
from cogs.moderation import human_duration, parse_duration

log = logging.getLogger(__name__)

MAX_GIVEAWAY_SECONDS = 28 * 86400
GOLD = 0xF1C40F


def _entry_button(giveaway_id: int, count: int = 0) -> discord.ui.Button:
    return discord.ui.Button(label=f"Enter ({count})", emoji="🎉", style=discord.ButtonStyle.success,
                             custom_id=f"giveaway:enter:{giveaway_id}")


class EnterButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"giveaway:enter:(?P<id>[0-9]+)"):
    def __init__(self, giveaway_id: int, count: int = 0) -> None:
        super().__init__(_entry_button(giveaway_id, count))
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> EnterButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.client.get_cog("Giveaways").toggle_entry(interaction, self.giveaway_id)


class RerollButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"giveaway:reroll:(?P<id>[0-9]+)"):
    def __init__(self, giveaway_id: int) -> None:
        super().__init__(discord.ui.Button(label="Reroll", emoji="🔁",
                                           style=discord.ButtonStyle.secondary,
                                           custom_id=f"giveaway:reroll:{giveaway_id}"))
        self.giveaway_id = giveaway_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> RerollButton:
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.client.get_cog("Giveaways").reroll(interaction, self.giveaway_id)


def giveaway_embed(row, *, entries: int, winners: list[int] | None = None) -> discord.Embed:
    ended = winners is not None
    lines = [f"**Prize:** {row['prize']}",
             f"**Hosted by:** <@{row['host_id']}>",
             f"**Winners:** {row['winners']}"]
    if ended:
        lines.append(f"**Ended** {discord.utils.format_dt(discord.utils.utcnow(), 'R')}")
        lines.append("🏆 " + (", ".join(f"<@{w}>" for w in winners) if winners else
                              "No valid entries, so nobody won."))
    else:
        ends = int(row["ends_at"])
        lines.append(f"**Ends** <t:{ends}:R> (<t:{ends}:f>)")
        lines.append("\nClick **🎉 Enter** to join. Click again to leave.")
    embed = discord.Embed(title=("🎉 GIVEAWAY ENDED" if ended else "🎉 GIVEAWAY"),
                          description="\n".join(lines), colour=ui.GREEN if ended else GOLD)
    embed.set_footer(text=f"Giveaway #{row['id']} · {entries} entr{'y' if entries == 1 else 'ies'}")
    return embed


class Giveaways(commands.Cog):
    giveaway = app_commands.Group(name="giveaway", description="Run giveaways", guild_only=True,
                                  default_permissions=discord.Permissions(moderate_members=True))

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(EnterButton, RerollButton)
        self.end_due.start()

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(EnterButton, RerollButton)
        self.end_due.cancel()

    # ------------------------------------------------------------------ #
    @giveaway.command(name="start", description="Start a giveaway in this channel")
    @mod_command("giveaway")
    @app_commands.describe(prize="What the winner gets", duration="How long it runs, e.g. 1h, 2d",
                           winners="How many winners (1-20)")
    async def start(self, interaction: discord.Interaction, prize: app_commands.Range[str, 1, 200],
                    duration: str, winners: app_commands.Range[int, 1, 20] = 1) -> None:
        seconds = parse_duration(duration)
        if seconds is None or not 60 <= seconds <= MAX_GIVEAWAY_SECONDS:
            await interaction.response.send_message(
                "Use a duration like `30m`, `12h` or `3d` (1 minute to 28 days).", ephemeral=True)
            return
        channel = interaction.channel
        if not channel.permissions_for(interaction.user).send_messages:
            await interaction.response.send_message("You can't post in this channel.", ephemeral=True)
            return
        storage = self.bot.storage
        gid = storage.add_giveaway(interaction.guild.id, channel.id, interaction.user.id, prize,
                                   winners, time.time() + seconds)
        row = storage.giveaway(gid)
        view = discord.ui.View(timeout=None)
        view.add_item(EnterButton(gid))
        await interaction.response.send_message(embed=giveaway_embed(row, entries=0), view=view)
        message = await interaction.original_response()
        storage.set_giveaway_message(gid, message.id)
        await log_event(self.bot, interaction.guild, "🎉 Giveaway started",
                        f"**{prize}** in {channel.mention} by {interaction.user.mention}, "
                        f"ends in {human_duration(seconds)}")

    @giveaway.command(name="end", description="End a giveaway now and draw the winners")
    @mod_command("giveaway")
    @app_commands.describe(giveaway_id="The number in the giveaway's footer (#12)")
    async def end(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        row = self.bot.storage.giveaway(giveaway_id)
        if row is None or row["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("No giveaway with that number here.", ephemeral=True)
            return
        if not self._may_manage(interaction.user, interaction.guild, row):
            await interaction.response.send_message("Only the host or the server owner can do that.",
                                                    ephemeral=True)
            return
        if row["ended"]:
            await interaction.response.send_message("That giveaway already ended.", ephemeral=True)
            return
        await interaction.response.send_message("Ending it now…", ephemeral=True)
        await self.finish(row)

    # ------------------------------------------------------------------ #
    async def toggle_entry(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        storage = self.bot.storage
        row = storage.giveaway(giveaway_id)
        if row is None or row["ended"] or row["ends_at"] <= time.time():
            await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
            return
        if interaction.user.bot:
            return
        entered = storage.toggle_entry(giveaway_id, interaction.user.id)
        count = len(storage.entries(giveaway_id))
        # Update the visible count. Editing the message is the reply, so no extra noise.
        view = discord.ui.View(timeout=None)
        view.add_item(EnterButton(giveaway_id, count))
        await interaction.response.edit_message(embed=giveaway_embed(row, entries=count), view=view)
        await interaction.followup.send("🎉 You're in! Good luck." if entered else
                                        "You left the giveaway.", ephemeral=True)

    @staticmethod
    def _may_manage(user: discord.abc.User, guild: discord.Guild, row) -> bool:
        return user.id == row["host_id"] or is_server_owner(user, guild)

    def _draw(self, guild: discord.Guild, giveaway_id: int, count: int) -> list[int]:
        """Pick up to ``count`` winners still in the server who haven't won this giveaway."""
        pool = [u for u in self.bot.storage.entries(giveaway_id, include_winners=False)
                if guild.get_member(u) is not None]
        picked = random.sample(pool, min(count, len(pool)))
        self.bot.storage.mark_winners(giveaway_id, picked)
        return picked

    async def _message(self, row) -> discord.PartialMessage | None:
        guild = self.bot.get_guild(row["guild_id"])
        channel = guild.get_channel(row["channel_id"]) if guild else None
        if channel is None or row["message_id"] is None:
            return None
        return channel.get_partial_message(row["message_id"])

    async def finish(self, row) -> None:
        storage = self.bot.storage
        if not storage.end_giveaway(row["id"]):
            return  # already ended by someone else
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        winners = self._draw(guild, row["id"], row["winners"])
        message = await self._message(row)
        if message is None:
            return
        view = discord.ui.View(timeout=None)
        view.add_item(RerollButton(row["id"]))
        try:
            await message.edit(embed=giveaway_embed(row, entries=len(storage.entries(row["id"])),
                                                    winners=winners), view=view)
            if winners:
                await message.reply(
                    f"🎉 Congratulations {', '.join(f'<@{w}>' for w in winners)}! You won "
                    f"**{row['prize']}**. Contact <@{row['host_id']}> to claim it.",
                    allowed_mentions=discord.AllowedMentions(users=True))
            else:
                await message.reply("Nobody entered, so there's no winner. 😢")
        except discord.HTTPException as exc:
            log.warning("Couldn't announce giveaway %s: %s", row["id"], exc)
        await log_event(self.bot, guild, "🎉 Giveaway ended",
                        f"**{row['prize']}** · winners: "
                        + (", ".join(f"<@{w}>" for w in winners) or "none"))

    async def reroll(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        row = self.bot.storage.giveaway(giveaway_id)
        if row is None or not row["ended"]:
            await interaction.response.send_message("That giveaway hasn't ended yet.", ephemeral=True)
            return
        if not self._may_manage(interaction.user, interaction.guild, row):
            await interaction.response.send_message(
                "Only the host or the server owner can reroll.", ephemeral=True)
            return
        new = self._draw(interaction.guild, giveaway_id, 1)
        if not new:
            await interaction.response.send_message(
                "There's nobody left to pick: every entrant has already won.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🔁 Rerolled! The new winner of **{row['prize']}** is <@{new[0]}>. Congratulations! 🎉",
            allowed_mentions=discord.AllowedMentions(users=True))
        await log_event(self.bot, interaction.guild, "🔁 Giveaway rerolled",
                        f"**{row['prize']}** · new winner <@{new[0]}> · by {interaction.user.mention}")

    @tasks.loop(seconds=15)
    async def end_due(self) -> None:
        for row in self.bot.storage.due_giveaways(time.time()):
            try:
                await self.finish(row)
            except Exception:
                log.exception("Ending giveaway %s failed", row["id"])

    @end_due.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Giveaways(bot))
