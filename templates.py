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
    locked        visible, but nobody can join (live stat voice channels)

With the "verification" feature, every channel that isn't marked
ungated=True is also hidden from @everyone and shown only to the member role,
which members get by clicking the verify button.

Follow-up questions (implemented in cogs/wizard.py), triggered by a server
type or feature listing them under "followups":
    ticket_role   which role can see and close support tickets
    subjects      subject names -> one text channel each in SUBJECT_CATEGORY
    reaction_roles  grouped role names -> one emoji-reaction message per group
                  in the channel marked special="reaction_menu"

Special channels (the bot posts in or updates them):
    reaction_menu reaction-role messages (react to get a role)
    ticket_panel  "Open a ticket" button
    verify        "I've read the rules" button (verification feature)
    welcome       greets new members
    rules         linked from the verify panel
    level_up      level-up announcements
    mod_log       moderation, ticket and join/leave log
    stat_members  voice channel renamed to show the member count
    stat_boosts   voice channel renamed to show the boost count

Each server type has a "rules" entry: a themed title and (emoji, rule, details)
tuples, posted as an embed in the rules channel when the rules feature is on.

Role entries: {"name", "color", "hoist", "above_staff", "level"}. With the
leveling feature, a role with "level": N is given to members reaching level N. Roles are created in
list order and Discord stacks each new role below the previous ones, so the
order here is the order shown in the member list. "above_staff" puts a
cosmetic rank (e.g. King/Queen) above the staff role.
"""

from __future__ import annotations

PRESETS = {"public", "announcement", "readonly", "staff_only", "tickets", "locked"}
FOLLOWUPS = {"ticket_role", "subjects", "reaction_roles"}
SPECIALS = {"reaction_menu", "ticket_panel", "verify", "welcome", "rules", "mod_log", "level_up",
            "stat_members", "stat_boosts"}

SEP = "┃"                      # between emoji and name in text channels
DEFAULT_EXTRA_EMOJI = "✨"      # for extra channels typed into the wizard
DEFAULT_SUBJECT_EMOJI = "📘"    # for study subjects
TICKET_CHANNEL_EMOJI = "🎫"

# Reaction emoji for self-assign roles whose name doesn't start with an emoji.
REACTION_PALETTE = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫", "⚪", "🔶",
                    "🔷", "💠", "🌟", "🍀", "🔥", "💧", "⚡", "🌙", "🎈", "🎯"]

# Self-assign roles in a group whose name mentions "color" get the colour of
# their leading emoji, e.g. "Name color (pick one): 🔴 Red, 🔵 Blue".
EMOJI_COLORS = {"🔴": 0xE74C3C, "🟠": 0xE67E22, "🟡": 0xF1C40F, "🟢": 0x2ECC71, "🔵": 0x3498DB,
                "🟣": 0x9B59B6, "🟤": 0x8B5A2B, "⚫": 0x23272A, "⚪": 0xFFFFFF, "🩷": 0xFF9FF3}

# Leveling: XP per message (random in this range), at most once per cooldown.
XP_PER_MESSAGE = (15, 25)
XP_COOLDOWN_SECONDS = 60


def text(name: str, category: str, preset: str | None = None, *, emoji: str | None = None,
         topic: str | None = None, special: str | None = None, ungated: bool = False) -> dict:
    """A text channel. preset=None means 'inherit the category preset'.

    ungated=True keeps it visible to members who haven't verified yet.
    """
    return {"type": "text", "name": name, "emoji": emoji, "category": category,
            "preset": preset, "topic": topic, "special": special, "ungated": ungated}


def voice(name: str, category: str, preset: str | None = None, *, emoji: str | None = None,
          special: str | None = None) -> dict:
    """A voice channel. preset=None means 'inherit the category preset'."""
    return {"type": "voice", "name": name, "emoji": emoji, "category": category, "preset": preset,
            "special": special}


# --------------------------------------------------------------------------- #
# Categories (created in this order). Server types can rename them.
# --------------------------------------------------------------------------- #
CATEGORIES: dict[str, dict] = {
    "stats":       {"name": "📊 SERVER STATS",  "preset": "locked"},
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
    "work":        {"name": "💼 WORKSPACE",     "preset": "public"},
    "meetings":    {"name": "📞 MEETING ROOMS", "preset": "public"},
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
            {"name": "🔥 Pro Player", "color": 0xE67E22, "hoist": True, "level": 25},
            {"name": "⚔️ Veteran", "color": 0x1ABC9C, "hoist": True, "level": 10},
            {"name": "🎯 Rookie", "color": 0x95A5A6, "level": 3},
            {"name": "📺 Streamer", "color": 0x9146FF, "hoist": True},
        ],
        "rules": {
            "title": "🎮 House Rules of the Lobby",
            "items": [
                ("🤝", "GG, always", "Respect everyone, win or lose. No toxicity, slurs or rage-baiting."),
                ("🚫", "No cheats or exploits", "Don't share hacks, cheats, or account selling."),
                ("📺", "Self-promo in its place", "Streams and clips go in their channels. No DM ads."),
                ("🎙️", "Keep comms clean", "No mic spam, soundboards or ear-rape in voice."),
                ("🧭", "Right channel, right post", "LFG posts go in LFG, clips in clips."),
                ("🛡️", "Game Masters have the final say",
                 "Follow staff instructions. Disagree? Open a ticket."),
            ],
        },
        "welcome_message": "🎮 **{user}** just joined the lobby! Grab a controller and say hi.",
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
                             "media_memes", "staff_area", "reaction_roles", "leveling", "server_stats"],
        "default_reaction_roles": "Platform: 🖥️ PC, 🎮 Console, 📱 Mobile\n"
                                  "Favourite games: ⛏️ Minecraft, 🔫 Valorant, 🪂 Fortnite, "
                                  "⚽ EA FC, 🏎️ Racing Games\n"
                                  "Playstyle (pick one): 😎 Casual, 🏆 Competitive\n"
                                  "Pings: 🔔 LFG Pings",
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
            {"name": "🧙 Archmage", "color": 0x9B59B6, "hoist": True, "level": 30},
            {"name": "🐉 Dragon Rider", "color": 0x1ABC9C, "hoist": True, "level": 15},
            {"name": "🏹 Ranger", "color": 0x27AE60, "hoist": True, "level": 5},
        ],
        "rules": {
            "title": "⚖️ The Laws of the Realm",
            "items": [
                ("👑", "Honor thy fellow travelers",
                 "Treat every citizen of the realm with respect. Harassment and hate mean exile."),
                ("🗡️", "No duels outside the arena",
                 "Keep arguments civil. Battles belong in roleplay, not real life."),
                ("🐉", "Guard the dragon's hoard",
                 "No spam, scams or cursed links. NSFW content is banished."),
                ("📜", "Seal thy spoilers", "Wrap anime, manga and lore spoilers in ||spoiler tags||."),
                ("🎭", "Roleplay stays in the Roleplay Realm",
                 "Out-of-character chatter goes to the tavern."),
                ("⚔️", "The Knights' word is law",
                 "Heed the Knights. To appeal, summon the guard with a petition."),
            ],
        },
        "welcome_message": "🚪 A new traveler approaches the castle gates! Welcome to the realm, "
                           "**{user}**.",
        "category_names": {
            "stats": "📊 REALM CENSUS", "info": "🏰 CASTLE GATES", "community": "🍺 THE TAVERN", "events": "🎪 FESTIVALS",
            "voice": "🔥 CAMPFIRES", "support": "📜 HELP DESK", "tickets": "📨 PETITIONS",
            "staff": "🗡️ ROYAL COUNCIL",
        },
        "renames": {
            "general": ("🍺", "tavern-chat"),
            "announcements": ("📯", "royal-decrees"),
            "welcome": ("🚪", "welcome-traveler"),
            "rules": ("⚖️", "kingdom-laws"),
            "reaction-roles": ("🎖️", "choose-your-path"),
            "events": ("🎪", "festivals"),
            "event-chat": ("🍻", "feast-hall"),
            "open-a-ticket": ("📜", "summon-the-guard"),
            "verify": ("🗝️", "enter-the-realm"),
            "staff-chat": ("🗡️", "council-chamber"),
            "mod-log": ("📋", "royal-records"),
            "media": ("🖼️", "gallery"),
            "memes": ("🃏", "jesters-corner"),
            "Lounge": ("🔥", "Campfire"),
            "Chill Zone": ("🌲", "Enchanted Forest"),
            "Music": ("🎻", "Bard's Stage"),
            "Staff Voice": ("👑", "Throne Room"),
            "Event Stage": ("🏟️", "Grand Arena"),
            "level-ups": ("🏆", "hall-of-heroes"),
            "Members": ("🏰", "Citizens"),
            "Boosts": ("💎", "Dragon Hoard"),
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
        "default_features": ["announcements", "rules_welcome", "verification", "events",
                             "voice_hangouts", "media_memes", "support_tickets", "staff_area",
                             "reaction_roles", "leveling", "server_stats"],
        "default_reaction_roles": "Class (pick one): 🔥 Fire Mage, ❄️ Ice Mage, 🌿 Druid, "
                                  "🗡️ Assassin, 🛡️ Paladin\n"
                                  "Allegiance (pick one): 🐲 House of Flame, 🌊 House of Tides, "
                                  "🍃 House of Thorns, 🌙 House of Shadows\n"
                                  "Favourite genre: ⚔️ Shonen, 💕 Romance, 👻 Horror, "
                                  "🍵 Slice of Life\n"
                                  "Pings: 📯 Quest Pings, 🎪 Festival Pings",
    },
    "study": {
        "label": "Study group",
        "emoji": "📚",
        "description": "Subject channels, resources and focus rooms",
        "staff_role": "🎓 Professor", "staff_color": 0x8E44AD,
        "member_role": "📖 Scholar", "member_color": 0x2ECC71,
        "roles": [
            {"name": "🧠 Top Scholar", "color": 0xF39C12, "hoist": True, "level": 25},
            {"name": "📗 Sophomore", "color": 0x27AE60, "level": 10},
            {"name": "🌱 Freshman", "color": 0x95A5A6, "level": 3},
            {"name": "✏️ Note Taker", "color": 0x16A085},
        ],
        "rules": {
            "title": "📘 Library Rules",
            "items": [
                ("🤫", "Respect the study space", "Be kind and patient. Everyone learns at their own pace."),
                ("✍️", "No cheating", "Explain, don't hand out answers to live exams or graded work."),
                ("📎", "Share good resources", "Credit your sources. No pirated textbooks."),
                ("🔕", "Focus rooms are quiet", "Stay muted unless the whole room agrees to talk."),
                ("❓", "Ask smart questions",
                 "Show what you've tried and use the right subject channel."),
                ("🎓", "Professors keep order", "Follow staff instructions."),
            ],
        },
        "welcome_message": "📚 Welcome to class, **{user}**! Grab a seat and open your notes.",
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
        "default_features": ["announcements", "rules_welcome", "events", "staff_area", "reaction_roles",
                             "leveling"],
        "default_reaction_roles": "Level (pick one): 🏫 High School, 🎓 University, 💡 Self-learner\n"
                                  "Study style: 🍅 Pomodoro, 👥 Study Buddies, 🎧 Lo-fi Listener\n"
                                  "Schedule (pick one): 🌙 Night Owl, 🌅 Early Bird\n"
                                  "Pings: 📅 Event Pings",
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
            {"name": "🔥 Superfan", "color": 0xF39C12, "hoist": True, "level": 15},
            {"name": "🌱 Regular Viewer", "color": 0x95A5A6, "level": 3},
        ],
        "rules": {
            "title": "🎬 Community Guidelines",
            "items": [
                ("💬", "Be a great audience",
                 "Feedback is welcome; hate toward the creator or other fans isn't."),
                ("📣", "No self-promo without asking", "Ask the Crew before sharing your own channel."),
                ("🔐", "Respect privacy", "Never share personal info about the creator or anyone else."),
                ("🎨", "Credit the artists", "Always credit fan art that isn't yours."),
                ("🤐", "No leaks", "Don't share unreleased content or spoil a premiere."),
                ("🛠️", "The Crew has the final say", "Follow staff instructions."),
            ],
        },
        "welcome_message": "🎬 **{user}** just joined the audience! Welcome to the community.",
        "category_names": {"info": "📌 START HERE", "staff": "🛠️ CREW ONLY"},
        "channels": [
            text("uploads", "content", "announcement", emoji="🎥", topic="New videos and streams."),
            text("feedback", "content", emoji="💡", topic="Thoughts on recent uploads."),
            text("collabs", "content", emoji="🤝", topic="Collaboration requests and ideas."),
            text("fan-art", "content", emoji="🎨"),
        ],
        "default_features": ["announcements", "rules_welcome", "events", "media_memes",
                             "staff_area", "reaction_roles", "leveling", "server_stats"],
        "default_reaction_roles": "Favourite content: 🎮 Gaming Videos, 🎙️ Podcasts, 📹 Vlogs, "
                                  "🖌️ Art Streams\n"
                                  "I'm a: ✏️ Fan Artist, ✂️ Clipper, 💡 Idea Giver\n"
                                  "Pings: 🔔 Upload Pings, 🔴 Live Pings",
    },
    "hangout": {
        "label": "General hangout",
        "emoji": "💬",
        "description": "A chill community with chat and voice",
        "staff_role": "🌟 Guardian", "staff_color": 0xF1C40F,
        "member_role": "🌸 Resident", "member_color": 0xFF9FF3,
        "roles": [
            {"name": "🏅 Legend", "color": 0xF1C40F, "hoist": True, "level": 30},
            {"name": "💫 Regular", "color": 0x48DBFB, "hoist": True, "level": 10},
            {"name": "🌱 Newbie", "color": 0x95A5A6, "level": 3},
            {"name": "🎉 Party Starter", "color": 0xFF6B6B},
        ],
        "rules": {
            "title": "🌸 House Rules",
            "items": [
                ("💖", "Be kind", "Treat everyone like a friend. No bullying, hate or drama."),
                ("🙅", "No spam", "That includes mass pings, emoji walls and chain messages."),
                ("🔞", "Keep it SFW", "This is a chill place for everyone."),
                ("🛋️", "Use the right room", "Memes in memes, intros in introductions."),
                ("🔒", "Stay safe", "Don't share personal info, and report anything sketchy."),
                ("🌟", "Guardians keep the peace", "Follow their lead. Something wrong? Open a ticket."),
            ],
        },
        "welcome_message": "👋 Hey **{user}**, welcome to the hangout! Pull up a chair.",
        "category_names": {"info": "📌 WELCOME", "community": "💬 HANGOUT"},
        "channels": [
            text("off-topic", "community", emoji="🌀"),
            text("introductions", "community", emoji="👋", topic="Say hi and tell us about yourself!"),
            text("bot-commands", "community", emoji="🤖"),
        ],
        "default_features": ["announcements", "rules_welcome", "voice_hangouts",
                             "media_memes", "reaction_roles", "leveling"],
        "default_reaction_roles": "Name color (pick one): 🔴 Red, 🔵 Blue, 🟢 Green, 🟣 Purple\n"
                                  "Hobbies: 🎵 Music, 📚 Books, 🎬 Movies, 🍳 Cooking, ✈️ Travel, "
                                  "🐾 Pets\n"
                                  "Interests: 🎮 Gamer, 🎨 Artist\n"
                                  "Vibe (pick one): ☀️ Morning Person, 🦉 Late Night Crew\n"
                                  "Pings: 🎉 Event Pings, 📢 Announcement Pings",
    },
    "work": {
        "label": "Work / Team",
        "emoji": "💼",
        "description": "A private workspace for a team, club or project group",
        "staff_role": "🧑‍💼 Manager", "staff_color": 0x2C3E50,
        "member_role": "👔 Team Member", "member_color": 0x3498DB,
        "roles": [
            {"name": "🏛️ Founder", "color": 0xF1C40F, "hoist": True, "above_staff": True},
            {"name": "🧠 Team Lead", "color": 0x8E44AD, "hoist": True},
            {"name": "🏆 MVP", "color": 0xE67E22, "hoist": True, "level": 25},
            {"name": "⭐ Rising Star", "color": 0x1ABC9C, "level": 10},
            {"name": "🌱 New Hire", "color": 0x95A5A6, "level": 3},
            {"name": "🤝 Guest", "color": 0x7F8C8D},
        ],
        "welcome_message": "💼 Welcome aboard, **{user}**! Read the handbook, pick your department "
                           "and say hi to the team.",
        "rules": {
            "title": "📘 Team Handbook",
            "items": [
                ("🤝", "Be professional and respectful",
                 "Assume good intent. Disagree with ideas, not people."),
                ("🔒", "What's said here stays here",
                 "Don't share internal info, screenshots or files outside this server."),
                ("🧵", "Use threads", "Reply in threads to keep channels readable."),
                ("⏰", "Respect working hours",
                 "Set your status role, and save @here for real emergencies."),
                ("📂", "Everything in its place",
                 "Tasks in tasks, files in resources, banter at the watercooler."),
                ("🛠️", "Stuck? Ask the helpdesk", "Open a ticket and a manager will help."),
            ],
        },
        "category_names": {
            "stats": "📊 TEAM STATS", "info": "📌 COMPANY HQ", "community": "☕ BREAK ROOM",
            "events": "📅 CALENDAR", "voice": "🛋️ LOUNGE", "support": "🛠️ IT HELPDESK",
            "tickets": "🎫 OPEN REQUESTS", "staff": "🧑‍💼 LEADERSHIP",
        },
        "renames": {
            "general": ("💬", "team-chat"),
            "announcements": ("📣", "company-news"),
            "welcome": ("👋", "onboarding"),
            "rules": ("📘", "handbook"),
            "verify": ("🔑", "sign-in"),
            "events": ("📅", "calendar"),
            "event-chat": ("🎉", "team-events"),
            "memes": ("😂", "watercooler"),
            "open-a-ticket": ("🛠️", "it-helpdesk"),
            "staff-chat": ("🧑‍💼", "leadership"),
            "mod-log": ("📋", "audit-log"),
            "level-ups": ("🏆", "milestones"),
            "Lounge": ("☕", "Coffee Break"),
            "Event Stage": ("🎤", "All-Hands"),
            "Members": ("👥", "Team"),
        },
        "channels": [
            text("standup", "work", emoji="📋", topic="Daily standup: yesterday, today, blockers."),
            text("tasks", "work", emoji="✅", topic="Track tasks and who's on what."),
            text("projects", "work", emoji="🗂️", topic="One thread per project."),
            text("resources", "work", emoji="📎", topic="Docs, links and files the team needs."),
            text("wins", "work", emoji="🏆", topic="Shout-outs and shipped work."),
            voice("Meeting Room 1", "meetings", emoji="📞"),
            voice("Meeting Room 2", "meetings", emoji="📞"),
            voice("Focus Time", "meetings", emoji="🎧"),
        ],
        "default_features": ["announcements", "rules_welcome", "verification", "events",
                             "voice_hangouts", "media_memes", "support_tickets", "staff_area"],
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
        "description": "Read-only rules channel and a welcome channel that greets newcomers",
        "channels": [
            text("welcome", "info", "readonly", emoji="👋", special="welcome", ungated=True),
            text("rules", "info", "readonly", emoji="📜", special="rules", ungated=True),
        ],
    },
    "verification": {
        "label": "Verification gate",
        "emoji": "✅",
        "description": "New members only see the rules until they click Verify",
        "channels": [
            text("verify", "info", "readonly", emoji="✅", special="verify", ungated=True,
                 topic="Read the rules, then click the button to unlock the server."),
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
            text("mod-log", "staff", emoji="📋", special="mod_log",
                 topic="Moderation actions, tickets, joins and leaves."),
            voice("Staff Voice", "staff", emoji="🔒"),
        ],
    },
    "reaction_roles": {
        "label": "Reaction roles",
        "emoji": "✨",
        "description": "A dedicated channel where members react with emoji to get roles",
        "channels": [
            text("reaction-roles", "info", "readonly", emoji="✨", special="reaction_menu",
                 topic="React to a message below to get that role. Remove your reaction to drop it."),
        ],
        "followups": ["reaction_roles"],
    },
    "leveling": {
        "label": "Leveling",
        "emoji": "⭐",
        "description": "Members earn XP for chatting and unlock themed rank roles",
        "channels": [
            text("level-ups", "community", "readonly", emoji="⭐", special="level_up",
                 topic="Level-up announcements. Use /rank and /leaderboard."),
        ],
    },
    "server_stats": {
        "label": "Live server stats",
        "emoji": "📊",
        "description": "Locked voice channels that show member and boost counts",
        "channels": [
            voice("Members", "stats", emoji="👥", special="stat_members"),
            voice("Boosts", "stats", emoji="💎", special="stat_boosts"),
        ],
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
            if (ch.get("special") or "").startswith("stat_") and ch.get("type") != "voice":
                problems.append(f"{where}: stat channels must be voice channels")
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
        levels = []
        for role in t.get("roles", []):
            if not role.get("name"):
                problems.append(f"server type {key!r}: role without a name")
            if "level" in role:
                if not (isinstance(role["level"], int) and role["level"] > 0):
                    problems.append(f"server type {key!r}: role {role.get('name')!r} level must be "
                                    "a positive integer")
                if role.get("above_staff"):
                    problems.append(f"server type {key!r}: role {role.get('name')!r} can't be both "
                                    "above_staff and a level reward")
                levels.append(role["level"])
        if len(levels) != len(set(levels)):
            problems.append(f"server type {key!r}: two level roles share a level")
        rules = t.get("rules")
        if rules is not None:
            items = rules.get("items", []) if isinstance(rules, dict) else []
            if not isinstance(rules, dict) or not rules.get("title") or not 1 <= len(items) <= 25:
                problems.append(f"server type {key!r}: rules need a title and 1-25 items")
            for item in items:
                if not (isinstance(item, tuple) and len(item) == 3 and len(item[1]) <= 240):
                    problems.append(f"server type {key!r}: each rule must be (emoji, rule, details)")
        if "{user}" not in t.get("welcome_message", "{user}"):
            problems.append(f"server type {key!r}: welcome_message needs a {{user}} placeholder")
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
