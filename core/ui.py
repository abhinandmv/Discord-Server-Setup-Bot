"""Shared embed helpers: colours, clipping, and a throttled progress reporter."""

from __future__ import annotations

import logging
import time

import discord

log = logging.getLogger(__name__)

BLURPLE = 0x5865F2
GREEN = 0x57F287
YELLOW = 0xFEE75C
RED = 0xED4245


def clip(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 2] + " …"


def bullet_list(lines: list[str], limit: int = 1024) -> str:
    """Join lines, replacing whatever doesn't fit with '…and N more'."""
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        remaining = len(lines) - i
        tail = f"\n…and {remaining} more"
        if used + len(line) + 1 + len(tail) > limit:
            out.append(tail.strip())
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out) or "—"


def fit_embed(embed: discord.Embed) -> discord.Embed:
    """Drop trailing fields until the embed is under Discord's 6000-char limit."""
    while len(embed) > 5900 and embed.fields:
        embed.remove_field(len(embed.fields) - 1)
    return embed


def progress_bar(fraction: float, width: int = 20) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "▰" * filled + "▱" * (width - filled)


def progress_embed(title: str, label: str, done: int, total: int,
                   overall_done: int, overall_total: int) -> discord.Embed:
    fraction = overall_done / overall_total if overall_total else 1.0
    return discord.Embed(
        title=title,
        description=(f"**{label}… {done}/{total}**\n"
                     f"{progress_bar(fraction)} {round(fraction * 100)}%\n\n"
                     "-# Items are created one at a time to respect Discord's rate limits."),
        colour=BLURPLE,
    )


class ProgressReporter:
    """Edits an interaction's message with progress, at most every ``interval`` seconds."""

    def __init__(self, interaction: discord.Interaction, title: str, interval: float = 1.5) -> None:
        self.interaction = interaction
        self.title = title
        self.interval = interval
        self._last = 0.0
        self._broken = False

    async def __call__(self, label: str, done: int, total: int,
                       overall_done: int, overall_total: int) -> None:
        now = time.monotonic()
        if done < total and now - self._last < self.interval:
            return
        self._last = now
        await self._edit(progress_embed(self.title, label, done, total, overall_done, overall_total))

    async def finish(self, embed: discord.Embed) -> bool:
        self._broken = False  # always try the final summary
        return await self._edit(embed)

    async def _edit(self, embed: discord.Embed) -> bool:
        """Returns False if the message can't be edited (anymore)."""
        if self._broken:
            return False
        try:
            await self.interaction.edit_original_response(embed=embed, view=None)
            return True
        except discord.HTTPException as exc:
            # The message's channel was deleted by a fresh start, or the 15-minute
            # interaction token expired. The work carries on; we stop retrying.
            log.info("Progress message no longer editable (%s); continuing without it", exc)
            self._broken = True
            return False
