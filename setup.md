# Setup Guide — from Developer Portal to a running bot

You've created your application in the Developer Portal. Follow these steps in order.

---

## Step 1 — Copy your Application ID

1. Open <https://discord.com/developers/applications> and click your application.
2. On **General Information**, copy the **Application ID** (a long number).
3. Keep it handy; you'll use it in Step 4.

---

## Step 2 — Get the bot token

1. In the left sidebar, click **Bot**.
2. If you see an **Add Bot** button, click it and confirm with **Yes, do it!** This creates the bot user for your application. Newer portal versions create it automatically, so you may not see this button.
3. Click **Reset Token** → confirm (enter your 2FA code if asked). If you see a **Copy** button under the token instead, just use that.
4. Click **Copy**. The token is shown only once; if you lose it, reset it again.

> ⚠️ The token is the bot's password. Never paste it in Discord, screenshots, or commit it to git.

---

## Step 3 — Check the bot settings

Still on the **Bot** page:

| Setting | Value |
|---|---|
| Public Bot | Off (recommended, so only you can invite it) |
| Requires OAuth2 Code Grant | **Off** |
| Presence Intent | Off |
| Server Members Intent | Off |
| Message Content Intent | Off |

This bot doesn't need any privileged intents. Click **Save Changes** if you changed anything.

---

## Step 4 — Invite the bot to a test server

1. Make a throwaway test server: in Discord, click **+** at the bottom of the server list → **Create My Own** → **For me and my friends**.
2. Paste this URL into your browser, replacing `YOUR_APPLICATION_ID` with the ID from Step 1:

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=1477904034896&scope=bot+applications.commands
   ```

3. Choose your test server → **Continue** → leave every permission ticked → **Authorize**.

The bot now appears in the member list, shown as offline until you start it in Step 8.

---

## Step 5 — Move the bot's role up

1. In your test server: **Server Settings → Roles**.
2. Drag the role with your bot's name to the **top** of the list, or at least above every role it should manage.
3. Click **Save Changes**.

Discord only lets a bot manage roles that sit below its own role.

---

## Step 6 — Copy your test server's ID

1. In Discord: **User Settings → Advanced → Developer Mode → On**.
2. Right-click your test server's icon → **Copy Server ID**.

With this ID set, slash commands appear instantly instead of after up to an hour.

---

## Step 7 — Create your `.env` file

In a terminal, inside the project folder:

```bash
cd discord-setup-wizard      # the folder you cloned / downloaded
cp .env.example .env
open -e .env                 # macOS; on Windows use: notepad .env
```

Fill it in (no quotes, no spaces around `=`):

```
DISCORD_TOKEN=paste-your-token-from-step-2
TEST_GUILD_ID=paste-your-server-id-from-step-6
DATABASE_PATH=data/bot.db
```

Save and close. `.env` is in `.gitignore`, so it won't be committed.

---

## Step 8 — Install and run

Requires **Python 3.10+**. The first time, create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then, every time you want to start the bot:

```bash
source .venv/bin/activate
python bot.py
```

> **macOS + python.org Python:** if you get `CERTIFICATE_VERIFY_FAILED`, run
> `"/Applications/Python 3.13/Install Certificates.command"` once (use your Python version).

You should see log lines like:

```
INFO  setup_bot Synced 2 command(s) to test guild 123456789012345678 (instant)
INFO  setup_bot Logged in as YourBot#1234 (id ...) in 1 guild(s)
```

The bot is now online. Keep this terminal open; press **Ctrl+C** to stop the bot.

---

## Step 9 — Run the wizard

1. In your test server, type `/setup` and press Enter.
2. Pick a server type → adjust features → **Next** → fill in the form → answer any follow-ups → choose **Fresh start** or **Keep existing** → review the preview → **Confirm & build**.
3. Watch the progress counter. When it finishes, your new channels and roles appear in the sidebar.

To undo everything the bot created, run `/reset` and confirm.

---

## Step 10 — Check that it works (optional but recommended)

Invite a second Discord account (or a friend) to the test server, then check:

- [ ] They can read the announcements, rules and welcome channels but can't type there
- [ ] They can't see the staff category
- [ ] In the roles channel, clicking a button or reacting with an emoji gives them that role
- [ ] **Open a ticket** creates a private channel (and its category) that only they and the mods can see
- [ ] They **can't** close their own ticket; a mod can, and the category disappears when the last ticket closes
- [ ] After you give them the **🔇 Muted** role, they can't type or speak anywhere
- [ ] After a bot restart (Ctrl+C, then `python bot.py`), the role and ticket buttons still work

The README has the full testing checklist.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `DISCORD_TOKEN is not set` | `.env` is missing or in the wrong folder. It must sit next to `bot.py`. |
| `LoginFailure: Improper token` | Token copied wrong or reset since. Reset it again (Step 2) and update `.env`. |
| `/setup` doesn't show up | Check that `TEST_GUILD_ID` is your server's ID and the log says "Synced … to test guild". Restart Discord with **Ctrl+R** (or **Cmd+R**). Make sure the invite URL included `applications.commands`. |
| Commands appear twice | You synced globally once and also to the guild. Harmless; the global copies can be cleared later. |
| "I'm missing some permissions" | Re-invite with the URL from Step 4, or enable the listed permissions on the bot's role. |
| "Missing permissions" errors while building | The bot's role is too low. Repeat Step 5. |
| "You need the Manage Server permission" | Run `/setup` from an account with Manage Server (the server owner always has it). |
| `ModuleNotFoundError: discord` | Activate the venv first: `source .venv/bin/activate`. |
| `CERTIFICATE_VERIFY_FAILED` (macOS) | Run `"/Applications/Python 3.x/Install Certificates.command"` once. |

---

## Going live on your real server

1. Invite the bot to the real server with the same URL (Step 4) and move its role up (Step 5).
2. Either change `TEST_GUILD_ID` to the real server's ID, or leave it **empty** to sync commands globally to every server the bot is in. Global sync can take up to an hour.
3. Restart the bot. To keep it running 24/7 you'll need it on an always-on machine or a host such as a VPS, Railway or fly.io, not your laptop.
