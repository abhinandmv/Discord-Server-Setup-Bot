"""Retry helper for Discord API calls made in bulk."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import discord

log = logging.getLogger(__name__)
T = TypeVar("T")


async def call_with_retry(factory: Callable[[], Awaitable[T]], *, delay: float = 0.5,
                          attempts: int = 4) -> T:
    """Await ``factory()``, retrying transient failures, then pause ``delay`` seconds.

    discord.py already sleeps through ordinary 429 responses on its own. This
    catches what gets past that: 5xx errors from Discord, a 429 surfaced as an
    HTTPException, and RateLimited (raised when a wait would exceed
    ``max_ratelimit_timeout``). 403/404 are raised immediately: retrying a
    missing permission or a deleted object can't succeed.

    The trailing pause spreads bulk creation out so we stay well clear of the
    per-guild channel/role creation limits.
    """
    for attempt in range(1, attempts + 1):
        try:
            result = await factory()
        except (discord.Forbidden, discord.NotFound):
            raise
        except discord.RateLimited as exc:
            if attempt == attempts:
                raise
            wait = exc.retry_after
        except discord.HTTPException as exc:
            if attempt == attempts or not (exc.status == 429 or exc.status >= 500):
                raise
            wait = 2.0 ** attempt
        else:
            if delay:
                await asyncio.sleep(delay)
            return result
        log.warning("Discord API call failed (attempt %d/%d); retrying in %.1fs",
                    attempt, attempts, wait)
        await asyncio.sleep(wait)
    raise AssertionError("unreachable")


def describe_error(exc: discord.HTTPException) -> str:
    """Short human-readable reason for an API failure."""
    if isinstance(exc, discord.Forbidden):
        return "missing permissions (check my role is high enough and has the right permissions)"
    if isinstance(exc, discord.NotFound):
        return "it no longer exists"
    return f"Discord error {exc.status}: {exc.text or 'unknown'}"
