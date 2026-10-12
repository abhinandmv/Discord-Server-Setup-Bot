# 🧙 Discord Server Setup Wizard

A Discord bot that builds a complete, themed server for you, then helps run it. Run `/setup`, answer a few interactive questions (buttons, menus and pop-up forms), and the bot creates styled roles, categories and channels with permissions already set up. It also handles verification, welcome messages, reaction roles, support tickets, leveling, live stats and moderation, and can back up, restore and copy server layouts.

Built with [discord.py](https://github.com/Rapptz/discord.py) 2.x.

---

## ✨ Features

- **Interactive wizard:** server type → features → details → follow-up questions → fresh start or keep existing → preview → build with a live progress bar.
- **6 themed server types**, each with its own coloured roles, emoji channel names, category names, welcome message and **rules**:

  | Type | Roles (top → bottom) | Example channels |
  |---|---|---|
  | Type | Roles (top → bottom) | Level rewards | Example channels |
  |---|---|---|---|
  | 🎮 Gaming | 🏆 Champion, 🎮 Game Master, 📺 Streamer, 🕹️ Player | 🎯 Rookie (3) → ⚔️ Veteran (10) → 🔥 Pro Player (25) | `🔍┃lfg`, `🎬┃clips`, `🎧 Squad 1` |
  | 🐉 Fantasy / Anime | 👑 King, 👸 Queen, ⚔️ Knight, 🪓 Viking | 🏹 Ranger (5) → 🐉 Dragon Rider (15) → 🧙 Archmage (30) | `📯┃royal-decrees`, `🍺┃tavern-chat`, `🗝️┃enter-the-realm` |
  | 📚 Study group | 🎓 Professor, ✏️ Note Taker, 📖 Scholar | 🌱 Freshman (3) → 📗 Sophomore (10) → 🧠 Top Scholar (25) | `📝┃study-chat`, `📘┃math`, `🔕 Focus Room 1` |
  | 🎬 Creator / YouTube | 🎬 Creator, 🛠️ Crew, 💎 Subscriber, 🎨 Artist, ⭐ Fan | 🌱 Regular Viewer (3) → 🔥 Superfan (15) | `🎥┃uploads`, `💡┃feedback`, `🤝┃collabs` |
  | 💬 General hangout | 🌟 Guardian, 🎉 Party Starter, 🌸 Resident | 🌱 Newbie (3) → 💫 Regular (10) → 🏅 Legend (30) | `🌀┃off-topic`, `👋┃introductions` |
  | 💼 Work / Team | 🏛️ Founder, 🧑‍💼 Manager, 🧠 Team Lead, 👔 Team Member, 🤝 Guest | 🌱 New Hire (3) → ⭐ Rising Star (10) → 🏆 MVP (25) | `📋┃standup`, `✅┃tasks`, `📞 Meeting Room 1` |

  Each type also has its own welcome message and rules, posted in the rules channel. For example, Fantasy greets newcomers with *"A new traveler approaches the castle gates!"* and posts **⚖️ The Laws of the Realm**. Work posts a **📘 Team Handbook** and has verification on by default.

- **Permissions handled for you**
  - Announcements: everyone reads, only staff post.
  - Rules and welcome: read-only.
  - Staff area: hidden from everyone except staff.
  - **🔇 Muted** role: can't type, react, use threads or speak anywhere.
- **🎫 Support tickets**
  - Members open a private ticket with a button. Only the member and the mods can see it.
  - **Only mods can close tickets.**
  - The tickets category appears only while a ticket is open.
- **✅ Verification gate:** new members only see the welcome, rules and verify channels until they click **Verify**. Without it, new members get the member role automatically.
- **👋 Welcome messages:** a themed greeting for every new member.
- **✨ Reaction roles:** a dedicated channel with one message per group (e.g. Platform, Pings, Name color), emoji already added. React to get a role, un-react to drop it. "Pick one" groups swap your role when you choose another, and groups with "color" in the name get coloured roles. Every type except Work has its own themed set, e.g. Fantasy's *🎖️┃choose-your-path* has a Class, an Allegiance (🐲 House of Flame, 🌊 House of Tides…), favourite genres and pings.
- **⭐ Leveling:** members earn XP for chatting and unlock the theme's rank roles. `/rank` and `/leaderboard` show progress.
- **📊 Live stats:** locked voice channels showing the member and boost counts, updated every 10 minutes.
- **🛡️ Moderation:** `/mute` (with optional duration), `/unmute`, `/warn`, `/warnings`, `/clearwarnings` and `/purge`. Every action, ticket, join and leave goes to the **mod-log** channel.
- **🧹 Fresh start (optional):** deletes all existing channels and builds from scratch. You must type `DELETE` to confirm.
- **💾 Backups:** the layout is saved automatically before anything deletes channels, and `/restore` brings it back. `/backup` saves one any time.
- **📐 Templates:** save a server's layout and apply it in another server. Export it as a file to share.
- **Safe**
  - Everything the bot creates is tracked in SQLite.
  - `/reset` removes **only** what the bot made.
  - Before building, the bot checks for duplicate names and asks whether to skip or create them anyway.
  - API calls are rate-limited and retried on failure.
  - The bot checks its own permissions first.
  - A wizard times out after 10 minutes of inactivity.
- **Survives restarts:** role menus, verify and ticket buttons, and timed mutes keep working after the bot restarts.
- **Easy to extend:** all server types, features, roles and channels live in [`templates.py`](templates.py).

---

## 🚀 Installation

**First time?** Follow the step-by-step guide in **[setup.md](setup.md)**. It covers the Developer Portal, inviting the bot, `.env` and running it, plus troubleshooting.

Short version:

```bash
git clone https://github.com/abhinandmv/Discord-Server-Setup-Bot.git
cd Discord-Server-Setup-Bot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then fill in DISCORD_TOKEN and TEST_GUILD_ID
python bot.py
```

### Configuration (`.env`)

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Bot token (Developer Portal → Bot → Reset Token) |
| `TEST_GUILD_ID` | – | Your server's ID. Slash commands sync there **instantly**. Leave empty to sync globally (up to 1 hour). |
| `DATABASE_PATH` | – | The SQLite database: created items, settings, backups, templates, XP and warnings (default `data/bot.db`) |

`.env` and `data/` are git-ignored. **Never commit your token.**

### Developer Portal settings

- **Bot** tab: turn **on Server Members Intent**. It's needed for welcome messages, verification, auto-role and the join/leave log, and the bot won't start without it. Presence and Message Content can stay **off**; leveling only counts messages and never reads them. Turn off **Requires OAuth2 Code Grant**.
- **Invite URL** (replace `YOUR_APPLICATION_ID`):

  ```
  https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=1477904034896&scope=bot+applications.commands
  ```

  - **Scopes:** `bot` and `applications.commands`
  - **Permissions:**
    - Manage Channels, Manage Roles, View Channels
    - Send Messages (+ in Threads), Create Public/Private Threads
    - Embed Links, Attach Files, Read Message History, Add Reactions
    - Connect, Speak
    - Manage Messages, Timeout/Mute/Deafen/Move Members, Manage Nicknames (so the staff role can be given these)

> ⚠️ **After inviting**, open Server Settings → Roles and drag the bot's role to the **top**. Discord only lets a bot manage roles below its own.

---

## 📖 Using the bot

### Commands

| Command | Who can use it | What it does |
|---|---|---|
**Admins** (need **Manage Server + Manage Channels + Manage Roles**):

| Command | What it does |
|---|---|
| `/setup` | Runs the setup wizard. Only you can see the wizard messages. |
| `/reset` | Deletes everything the bot created, after you confirm. |
| `/backup` | Saves the current channel layout. The 10 newest backups are kept. |
| `/restore` | Pick a backup and rebuild the channels from it (asks you to type `DELETE`). |
| `/template save` · `list` · `apply` · `delete` | Save this server's layout as your own template and build it in any server. |
| `/template export` · `import` | Download a template as a `.json` file, or add one someone shared with you. |

**Moderators:**

| Command | Needs | What it does |
|---|---|---|
| `/mute @member [duration] [reason]` | Timeout Members | Gives them the Muted role, e.g. `10m`, `2h`, `3d`, or until `/unmute`. Leaving and rejoining doesn't remove it. |
| `/unmute @member` | Timeout Members | Removes the mute. |
| `/warn @member reason` | Timeout Members | Records a warning and DMs them. |
| `/warnings @member` · `/clearwarnings @member` | Timeout Members | Shows or clears their warnings. |
| `/purge amount [@member]` | Manage Messages | Deletes up to 100 recent messages here, optionally only from one member. |

Mods can't target the server owner, bots, themselves, or anyone whose highest role is equal to or above theirs.

**Everyone:**

| Command | What it does |
|---|---|
| `/rank [@member]` | Shows level, XP progress, rank and the next reward. |
| `/leaderboard` | The top 10 most active members. |

### For admins: setting up your server

1. **Type `/setup`** in any channel and press Enter.
2. **Pick a server type** (Gaming, Fantasy / Anime, Study group, Creator / YouTube, General hangout or Work / Team). This decides the role names, colours and channel theme.
3. **Choose features** from the menu. With **Rules & welcome**, the theme's rules are posted in the rules channel for you. Sensible defaults are pre-selected; tick or untick what you want, then press **Next**:

   | Feature | What you get |
   |---|---|
   | 📢 Announcements | A channel only staff can post in |
   | 📜 Rules & welcome | Read-only rules channel and a welcome channel that greets newcomers |
   | ✅ Verification gate | A verify button; everything else stays hidden until members click it |
   | 📅 Events | Events channel, event chat and a stage voice channel |
   | 🔊 Voice hangouts | Casual voice channels |
   | 🎫 Support tickets | A button members click to open private tickets |
   | 🖼️ Media/memes | Media and memes channels |
   | 🛡️ Staff area | A private category only staff can see |
   | ✨ Reaction roles | A dedicated channel where members react with emoji to get roles |
   | ⭐ Leveling | XP for chatting, a level-ups channel and themed rank rewards |
   | 📊 Live server stats | Locked voice channels showing member and boost counts |

4. **Fill in the details form.** The staff and member role names are pre-filled with the theme (e.g. `⚔️ Knight` / `🪓 Viking`). Change them if you like. You can also add extra channels, comma-separated (e.g. `art, 🎲 board games`).
5. **Answer the follow-up questions.** They only appear when relevant:
   - **Support tickets:** which role can see and close tickets (usually your staff role).
   - **Study group:** your subjects. Each one becomes a channel.
   - **Reaction roles:** one group per line, e.g.

     ```
     Platform: 🖥️ PC, 🎮 Console
     Name color (pick one): 🔴 Red, 🔵 Blue, 🟢 Green
     ```

     Each group becomes its own message in the reaction-roles channel (up to 5 groups, 20 roles in total). Start each role name with the emoji to react with; otherwise the bot picks one. **(pick one)** allows only one role from that group. In a group with "color" in the name, 🔴 🟠 🟡 🟢 🔵 🟣 🟤 ⚫ ⚪ also set the role's colour.
6. **Choose how to build:**
   - **🧹 Fresh start:** deletes **all** existing channels and categories (and roles the bot made earlier), then builds everything new. Your other roles are kept. The old layout is **backed up first**, so `/restore` can bring the channels back, but their **messages are gone for good**.
   - **➕ Keep existing:** leaves your current channels alone and adds the new ones. If something with the same name already exists, you choose to **skip** it (reuse it) or **create it anyway**.
7. **Review the preview.** It lists every role, category and channel. Press **✅ Confirm & build**, **✏️ Edit** to start over (your answers are remembered), or **Cancel** (nothing is created).
   - For a fresh start you'll be asked to **type `DELETE`** to confirm.
8. **Watch it build.** A progress bar shows each step. With a fresh start, the summary is posted in your new staff channel, because the channel you ran `/setup` in has been deleted.

### After setup: what to do next

- **Give your moderators the staff role** (e.g. ⚔️ Knight, 🎮 Game Master). It has moderation powers: delete messages, time out, mute/move in voice, change nicknames.
- **Hand out the cosmetic ranks yourself** (e.g. 👑 King, 👸 Queen, 🏆 Champion). They're displayed separately and coloured but carry no extra permissions.
- **Check the rules.** The bot posts a themed set. Edit them in `templates.py` (`"rules"`) before running `/setup`, or post your own; the rules channel is read-only for members, but staff can post in it.
- **Existing members and the member role:** new members get it automatically (or by clicking Verify). People who were already in the server need to click **Verify**, or you can give them the role by hand.
- **Hand out level rewards?** No need: members earn them by chatting.

### For members

- **Verify** (if the server uses it): read the rules, then click **✅ I've read the rules, let me in**.
- **Pick your roles:** in the reaction-roles channel (e.g. `✨┃reaction-roles` or `🎖️┃choose-your-path`), click an emoji under a message to get that role, and click it again to drop it. In a "pick one" message, choosing another emoji swaps your role.
- **Level up:** chat to earn XP (once a minute counts). Check `/rank` and `/leaderboard`.
- **Get help:** in the support channel (e.g. `🎫┃open-a-ticket`), click **🎫 Open a ticket**. A private channel opens that only you and the mods can see. Describe your issue there. You can have one open ticket at a time.

### For moderators

- **Closing tickets:** when an issue is resolved, click **🔒 Close ticket (staff)** in the ticket channel. It's deleted after 5 seconds. Members can't close their own tickets. When the last ticket is closed, the tickets category disappears too.
- **Muting someone:** `/mute @member 30m spamming`. They can still read but can't type, react, create threads or speak in voice. Leave out the duration to mute until `/unmute`.
- **Everything is logged** in the mod-log channel (e.g. `📋┃mod-log`, `📋┃royal-records`): mutes, warnings, purges, tickets, verifications, joins and leaves.
- **Staff channels:** the staff category (e.g. `🛡️ STAFF ROOM`, `🗡️ ROYAL COUNCIL`) is visible only to the staff role.

### Undoing everything

Run `/reset`. It lists what the bot created and asks for confirmation, then deletes only those items: roles, categories, channels (including open tickets) and its own messages. Anything made by people, or existing items the wizard reused, is left alone.

> To bring back the channels a **fresh start** removed, use `/restore` and pick the backup called "Before fresh start". Restoring replaces the current channels (which are backed up too) but doesn't touch roles, so run `/reset` first if you also want the bot's roles gone. Messages can't be restored.

---

## 🎨 Customising

Everything lives in [`templates.py`](templates.py). No other code needs to change.

- **New server type:** add an entry to `SERVER_TYPES`:
  - `label`, `emoji`, `description`
  - `staff_role` / `staff_color`, `member_role` / `member_color`
  - themed `roles` (use `"above_staff": True` for cosmetic top ranks, `"level": 10` for a leveling reward)
  - `welcome_message` (with a `{user}` placeholder)
  - `rules`: `{"title": ..., "items": [(emoji, rule, details), ...]}`
  - `channels`, `default_features`, `default_self_roles` (one group per line)
  - optionally `category_names` and `renames` to re-theme shared channels, e.g. `"announcements": ("📯", "royal-decrees")`
- **New feature:** add an entry to `FEATURES` with its `channels` and optional `followups`.
- **New category:** add it to `CATEGORIES` with a permission preset (`public`, `announcement`, `readonly`, `staff_only`, `tickets` or `locked`).
- **Channels:** use `text(name, category, preset, emoji="📢")` and `voice(name, category, emoji="🔊")`. Text channels are shown as `📢┃name`. Pass `ungated=True` to keep a channel visible before members verify.
- **Leveling speed:** `XP_PER_MESSAGE` and `XP_COOLDOWN_SECONDS`.

`templates.validate()` runs at startup and reports typos such as an unknown category, preset, feature or renamed channel.

---

## 🗂️ Project structure

```
bot.py              entry point: loads cogs, syncs slash commands
config.py           reads .env
templates.py        server types, features, categories, channels and roles
core/
  plan.py           wizard answers + templates -> concrete Plan; role groups; duplicate detection
  builder.py        runs a Plan: backup, fresh start, creation, retries, tracking, progress
  layout.py         snapshot a server's layout; rebuild it (restore / templates)
  wipe.py           deleting channels and old bot roles (shared by setup, restore, templates)
  permissions.py    permission presets + verification gate -> overwrites; safety checks
  storage.py        SQLite: tracked items, settings, backups, templates, XP, warnings, mutes
  modlog.py         posts events to the mod-log channel
  retry.py          retry helper for rate limits / server errors
  ui.py             embed helpers, progress bar, DELETE confirmation
cogs/
  wizard.py         /setup
  reset.py          /reset
  backup.py         /backup, /restore
  server_templates.py  /template save|list|apply|delete|export|import
  role_menu.py      reaction roles (role menus from older versions still work)
  tickets.py        open/close tickets, on-demand ticket category
  welcome.py        welcome messages, verify button, auto-role, join/leave log
  leveling.py       XP, level rewards, /rank, /leaderboard
  stats.py          live member/boost count channels
  moderation.py     /mute, /unmute, /warn, /warnings, /clearwarnings, /purge
Dockerfile          container image for running 24/7
setup.md            step-by-step first-time setup guide
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| Bot exits with "needs the Server Members intent" | Developer Portal → Bot → turn on **Server Members Intent** → Save, then start it again. |
| `/setup` doesn't appear | Check `TEST_GUILD_ID`, then reload Discord (Ctrl/Cmd+R). The invite must include `applications.commands`. |
| "I'm missing some permissions" | Re-invite with the URL above, or enable the listed permissions on the bot's role. |
| Roles fail to create or assign | Drag the bot's role to the top of the role list. |
| A member can see a hidden channel | Check they don't have **Administrator**. Admins see every channel. |
| A reaction doesn't give a role | The bot must be online, and its role must be above that role. |
| No welcome message / auto-role | Turn on **Server Members Intent**, and make sure the bot's role is above the member role. |
| Stat channels don't update | They refresh every 10 minutes; Discord allows only 2 renames per channel per 10 minutes. |
| `CERTIFICATE_VERIFY_FAILED` (macOS) | Run `"/Applications/Python 3.x/Install Certificates.command"` once. |

More in [setup.md](setup.md#troubleshooting).

---

## ⚠️ Notes and limits

- **Fresh start** can't delete the rules or updates channels that Discord requires on **Community** servers. They're skipped and listed as a warning.
- **Muted** is applied to every pre-existing channel, one API call each, so this is slow on very large servers.
- **Reaction roles** only use the emoji already on each message; members can't add new ones there. If a moderator removes a reaction role by hand, the member's reaction stays until they click it again.
- **Verification** hides channels from members who haven't verified, including people who were already in the server. Admins and the staff role always see everything.
- **Backups and templates** hold channel names, order, topics, settings and permissions, but not messages. Restoring rebuilds stage channels as voice channels.
- **Templates** only include channels the person saving them can see, and never include member-specific permissions.
- **Permission safety:** `/setup` and `/reset` require Manage Server, Manage Channels **and** Manage Roles, so nobody can use the bot to do more than they could themselves:
  - New roles only get permissions that the person running `/setup` has.
  - Fresh start and `/reset` won't delete roles above that person's highest role.
  - An existing role is only made a reaction role or level reward if it has no moderator/admin permissions, doesn't unlock any channels, **and** the person running `/setup` could assign it themselves.
  - Restore and template permissions are capped the same way: nothing is granted that the person running it doesn't have.
  - The verify button, auto-role, level rewards and `/mute` re-check each role every time. If someone later gives that role moderator permissions, the bot stops handing it out.
- **Role icons** (images next to names) need Server Boost level 2, so the role emoji are part of the names instead.
- **Limits per run:** 10 extra channels, 20 subjects, 20 reaction roles in up to 5 groups.

---

## ☁️ Running 24/7

The bot only works while `python bot.py` is running, so it goes offline when your computer sleeps. To keep it online, run it on an always-on machine. The included `Dockerfile` works almost anywhere.

**Any machine with Docker** (a VPS, a home server, a Raspberry Pi 4/5):

```bash
docker build -t setup-bot .
docker run -d --name setup-bot --restart unless-stopped \
  --env-file .env -v setup-bot-data:/app/data setup-bot
docker logs -f setup-bot          # watch it start
```

The `-v setup-bot-data:/app/data` volume keeps the database (tracked items, backups, XP, warnings) when you rebuild or update the container.

**Railway** (no server to manage):

1. Push this repo to GitHub (your `.env` stays local; it's git-ignored).
2. On [railway.com](https://railway.com), choose **New Project → Deploy from GitHub repo** and pick this repo. Railway finds the `Dockerfile` on its own.
3. Under **Variables**, add `DISCORD_TOKEN` (and `TEST_GUILD_ID` if you want).
4. Under **Settings → Volumes**, add a volume mounted at `/app/data` so the database survives redeploys.

**Fly.io:** run `fly launch` (it detects the Dockerfile; say no to adding a database), then `fly secrets set DISCORD_TOKEN=...`, `fly volumes create bot_data --size 1`, and mount it at `/app/data` in `fly.toml`. Finish with `fly deploy`.

> Only run **one** copy of the bot at a time. Two copies with the same token would both answer every command.

---

## 📄 License

Released under the [MIT License](LICENSE).
