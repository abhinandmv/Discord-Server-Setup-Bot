"""Turn wizard answers + templates into a concrete, previewable build plan."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

import discord

import templates

MAX_EXTRA_CHANNELS = 10
MAX_SUBJECTS = 20
MAX_SELF_ROLES = 20  # reaction roles per setup (a message holds at most 20 reactions)
MAX_ROLE_GROUPS = 5  # one reaction-roles message per group
DEFAULT_ROLE_GROUP = "Roles"


@dataclass
class RoleGroup:
    """One reaction-roles message."""
    name: str
    roles: list[str] = field(default_factory=list)
    exclusive: bool = False  # members may pick only one role from this group


@dataclass
class WizardAnswers:
    server_type: str | None = None
    features: list[str] = field(default_factory=list)
    staff_role: str = ""
    member_role: str = ""
    extra_channels: list[str] = field(default_factory=list)
    ticket_role: str | None = None  # "plan:<role key>" or "id:<existing role id>"
    subjects: list[str] = field(default_factory=list)
    reaction_roles: list[RoleGroup] = field(default_factory=list)


@dataclass
class RoleSpec:
    key: str  # staff | member | muted | extra:<name> | self:<name>
    name: str
    color: int = 0
    hoist: bool = False
    mentionable: bool = False
    permissions: tuple[str, ...] = ()
    self_assign: bool = False
    group: str | None = None  # reaction-role message (group) this role belongs to
    reaction: bool = False  # self-assigned by reacting in the reaction-roles channel
    level: int | None = None  # leveling reward
    existing_id: int | None = None  # set by find_conflicts()


@dataclass
class ChannelSpec:
    name: str
    kind: str  # text | voice
    preset: str | None = None  # None = inherit from category
    topic: str | None = None
    special: str | None = None
    gated: bool = False  # hidden until verified
    existing_id: int | None = None

    @property
    def display(self) -> str:
        return f"#{self.name}" if self.kind == "text" else f"🔊 {self.name}"


@dataclass
class CategorySpec:
    key: str
    name: str
    preset: str
    channels: list[ChannelSpec] = field(default_factory=list)
    existing_id: int | None = None

    @property
    def gated(self) -> bool:
        # A category stays visible if anything in it is, e.g. rules next to announcements.
        return bool(self.channels) and all(ch.gated for ch in self.channels)


@dataclass
class Plan:
    server_type: str
    features: list[str]
    roles: list[RoleSpec] = field(default_factory=list)
    categories: list[CategorySpec] = field(default_factory=list)
    ticket_role: str | None = None
    ticket_category_name: str = ""
    create_duplicates: bool = False
    wipe: bool = False  # delete every existing channel/category first
    reaction_groups: list[RoleGroup] = field(default_factory=list)  # one message each

    def role(self, key: str) -> RoleSpec | None:
        return next((r for r in self.roles if r.key == key), None)

    def channels(self) -> list[tuple[CategorySpec, ChannelSpec]]:
        return [(cat, ch) for cat in self.categories for ch in cat.channels]

    def reuses(self, spec: RoleSpec | CategorySpec | ChannelSpec) -> bool:
        """True if this item already exists and the admin chose to skip duplicates."""
        return spec.existing_id is not None and not self.create_duplicates

    def conflicts(self) -> list[str]:
        out = [f"Role @{r.name}" for r in self.roles if r.existing_id]
        out += [f"Category {c.name}" for c in self.categories if c.existing_id]
        out += [ch.display for _, ch in self.channels() if ch.existing_id]
        return out

    def new_counts(self) -> tuple[int, int, int]:
        roles = sum(not self.reuses(r) for r in self.roles)
        cats = sum(not self.reuses(c) for c in self.categories)
        chans = sum(not self.reuses(ch) for _, ch in self.channels())
        return roles, cats, chans


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def parse_list(raw: str) -> list[str]:
    """'Math, physics\\nmath , Art' -> ['Math', 'physics', 'Art'] (deduped, order kept)."""
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[,\n]", raw or ""):
        item = part.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item[:100])
    return out


_ASCII_PUNCT = re.compile("[" + re.escape(string.punctuation.replace("-", "").replace("_", "")) + "]")


_PICK_ONE = re.compile(r"\s*\(\s*pick\s+one\s*\)\s*$", re.IGNORECASE)


def parse_role_groups(raw: str) -> list[RoleGroup]:
    """Parse the reaction roles box.

    One group per line, "Group name: role, role". Add "(pick one)" after the
    group name to allow only one role from it. Lines without a group name go
    into DEFAULT_ROLE_GROUP, so a plain "PC, Console" list still works.
    Role names are deduplicated across groups and capped at MAX_SELF_ROLES.
    """
    groups: dict[str, RoleGroup] = {}
    seen: set[str] = set()
    total = 0
    for line in (raw or "").splitlines():
        head, sep, rest = line.partition(":")
        if not sep or "," in head or not head.strip():
            head, rest = DEFAULT_ROLE_GROUP, line
        exclusive = bool(_PICK_ONE.search(head))
        name = _PICK_ONE.sub("", head).strip()[:80] or DEFAULT_ROLE_GROUP
        key = name.lower()
        if key not in groups:
            if len(groups) >= MAX_ROLE_GROUPS:
                key = next(reversed(groups))  # overflow joins the last group
            else:
                groups[key] = RoleGroup(name, exclusive=exclusive)
        group = groups[key]
        group.exclusive = group.exclusive or exclusive
        for role in parse_list(rest):
            if role.lower() in seen or total >= MAX_SELF_ROLES:
                continue
            seen.add(role.lower())
            group.roles.append(role)
            total += 1
    return [g for g in groups.values() if g.roles]


def format_role_groups(groups: list[RoleGroup]) -> str:
    """Inverse of parse_role_groups, used to pre-fill the wizard's text box."""
    return "\n".join(f"{g.name}{' (pick one)' if g.exclusive else ''}: {', '.join(g.roles)}"
                     for g in groups)


def text_channel_name(raw: str) -> str:
    """Normalise like Discord: lowercase, spaces -> dashes, no ASCII punctuation.

    Emoji and decorative characters such as '┃' are kept.
    """
    name = re.sub(r"\s+", "-", raw.strip().lower())
    name = _ASCII_PUNCT.sub("", name)
    return re.sub(r"-{2,}", "-", name).strip("-")[:100]


def split_leading_emoji(name: str) -> tuple[str | None, str]:
    """'🔥 Fire Mage' -> ('🔥', 'Fire Mage'); 'Fire Mage' -> (None, 'Fire Mage').

    Only symbols from the emoji ranges count, so '* PC' or '-> PC' don't.
    """
    match = re.match(r"^\s*(\S+)\s+(.+)$", name)
    if match:
        token = match.group(1)
        if all(ord(c) >= 0x2300 or c in "‍️" for c in token):
            return token, match.group(2).strip()
    return None, name.strip()


def followups_for(a: WizardAnswers) -> list[str]:
    """Follow-up questions needed for these answers, in a stable order."""
    if not a.server_type:
        return []
    steps = list(templates.SERVER_TYPES[a.server_type].get("followups", []))
    for key, feat in templates.FEATURES.items():
        if key in a.features:
            steps += feat.get("followups", [])
    return list(dict.fromkeys(steps))


def styled_channel_name(d: dict, renames: dict[str, tuple[str, str]]) -> str:
    emoji, base = d.get("emoji"), d["name"]
    if base in renames:
        emoji, base = renames[base]
    if d["type"] == "text":
        return text_channel_name(f"{emoji}{templates.SEP}{base}" if emoji else base)
    return (f"{emoji} {base}" if emoji else base).strip()[:100]


# --------------------------------------------------------------------------- #
# Plan building
# --------------------------------------------------------------------------- #
def build_plan(a: WizardAnswers) -> Plan:
    t = templates.SERVER_TYPES[a.server_type]
    steps = followups_for(a)
    category_names = t.get("category_names", {})
    plan = Plan(
        server_type=a.server_type,
        features=[f for f in templates.FEATURES if f in a.features],
        ticket_role=(a.ticket_role or "plan:staff") if "ticket_role" in steps else None,
        ticket_category_name=category_names.get(
            templates.TICKET_CATEGORY, templates.CATEGORIES[templates.TICKET_CATEGORY]["name"]),
    )

    # Roles, in member-list order (top first). Earlier entries win on name
    # clashes, so a self-assign role can never shadow the staff or Muted role.
    seen_roles: set[str] = set()

    def add_role(key: str, name: str, style: dict, self_assign: bool = False) -> None:
        name = name.strip()[:100]
        if not name or name.lower() in seen_roles or name.lower().lstrip("@") == "everyone":
            return
        seen_roles.add(name.lower())
        plan.roles.append(RoleSpec(
            key=key, name=name, color=style.get("color", 0), hoist=style.get("hoist", False),
            mentionable=style.get("mentionable", False),
            permissions=tuple(style.get("permissions", ())), self_assign=self_assign,
        ))

    defaults = templates.DEFAULT_ROLES
    staff_style = {**defaults["staff"], **({"color": t["staff_color"]} if "staff_color" in t else {})}
    member_style = {**defaults["member"], **({"color": t["member_color"]} if "member_color" in t else {})}
    extras = t.get("roles", [])

    # Staff and member are added first so a cosmetic rank can't take their names,
    # then everything is reordered for display.
    add_role("staff", a.staff_role or t["staff_role"], staff_style)
    add_role("member", a.member_role or t["member_role"], member_style)
    add_role("muted", defaults["muted"]["name"], defaults["muted"])
    leveling = "leveling" in a.features
    for extra in extras:
        add_role(f"extra:{extra['name'].lower()}", extra["name"], extra)
        if leveling and extra.get("level") and plan.roles[-1].key == f"extra:{extra['name'].lower()}":
            plan.roles[-1].level = extra["level"]
    if "reaction_roles" in steps:
        for group in a.reaction_roles:
            kept = RoleGroup(group.name, exclusive=group.exclusive)
            for name in group.roles:
                style = dict(defaults.get("self_assign", {}))
                emoji, _ = split_leading_emoji(name)
                if "colo" in group.name.lower() and emoji in templates.EMOJI_COLORS:
                    style["color"] = templates.EMOJI_COLORS[emoji]
                before = len(plan.roles)
                add_role(f"react:{name.lower()}", name, style, self_assign=True)
                if len(plan.roles) > before:  # skipped if the name is already taken
                    plan.roles[-1].group = group.name
                    plan.roles[-1].reaction = True
                    kept.roles.append(plan.roles[-1].name)
            if kept.roles:
                plan.reaction_groups.append(kept)

    above = {f"extra:{e['name'].lower()}" for e in extras if e.get("above_staff")}

    def rank(r: RoleSpec) -> int:
        if r.key in above:
            return 0
        return {"staff": 1, "muted": 2}.get(r.key, 4 if r.key == "member" else 5 if r.self_assign else 3)

    plan.roles.sort(key=rank)  # stable: keeps template order within each rank
    has_reaction_roles = any(r.reaction for r in plan.roles)

    # Channels, gathered from every source, then grouped by category.
    renames = t.get("renames", {})
    defs: list[dict] = list(templates.BASE_CHANNELS) + list(t.get("channels", []))
    for key, feat in templates.FEATURES.items():
        if key in a.features:
            defs += feat.get("channels", [])
    for name in a.extra_channels[:MAX_EXTRA_CHANNELS]:
        emoji, rest = split_leading_emoji(name)
        defs.append(templates.text(rest, templates.EXTRA_CHANNEL_CATEGORY,
                                   emoji=emoji or templates.DEFAULT_EXTRA_EMOJI))
    if "subjects" in steps:
        for subject in a.subjects[:MAX_SUBJECTS]:
            emoji, rest = split_leading_emoji(subject)
            defs.append(templates.text(rest, templates.SUBJECT_CATEGORY,
                                       emoji=emoji or templates.DEFAULT_SUBJECT_EMOJI,
                                       topic=f"Discussion and help for {rest}."))

    gate = "verification" in a.features
    by_category: dict[str, list[ChannelSpec]] = {key: [] for key in templates.CATEGORIES}
    seen_channels: set[tuple[str, str]] = set()
    for d in defs:
        if d.get("special") == "reaction_menu" and not has_reaction_roles:
            continue
        name = styled_channel_name(d, renames)
        ident = (d["type"], name.lower())
        if not name or ident in seen_channels:
            continue
        seen_channels.add(ident)
        by_category[d["category"]].append(ChannelSpec(
            name=name, kind=d["type"], preset=d.get("preset"),
            topic=d.get("topic"), special=d.get("special"),
            gated=gate and not d.get("ungated"),
        ))

    for key, cat in templates.CATEGORIES.items():
        if by_category[key]:
            plan.categories.append(CategorySpec(key, category_names.get(key, cat["name"]),
                                                cat["preset"], by_category[key]))
    return plan


def find_conflicts(guild: discord.Guild, plan: Plan, *, ignore_ids: set[int] = frozenset()) -> None:
    """Mark plan items whose name already exists in the guild (sets existing_id).

    With plan.wipe, channels and categories are about to be deleted, so only
    roles can conflict. ``ignore_ids`` are items that will be deleted first.
    """
    roles = {r.name.lower(): r.id for r in guild.roles
             if not r.is_default() and not r.managed and r.id not in ignore_ids}
    for role in plan.roles:
        role.existing_id = roles.get(role.name.lower())

    if plan.wipe:
        categories: dict[str, int] = {}
        text_channels: dict[str, int] = {}
        voice_channels: dict[str, int] = {}
    else:
        categories = {c.name.lower(): c.id for c in guild.categories}
        text_channels = {c.name.lower(): c.id for c in guild.text_channels}
        voice_channels = {c.name.lower(): c.id for c in guild.voice_channels}
    for cat in plan.categories:
        cat.existing_id = categories.get(cat.name.lower())
        for ch in cat.channels:
            lookup = text_channels if ch.kind == "text" else voice_channels
            ch.existing_id = lookup.get(ch.name.lower())
