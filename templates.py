"""
Server templates for the setup wizard.

Everything the wizard can build is described here as plain data, so new server
types, features, channels and roles can be added without touching wizard code.

How it fits together
--------------------
* CATEGORIES      - every category the bot may create, in display order, with a
                    permission preset that its channels inherit.
* SERVER_TYPES    - one entry per button in wizard question 1. Each type has its
                    own themed, coloured roles and can rename any channel or
                    category ("renames" / "category_names").
* FEATURES        - one entry per option in the question 2 multi-select.
* text() / voice() describe a channel: a base name, an emoji and which
                    CATEGORIES key it lives in. Text channels are displayed as
                    "<emoji>┃<name>", voice channels as "<emoji> <Name>".

Permission presets (implemented in core/permissions.py):
    public        normal channel
    announcement  everyone can read, only staff can send
    readonly      read-only for everyone (staff can still post)
    staff_only    hidden from everyone except the staff role
    tickets       hidden from everyone except the chosen ticket role

Follow-up questions (implemented in cogs/wizard.py), triggered by a server
type or feature listing them under "followups":
    ticket_role   which role can see and close support tickets
    subjects      subject names -> one text channel each in SUBJECT_CATEGORY
    self_roles    role names -> self-assign menu (buttons + reactions) posted
                  in the channel marked special="role_menu"

Special channels (bot posts an interactive message there):
    role_menu     self-assign role buttons + reaction roles
    ticket_panel  "Open a ticket" button

Role entries: {"name", "color", "hoist", "above_staff"}. Roles are created in
list order and Discord stacks each new role below the previous ones, so the
order here is the order shown in the member list. "above_staff" puts a
cosmetic rank (e.g. King/Queen) above the staff role.
"""

from __future__ import annotations

PRESETS = {"public", "announcement", "readonly", "staff_only", "tickets"}
FOLLOWUPS = {"ticket_role", "subjects", "self_roles"}
SPECIALS = {"role_menu", "ticket_panel"}

SEP = "┃"                      # between emoji and name in text channels
DEFAULT_EXTRA_EMOJI = "✨"      # for extra channels typed into the wizard
DEFAULT_SUBJECT_EMOJI = "📘"    # for study subjects
TICKET_CHANNEL_EMOJI = "🎫"

# Reaction emoji for self-assign roles whose name doesn't start with an emoji.
REACTION_PALETTE = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫", "⚪", "🔶",
                    "🔷", "💠", "🌟", "🍀", "🔥", "💧", "⚡", "🌙", "🎈", "🎯"]


def text(name: str, category: str, preset: str | None = None, *, emoji: str | None = None,
         topic: str | None = None, special: str | None = None) -> dict:
    """A text channel. preset=None means 'inherit the category preset'."""
    return {"type": "text", "name": name, "emoji": emoji, "category": category,
            "preset": preset, "topic": topic, "special": special}


def voice(name: str, category: str, preset: str | None = None, *, emoji: str | None = None) -> dict:
    """A voice channel. preset=None means 'inherit the category preset'."""
    return {"type": "voice", "name": name, "emoji": emoji, "category": category, "preset": preset}


# --------------------------------------------------------------------------- #
# Categories (created in this order). Server types can rename them.
# --------------------------------------------------------------------------- #
CATEGORIES: dict[str, dict] = {
    "info":        {"name": "📌 INFORMATION",   "preset": "public"},
    "community":   {"name": "💬 COMMUNITY",     "preset": "public"},
    "gaming":      {"name": "🎮 GAMING",        "preset": "public"},
    "game_voice":  {"name": "🎧 SQUAD VOICE",   "preset": "public"},
    "lore":        {"name": "📖 THE LIBRARY",   "preset": "public"},
    "anime":       {"name": "🌸 ANIME CORNER",  "preset": "public"},
    "roleplay":    {"name": "🎭 ROLEPLAY REALM", "preset": "public"},
    "study":       {"name": "📚 STUDY HALL",    "preset": "public"},
    "subjects":    {"name": "📘 SUBJECTS",      "preset": "public"},
    "study_rooms": {"name": "🎧 FOCUS ROOMS",   "preset": "public"},
    "content":     {"name": "🎬 CONTENT",       "preset": "public"},
    "events":      {"name": "🎉 EVENTS",        "preset": "public"},
    "voice":       {"name": "🔊 VOICE LOUNGE",  "preset": "public"},
    "support":     {"name": "🆘 SUPPORT",       "preset": "public"},
    "tickets":     {"name": "🎫 OPEN TICKETS",  "preset": "tickets"},
    "staff":       {"name": "🛡️ STAFF ROOM",    "preset": "staff_only"},
}

# Where free-form channels from the wizard go.
EXTRA_CHANNEL_CATEGORY = "community"
SUBJECT_CATEGORY = "subjects"
# Created on demand when the first ticket opens, deleted when the last closes.
TICKET_CATEGORY = "tickets"

# --------------------------------------------------------------------------- #
# Role styles shared by every type. Staff/member names and colours come from
# the server type. Permission names are discord.Permissions attribute names.
# --------------------------------------------------------------------------- #
DEFAULT_ROLES: dict[str, dict] = {
    "staff": {
        "color": 0xE67E22, "hoist": True, "mentionable": True,
        "permissions": ["manage_messages", "moderate_members", "mute_members",
                        "deafen_members", "move_members", "manage_nicknames"],
    },
    "member": {"color": 0x3498DB, "hoist": True},
    "muted": {"name": "🔇 Muted", "color": 0x546E7A},
    "self_assign": {"mentionable": True},
}

# Channels every server gets regardless of type.
BASE_CHANNELS: list[dict] = [
    text("general", "community", emoji="💬", topic="General chat. Be nice!"),
]

# --------------------------------------------------------------------------- #
# Server types (wizard question 1)
# --------------------------------------------------------------------------- #
SERVER_TYPES: dict[str, dict] = {
    "gaming": {
        "label": "Gaming",
        "emoji": "🎮",
        "description": "LFG, clips, tournaments and squad voice",
        "staff_role": "🎮 Game Master", "staff_color": 0xE74C3C,
        "member_role": "🕹️ Player", "member_color": 0x3498DB,
        "roles": [
            {"name": "🏆 Champion", "color": 0xF1C40F, "hoist": True, "above_staff": True},
            {"name": "🔥 Pro Player", "color": 0xE67E22, "hoist": True},
            {"name": "📺 Streamer", "color": 0x9146FF, "hoist": True},
        ],
        "category_names": {"info": "📌 HQ", "community": "💬 LOBBY", "events": "🏆 TOURNAMENTS",
                           "voice": "🔊 HANGOUT", "staff": "🛡️ GAME MASTERS"},
        "renames": {"general": ("💬", "lobby-chat"), "events": ("🏆", "tournaments")},
        "channels": [
            text("lfg", "gaming", emoji="🔍", topic="Looking for group? Post your game, rank and platform."),
            text("clips", "gaming", emoji="🎬", topic="Share your best plays."),
            text("game-chat", "gaming", emoji="🎮"),
            text("achievements", "gaming", emoji="🏅", topic="Brag about your wins."),
            voice("Squad 1", "game_voice", emoji="🎧"),
            voice("Squad 2", "game_voice", emoji="🎧"),
            voice("Duo Queue", "game_voice", emoji="⚔️"),
        ],
        "default_features": ["announcements", "rules_welcome", "events", "voice_hangouts",
                             "media_memes", "staff_area", "self_roles"],
        "default_self_roles": "🖥️ PC, 🎮 Console, 📱 Mobile, 🔔 LFG Pings",
    },
    "fantasy": {
        "label": "Fantasy / Anime",
        "emoji": "🐉",
        "description": "A kingdom with royal ranks, lore, anime and roleplay",
        "staff_role": "⚔️ Knight", "staff_color": 0xC0392B,
        "member_role": "🪓 Viking", "member_color": 0x5DADE2,
        "roles": [
            {"name": "👑 King", "color": 0xF1C40F, "hoist": True, "above_staff": True},
            {"name": "👸 Queen", "color": 0xE91E63, "hoist": True, "above_staff": True},
            {"name": "🧙 Archmage", "color": 0x9B59B6, "hoist": True},
            {"name": "🐉 Dragon Rider", "color": 0x1ABC9C, "hoist": True},
            {"name": "🏹 Ranger", "color": 0x27AE60, "hoist": True},
        ],
        "category_names": {
            "info": "🏰 CASTLE GATES", "community": "🍺 THE TAVERN", "events": "🎪 FESTIVALS",
            "voice": "🔥 CAMPFIRES", "support": "📜 HELP DESK", "tickets": "📨 PETITIONS",
            "staff": "🗡️ ROYAL COUNCIL",
        },
        "renames": {
            "general": ("🍺", "tavern-chat"),
            "announcements": ("📯", "royal-decrees"),
            "welcome": ("🚪", "welcome-traveler"),
            "rules": ("⚖️", "kingdom-laws"),
            "roles": ("🎖️", "choose-your-path"),
            "events": ("🎪", "festivals"),
            "event-chat": ("🍻", "feast-hall"),
            "open-a-ticket": ("📜", "summon-the-guard"),
            "staff-chat": ("🗡️", "council-chamber"),
            "mod-log": ("📋", "royal-records"),
            "media": ("🖼️", "gallery"),
            "memes": ("🃏", "jesters-corner"),
            "Lounge": ("🔥", "Campfire"),
            "Chill Zone": ("🌲", "Enchanted Forest"),
            "Music": ("🎻", "Bard's Stage"),
            "Staff Voice": ("👑", "Throne Room"),
            "Event Stage": ("🏟️", "Grand Arena"),
        },
        "channels": [
            text("lore", "lore", emoji="📜", topic="The history of our realm."),
            text("world-map", "lore", emoji="🗺️"),
            text("character-sheets", "lore", emoji="🧾", topic="Post your character here."),
            text("anime-chat", "anime", emoji="🌸"),
            text("now-watching", "anime", emoji="📺", topic="What are you watching this season?"),
            text("manga", "anime", emoji="📚"),
            text("fan-art", "anime", emoji="🎨"),
            text("roleplay", "roleplay", emoji="🎭"),
            text("quests", "roleplay", emoji="⚔️", topic="Quest boards and adventures."),
            text("arena", "roleplay", emoji="🏟️"),
            voice("Dragon's Lair", "roleplay", emoji="🐉"),
        ],
        "default_features": ["announcements", "rules_welcome", "events", "voice_hangouts",
                             "media_memes", "support_tickets", "staff_area", "self_roles"],
        "default_self_roles": "🔥 Fire Mage, ❄️ Ice Mage, 🌿 Druid, 🗡️ Assassin, 🛡️ Paladin",
    },
    "study": {
        "label": "Study group",
        "emoji": "📚",
        "description": "Subject channels, resources and focus rooms",
        "staff_role": "🎓 Professor", "staff_color": 0x8E44AD,
        "member_role": "📖 Scholar", "member_color": 0x2ECC71,
        "roles": [
            {"name": "🧠 Top Scholar", "color": 0xF39C12, "hoist": True},
            {"name": "✏️ Note Taker", "color": 0x16A085},
        ],
        "category_names": {"info": "🏫 CAMPUS", "community": "☕ COMMON ROOM",
                           "staff": "🎓 FACULTY"},
        "renames": {"general": ("☕", "common-room")},
        "channels": [
            text("study-chat", "study", emoji="📝"),
            text("resources", "study", emoji="📎", topic="Useful links, notes and guides."),
            text("homework-help", "study", emoji="❓"),
            voice("Focus Room 1", "study_rooms", emoji="🔕"),
            voice("Focus Room 2", "study_rooms", emoji="🔕"),
            voice("Group Study", "study_rooms", emoji="👥"),
        ],
        "followups": ["subjects"],
        "default_subjects": "Math, Physics, Chemistry, Biology, Computer Science",
        "default_features": ["announcements", "rules_welcome", "events", "staff_area", "self_roles"],
        "default_self_roles": "📅 Event Pings, 🌙 Night Owl, 🌅 Early Bird",
    },
    "creator": {
        "label": "Creator / YouTube",
        "emoji": "🎬",
        "description": "Uploads, feedback and collabs for your audience",
        "staff_role": "🛠️ Crew", "staff_color": 0xE67E22,
        "member_role": "⭐ Fan", "member_color": 0x3498DB,
        "roles": [
            {"name": "🎬 Creator", "color": 0xFF0000, "hoist": True, "above_staff": True},
            {"name": "💎 Subscriber", "color": 0xE91E63, "hoist": True},
            {"name": "🎨 Artist", "color": 0x9B59B6, "hoist": True},
            {"name": "🤝 Collaborator", "color": 0x1ABC9C},
        ],
        "category_names": {"info": "📌 START HERE", "staff": "🛠️ CREW ONLY"},
        "channels": [
            text("uploads", "content", "announcement", emoji="🎥", topic="New videos and streams."),
            text("feedback", "content", emoji="💡", topic="Thoughts on recent uploads."),
            text("collabs", "content", emoji="🤝", topic="Collaboration requests and ideas."),
            text("fan-art", "content", emoji="🎨"),
        ],
        "default_features": ["announcements", "rules_welcome", "events", "media_memes",
                             "staff_area", "self_roles"],
        "default_self_roles": "🔔 Upload Pings, 🔴 Live Pings",
    },
    "hangout": {
        "label": "General hangout",
        "emoji": "💬",
        "description": "A chill community with chat and voice",
        "staff_role": "🌟 Guardian", "staff_color": 0xF1C40F,
        "member_role": "🌸 Resident", "member_color": 0xFF9FF3,
        "roles": [
            {"name": "💫 Regular", "color": 0x48DBFB, "hoist": True},
            {"name": "🎉 Party Starter", "color": 0xFF6B6B},
        ],
        "category_names": {"info": "📌 WELCOME", "community": "💬 HANGOUT"},
        "channels": [
            text("off-topic", "community", emoji="🌀"),
            text("introductions", "community", emoji="👋", topic="Say hi and tell us about yourself!"),
            text("bot-commands", "community", emoji="🤖"),
        ],
        "default_features": ["announcements", "rules_welcome", "voice_hangouts",
                             "media_memes", "self_roles"],
        "default_self_roles": "🎉 Event Pings, 📢 Announcement Pings, 🎮 Gamer, 🎨 Artist",
    },
}

# --------------------------------------------------------------------------- #
# Features (wizard question 2), in the order shown in the select menu
# --------------------------------------------------------------------------- #
FEATURES: dict[str, dict] = {
    "announcements": {
        "label": "Announcements",
        "emoji": "📢",
        "description": "Staff-only posting channel everyone can read",
        "channels": [text("announcements", "info", "announcement", emoji="📢",
                          topic="Server news.")],
    },
    "rules_welcome": {
        "label": "Rules & welcome",
        "emoji": "📜",
        "description": "Read-only welcome and rules channels",
        "channels": [
            text("welcome", "info", "readonly", emoji="👋"),
            text("rules", "info", "readonly", emoji="📜"),
        ],
    },
    "events": {
        "label": "Events",
        "emoji": "📅",
        "description": "Event announcements, chat and a stage voice channel",
        "channels": [
            text("events", "events", "announcement", emoji="📅", topic="Upcoming events."),
            text("event-chat", "events", emoji="🎉"),
            voice("Event Stage", "events", emoji="🎤"),
        ],
    },
    "voice_hangouts": {
        "label": "Voice hangouts",
        "emoji": "🔊",
        "description": "Casual voice channels",
        "channels": [
            voice("Lounge", "voice", emoji="🛋️"),
            voice("Chill Zone", "voice", emoji="🌙"),
            voice("Music", "voice", emoji="🎵"),
        ],
    },
    "support_tickets": {
        "label": "Support tickets",
        "emoji": "🎫",
        "description": "Members open private tickets; only mods can close them",
        "channels": [
            text("open-a-ticket", "support", "readonly", emoji="🎫", special="ticket_panel",
                 topic="Click the button to open a private ticket with the team."),
        ],
        "followups": ["ticket_role"],
    },
    "media_memes": {
        "label": "Media/memes",
        "emoji": "🖼️",
        "description": "Channels for media and memes",
        "channels": [
            text("media", "community", emoji="📸", topic="Photos, videos and art."),
            text("memes", "community", emoji="😂"),
        ],
    },
    "staff_area": {
        "label": "Staff area",
        "emoji": "🛡️",
        "description": "Private staff category hidden from members",
        "channels": [
            text("staff-chat", "staff", emoji="🛡️"),
            text("mod-log", "staff", emoji="📋"),
            voice("Staff Voice", "staff", emoji="🔒"),
        ],
    },
    "self_roles": {
        "label": "Self-assign roles",
        "emoji": "🏷️",
        "description": "Members pick roles with buttons or emoji reactions",
        "channels": [
            text("roles", "info", "readonly", emoji="🏷️", special="role_menu",
                 topic="Pick your roles with the buttons or reactions below."),
        ],
        "followups": ["self_roles"],
    },
}


# --------------------------------------------------------------------------- #
# Validation: catches typos when you add or edit templates.
# --------------------------------------------------------------------------- #
def validate() -> None:
    """Raise ValueError describing every problem found in the template data."""
    problems: list[str] = []
    base_names: set[str] = {ch["name"] for ch in BASE_CHANNELS}

    def check_channels(owner: str, channels: list[dict]) -> None:
        for ch in channels:
            base_names.add(ch.get("name"))
            where = f"{owner} channel {ch.get('name')!r}"
            if ch.get("type") not in ("text", "voice"):
                problems.append(f"{where}: type must be 'text' or 'voice'")
            if ch.get("category") not in CATEGORIES:
                problems.append(f"{where}: unknown category {ch.get('category')!r}")
            if ch.get("preset") is not None and ch["preset"] not in PRESETS:
                problems.append(f"{where}: unknown preset {ch['preset']!r}")
            if ch.get("special") is not None and ch["special"] not in SPECIALS:
                problems.append(f"{where}: unknown special {ch['special']!r}")

    for key, cat in CATEGORIES.items():
        if cat.get("preset") not in PRESETS:
            problems.append(f"category {key!r}: unknown preset {cat.get('preset')!r}")
    for key in (EXTRA_CHANNEL_CATEGORY, SUBJECT_CATEGORY, TICKET_CATEGORY):
        if key not in CATEGORIES:
            problems.append(f"category {key!r} is referenced but not defined")
    if len(REACTION_PALETTE) < 20:
        problems.append("REACTION_PALETTE needs at least 20 emoji (one per self-assign role)")

    check_channels("base", BASE_CHANNELS)
    for key, feat in FEATURES.items():
        check_channels(f"feature {key!r}", feat.get("channels", []))
        for f in feat.get("followups", []):
            if f not in FOLLOWUPS:
                problems.append(f"feature {key!r}: unknown followup {f!r}")

    for key, t in SERVER_TYPES.items():
        for field in ("label", "description", "staff_role", "member_role", "default_features"):
            if field not in t:
                problems.append(f"server type {key!r}: missing {field!r}")
        check_channels(f"server type {key!r}", t.get("channels", []))
        for feat in t.get("default_features", []):
            if feat not in FEATURES:
                problems.append(f"server type {key!r}: unknown default feature {feat!r}")
        for f in t.get("followups", []):
            if f not in FOLLOWUPS:
                problems.append(f"server type {key!r}: unknown followup {f!r}")
        for role in t.get("roles", []):
            if not role.get("name"):
                problems.append(f"server type {key!r}: role without a name")
        for cat in t.get("category_names", {}):
            if cat not in CATEGORIES:
                problems.append(f"server type {key!r}: category_names has unknown category {cat!r}")

    # Renames are checked last so every channel's base name has been collected.
    for key, t in SERVER_TYPES.items():
        for base, value in t.get("renames", {}).items():
            if base not in base_names:
                problems.append(f"server type {key!r}: rename of unknown channel {base!r}")
            if not (isinstance(value, tuple) and len(value) == 2):
                problems.append(f"server type {key!r}: rename {base!r} must be (emoji, name)")

    if len(SERVER_TYPES) > 20:
        problems.append("at most 20 server types fit on the wizard's buttons")
    if len(FEATURES) > 25:
        problems.append("at most 25 features fit in a select menu")

    if problems:
        raise ValueError("Invalid templates:\n  - " + "\n  - ".join(problems))
