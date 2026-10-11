# 🧙 Discord Server Setup Wizard

A Discord bot that builds a complete, themed server for you. Run `/setup`, answer a few interactive questions (buttons, menus and pop-up forms), and the bot creates styled roles, categories and channels with permissions already set up. That includes support tickets, self-assign roles and a Muted role.

Built with [discord.py](https://github.com/Rapptz/discord.py) 2.x.

---

## ✨ Features

- **Interactive wizard:** server type → features → details → follow-up questions → fresh start or keep existing → preview → build with a live progress bar.
- **5 themed server types**, each with its own coloured roles, emoji channel names and category names:

  | Type | Roles (top → bottom) | Example channels |
  |---|---|---|
  | 🎮 Gaming | 🏆 Champion, 🎮 Game Master, 🔥 Pro Player, 📺 Streamer, 🕹️ Player | `🔍┃lfg`, `🎬┃clips`, `🎧 Squad 1` |
  | 🐉 Fantasy / Anime | 👑 King, 👸 Queen, ⚔️ Knight, 🧙 Archmage, 🐉 Dragon Rider, 🏹 Ranger, 🪓 Viking | `📯┃royal-decrees`, `🍺┃tavern-chat`, `🌸┃anime-chat` |
  | 📚 Study group | 🎓 Professor, 🧠 Top Scholar, ✏️ Note Taker, 📖 Scholar | `📝┃study-chat`, `📘┃math`, `🔕 Focus Room 1` |
  | 🎬 Creator / YouTube | 🎬 Creator, 🛠️ Crew, 💎 Subscriber, 🎨 Artist, ⭐ Fan | `🎥┃uploads`, `💡┃feedback`, `🤝┃collabs` |
  | 💬 General hangout | 🌟 Guardian, 💫 Regular, 🎉 Party Starter, 🌸 Resident | `🌀┃off-topic`, `👋┃introductions` |

- **Permissions handled for you**
  - Announcements: everyone reads, only staff post.
  - Rules and welcome: read-only.
  - Staff area: hidden from everyone except staff.
  - **🔇 Muted** role: can't type, react, use threads or speak anywhere.
- **🎫 Support tickets**
  - Members open a private ticket with a button. Only the member and the mods can see it.
  - **Only mods can close tickets.**
  - The tickets category appears only while a ticket is open.
- **🏷️ Self-assign roles** with **buttons and emoji reactions** on the same message.
- **🧹 Fresh start (optional):** deletes all existing channels and builds from scratch. You must type `DELETE` to confirm.
- **Safe**
  - Everything the bot creates is tracked in SQLite.
  - `/reset` removes **only** what the bot made.
  - Before building, the bot checks for duplicate names and asks whether to skip or create them anyway.
  - API calls are rate-limited and retried on failure.
  - The bot checks its own permissions first.
  - A wizard times out after 10 minutes of inactivity.
- **Survives restarts:** role and ticket buttons keep working after the bot restarts.
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
| `DATABASE_PATH` | – | Where created-item IDs are stored (default `data/bot.db`) |

`.env` and `data/` are git-ignored. **Never commit your token.**

### Developer Portal settings

- **Bot** tab: no privileged intents are needed (Presence, Server Members and Message Content can all stay **off**). Turn off **Requires OAuth2 Code Grant**.
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
| `/setup` | Members with **Manage Server + Manage Channels + Manage Roles** | Runs the setup wizard. Only you can see the wizard messages. |
| `/reset` | Members with **Manage Server + Manage Channels + Manage Roles** | Deletes everything the bot created, after you confirm. |

### For admins: setting up your server

1. **Type `/setup`** in any channel and press Enter.
2. **Pick a server type** (Gaming, Fantasy / Anime, Study group, Creator / YouTube or General hangout). This decides the role names, colours and channel theme.
3. **Choose features** from the menu. Sensible defaults are pre-selected; tick or untick what you want, then press **Next**:

   | Feature | What you get |
   |---|---|
   | 📢 Announcements | A channel only staff can post in |
   | 📜 Rules & welcome | Read-only welcome and rules channels |
   | 📅 Events | Events channel, event chat and a stage voice channel |
   | 🔊 Voice hangouts | Casual voice channels |
   | 🎫 Support tickets | A button members click to open private tickets |
   | 🖼️ Media/memes | Media and memes channels |
   | 🛡️ Staff area | A private category only staff can see |
   | 🏷️ Self-assign roles | A message where members pick their own roles |

4. **Fill in the details form.** The staff and member role names are pre-filled with the theme (e.g. `⚔️ Knight` / `🪓 Viking`). Change them if you like. You can also add extra channels, comma-separated (e.g. `art, 🎲 board games`).
5. **Answer the follow-up questions.** They only appear when relevant:
   - **Support tickets:** which role can see and close tickets (usually your staff role).
   - **Study group:** your subjects. Each one becomes a channel.
   - **Self-assign roles:** the role names. Start a name with an emoji (e.g. `🔥 Fire Mage`) and that emoji becomes its reaction.
6. **Choose how to build:**
   - **🧹 Fresh start:** deletes **all** existing channels and categories (and roles the bot made earlier), then builds everything new. Your other roles are kept. Deleted channels **cannot be recovered**.
   - **➕ Keep existing:** leaves your current channels alone and adds the new ones. If something with the same name already exists, you choose to **skip** it (reuse it) or **create it anyway**.
7. **Review the preview.** It lists every role, category and channel. Press **✅ Confirm & build**, **✏️ Edit** to start over (your answers are remembered), or **Cancel** (nothing is created).
   - For a fresh start you'll be asked to **type `DELETE`** to confirm.
8. **Watch it build.** A progress bar shows each step. With a fresh start, the summary is posted in your new staff channel, because the channel you ran `/setup` in has been deleted.

### After setup: what to do next

- **Give your moderators the staff role** (e.g. ⚔️ Knight, 🎮 Game Master). It has moderation powers: delete messages, time out, mute/move in voice, change nicknames.
- **Hand out the cosmetic ranks yourself** (e.g. 👑 King, 👸 Queen, 🏆 Champion). They're displayed separately and coloured but carry no extra permissions.
- **Write your rules and welcome message.** Those channels are read-only for members, but staff can post in them.
- **Optional:** give everyone the member role (e.g. 🪓 Viking) with an auto-role bot, or by hand.

### For members

- **Pick your roles:** go to the roles channel (e.g. `🏷️┃roles` or `🎖️┃choose-your-path`). Either:
  - **click a button** to add a role (click again to remove it), or
  - **react with the emoji** to add the role (remove your reaction to drop it).
- **Get help:** in the support channel (e.g. `🎫┃open-a-ticket`), click **🎫 Open a ticket**. A private channel opens that only you and the mods can see. Describe your issue there. You can have one open ticket at a time.

### For moderators

- **Closing tickets:** when an issue is resolved, click **🔒 Close ticket (staff)** in the ticket channel. It's deleted after 5 seconds. Members can't close their own tickets. When the last ticket is closed, the tickets category disappears too.
- **Muting someone:** give them the **🔇 Muted** role. They can still read but can't type, react, create threads or speak in voice. Remove the role to unmute.
- **Staff channels:** the staff category (e.g. `🛡️ STAFF ROOM`, `🗡️ ROYAL COUNCIL`) is visible only to the staff role.

### Undoing everything

Run `/reset`. It lists what the bot created and asks for confirmation, then deletes only those items: roles, categories, channels (including open tickets) and its own messages. Anything made by people, or existing items the wizard reused, is left alone.

> `/reset` can't bring back channels removed by a **fresh start**. Those weren't made by the bot, so they are permanently gone.

---

## 🎨 Customising

Everything lives in [`templates.py`](templates.py). No other code needs to change.

- **New server type:** add an entry to `SERVER_TYPES`:
  - `label`, `emoji`, `description`
  - `staff_role` / `staff_color`, `member_role` / `member_color`
  - themed `roles` (use `"above_staff": True` for cosmetic top ranks)
  - `channels`, `default_features`, `default_self_roles`
  - optionally `category_names` and `renames` to re-theme shared channels, e.g. `"announcements": ("📯", "royal-decrees")`
- **New feature:** add an entry to `FEATURES` with its `channels` and optional `followups`.
- **New category:** add it to `CATEGORIES` with a permission preset (`public`, `announcement`, `readonly`, `staff_only` or `tickets`).
- **Channels:** use `text(name, category, preset, emoji="📢")` and `voice(name, category, emoji="🔊")`. Text channels are shown as `📢┃name`.

`templates.validate()` runs at startup and reports typos such as an unknown category, preset, feature or renamed channel.

---

## 🗂️ Project structure

```
bot.py              entry point: loads cogs, syncs slash commands
config.py           reads .env
templates.py        server types, features, categories, channels and roles
core/
  plan.py           wizard answers + templates -> concrete Plan; duplicate detection
  builder.py        runs a Plan: fresh start, creation, retries, tracking, progress
  permissions.py    permission presets -> channel overwrites; required bot permissions
  storage.py        SQLite: tracked items + per-server settings
  retry.py          retry helper for rate limits / server errors
  ui.py             embed helpers and the progress bar
cogs/
  wizard.py         /setup
  reset.py          /reset
  role_menu.py      self-assign buttons + reaction roles
  tickets.py        open/close tickets, on-demand ticket category
setup.md            step-by-step first-time setup guide
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `/setup` doesn't appear | Check `TEST_GUILD_ID`, then reload Discord (Ctrl/Cmd+R). The invite must include `applications.commands`. |
| "I'm missing some permissions" | Re-invite with the URL above, or enable the listed permissions on the bot's role. |
| Roles fail to create or assign | Drag the bot's role to the top of the role list. |
| A member can see a hidden channel | Check they don't have **Administrator**. Admins see every channel. |
| A reaction or button doesn't give a role | The bot must be online, and its role must be above that role. |
| `CERTIFICATE_VERIFY_FAILED` (macOS) | Run `"/Applications/Python 3.x/Install Certificates.command"` once. |

More in [setup.md](setup.md#troubleshooting).

---

## ⚠️ Notes and limits

- **Fresh start** can't delete the rules or updates channels that Discord requires on **Community** servers. They're skipped and listed as a warning.
- **Muted** is applied to every pre-existing channel, one API call each, so this is slow on very large servers.
- **Buttons and reactions** on the role menu work independently. If someone adds a role by reacting and removes it with the button, their reaction stays.
- **Permission safety:** `/setup` and `/reset` require Manage Server, Manage Channels **and** Manage Roles, so nobody can use the bot to do more than they could themselves. An existing role is only added to the self-assign menu if it has no moderator/admin permissions **and** the person running `/setup` could assign it themselves.
- **Role icons** (images next to names) need Server Boost level 2, so the role emoji are part of the names instead.
- **Limits per run:** 10 extra channels, 20 subjects, 20 self-assign roles.
- The bot only runs while `python bot.py` is running. For 24/7 uptime, host it on a VPS or a service such as Railway or fly.io.

---

## 📄 License

Released under the [MIT License](LICENSE).
