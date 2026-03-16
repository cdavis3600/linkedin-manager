# LinkedIn Manager — Cursor Handoff

This document captures exactly where the project is and what to do next.
Open this in Cursor and use it as your starting point.

---

## Current Status (as of March 15, 2026)

**Core rewrite complete. All major features implemented.**

- ✅ LinkedIn OAuth complete (tokens saved in `.env`)
- ✅ Discord bot configured and tested
- ✅ OpenAI API key in `.env` (used for both fetching and rewriting)
- ✅ All Python dependencies installed
- ✅ SSL certificates fixed (Mac)
- ✅ Single post generation (no more 3 variants)
- ✅ CJ's voice profile built from real post examples
- ✅ 3 source types: tfg / inspiration / industry (each with distinct tone)
- ✅ Team tagging step in Discord (multi-select before posting)
- ✅ Source type prefix support in SOURCE_LINKEDIN_URLS

---

## How the Discord Flow Works Now

1. Bot fetches posts from all SOURCE_LINKEDIN_URLS daily at 10 AM
2. GPT-4 picks the best post (or synthesizes overlapping themes)
3. One post is generated in CJ's voice, tuned to the source type:
   - 🏢 **Company Post (tfg)** — brief personal reaction, team pride, 1-4 sentences
   - 💡 **Inspiration** — curious/observational riff on something CJ follows, 3-6 sentences
   - 📰 **Industry News** — opinionated take on what's happening, 3-6 sentences
4. Discord embed shows the post with source type label + Approve / Regenerate / Skip buttons
5. On Approve → **team tagging step** (multi-select dropdown of teammates to @-mention)
6. Post goes live on LinkedIn

---

## First Thing To Do

Run the pipeline right now to test everything end-to-end:

```bash
python3 main.py --now
```

Watch two things:
1. **Terminal** — shows logs of fetching, generating, errors
2. **Discord DM** — approval message should appear within 30–60 seconds

---

## .env Setup

Make sure these are all populated in your `.env`:

```env
# Source URLs with type prefixes
SOURCE_LINKEDIN_URLS=tfg:https://www.linkedin.com/company/the-famous-group/,inspiration:https://www.linkedin.com/in/someone/

# Team members for the Discord tagging step
TEAM_MEMBERS=Jane Smith,John Doe,Bob Jones
```

Valid type prefixes: `tfg`, `inspiration`, `industry`
If no prefix is given, the URL defaults to `inspiration`.

---

## If The Test Run Fails

Paste the full error from terminal into Cursor chat and ask it to fix it.

### Error: module not found
```bash
pip3 install discord.py==2.4.0 "openai>=1.52.0" requests==2.31.0 python-dotenv==1.0.1 \
  apscheduler==3.10.4 aiohttp==3.10.5 aiofiles==23.2.1 Pillow==10.4.0 audioop-lts
```

### Error: SSL certificate verify failed
```bash
/Applications/Python\ 3.13/Install\ Certificates.command
```

### Error: unauthorized_scope_error (LinkedIn)
Check `oauth_setup.py` — scopes must be exactly:
```python
SCOPES = "openid profile email w_member_social"
```

### Error: No posts found
- Check `SOURCE_LINKEDIN_URLS` in `.env` — must have type prefix and full URL
- Check `OPENAI_API_KEY` is valid and has credits
- If `BRAVE_SEARCH_API_KEY` is set, Brave Search finds post URLs first
- Falls back to OpenAI Responses API with `web_search` if Brave is not configured

### Discord message not appearing
- Make sure you sent the bot a DM first (to open the thread)
- Check `DISCORD_APPROVAL_CHANNEL_ID` is the numeric DM channel ID

---

## Key Files To Know

| File | What it does | When to edit |
|---|---|---|
| `.env` | All credentials and settings | Adding new source URLs, changing schedule, editing team |
| `config.py` | Loads `.env` into Python | Adding new config variables |
| `linkedin.py` | Brave Search + OpenAI post fetch + LinkedIn post | Fetch prompt or posting changes |
| `rewriter.py` | GPT-4 voice profile + post generation | Changing CJ's voice or type instructions |
| `discord_bot.py` | Approval UI, team tagging, buttons | Adding new approval options |
| `scheduler.py` | Pipeline logic | Changing what happens at run time |
| `database.py` | SQLite deduplication and history | Schema changes |
| `oauth_setup.py` | LinkedIn OAuth (run every ~55 days) | Scope changes |

---

## Changing CJ's Voice / Post Style

Open `rewriter.py` and look at:
- `CJ_VOICE` — the overall voice profile (examples from real posts)
- `TYPE_INSTRUCTIONS["tfg"]` — rules for company post reactions
- `TYPE_INSTRUCTIONS["inspiration"]` — rules for posts about what CJ follows
- `TYPE_INSTRUCTIONS["industry"]` — rules for industry takes

Example: *"Make the TFG reactions even shorter — 2 sentences max"* →
Change the Length line in `TYPE_INSTRUCTIONS["tfg"]`.

---

## Adding More LinkedIn Sources

Edit `.env` — no code changes needed:

```env
SOURCE_LINKEDIN_URLS=tfg:https://www.linkedin.com/company/the-famous-group/,inspiration:https://www.linkedin.com/in/first-person/,industry:https://www.linkedin.com/company/industry-source/
```

---

## Adding / Editing Team Members

Edit `.env`:

```env
TEAM_MEMBERS=Jane Smith,John Doe,Bob Jones
```

These appear as checkboxes in Discord after each approval. Selected names get
appended to the post as `@Name` mentions before it's published.

---

## Discord Commands

```
!status   — recent post history (last 10)
!pending  — posts waiting for approval
!team     — show configured team roster
```

---

## Daily Schedule

Currently set to **10:00 AM America/New_York**. To change, update `.env`:

```env
SCHEDULE_HOUR=9
SCHEDULE_MINUTE=30
TIMEZONE=America/Los_Angeles
```

---

## Running Permanently (24/7)

Right now the bot only runs while Terminal is open. To run permanently,
deploy to a cloud VM using Docker:

```bash
docker compose up -d
```

See README.md → Deployment section for full instructions.

---

## LinkedIn Token Expiry

Your `LINKEDIN_ACCESS_TOKEN` expires in ~60 days. When it does, run:

```bash
python3 oauth_setup.py
```

Set a calendar reminder for **~May 10, 2026**.

---

## Quick Reference

```bash
# Test run now
python3 main.py --now

# Start normally (bot + daily scheduler)
python3 main.py

# Refresh LinkedIn token
python3 oauth_setup.py

# Check recent post history in Discord
!status

# Check pending approvals in Discord
!pending

# Check team roster in Discord
!team
```
