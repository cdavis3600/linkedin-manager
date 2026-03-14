# LinkedIn Manager — Cursor Handoff

This document captures exactly where the project is and what to do next.
Open this in Cursor and use it as your starting point.

---

## Current Status (as of March 13, 2026)

**All setup is complete. The project is ready for its first test run.**

Everything is configured and working:
- ✅ LinkedIn OAuth complete (tokens saved in `.env`)
- ✅ Discord bot configured and tested
- ✅ OpenAI API key in `.env` (used for both fetching and rewriting)
- ✅ All Python dependencies installed
- ✅ SSL certificates fixed (Mac)

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

## If The Test Run Fails

Paste the full error from terminal here in Cursor chat and ask it to fix it.
The most common issues and their fixes are documented below.

### Error: module not found
```bash
pip3 install discord.py==2.4.0 openai>=1.52.0 requests==2.31.0 python-dotenv==1.0.1 \
  apscheduler==3.10.4 aiohttp==3.10.5 aiofiles==23.2.1 Pillow==10.4.0 audioop-lts
```

### Error: SSL certificate verify failed
```bash
/Applications/Python\ 3.13/Install\ Certificates.command
```

### Error: unauthorized_scope_error (LinkedIn)
Check `oauth_setup.py` line 28 — scopes must be exactly:
```python
SCOPES = "openid profile email w_member_social"
```

### Error: No posts found
- Check `SOURCE_LINKEDIN_URLS` in `.env` — must be full URL with trailing slash
- Check `OPENAI_API_KEY` is valid and has credits
- Run `python3 test_fetch.py` to isolate the fetch step

### Discord message not appearing
- Make sure you sent the bot a DM first (to open the thread)
- Check `DISCORD_APPROVAL_CHANNEL_ID` is the numeric DM channel ID, not a server channel

---

## Key Files To Know

| File | What it does | When to edit |
|---|---|---|
| `.env` | All credentials and settings | Adding new source URLs, changing schedule time |
| `config.py` | Loads `.env` into Python | Adding new config variables |
| `linkedin.py` | OpenAI web search fetch + LinkedIn post | Fetch prompt or posting changes |
| `rewriter.py` | GPT-4 prompt and variants | Changing writing style or tone |
| `discord_bot.py` | Approval UI and buttons | Adding new approval options |
| `scheduler.py` | Pipeline logic | Changing what happens at run time |
| `oauth_setup.py` | LinkedIn OAuth (run every ~55 days) | Scope changes |

---

## Adding More LinkedIn Sources

Edit `.env` — no code changes needed:

```env
SOURCE_LINKEDIN_URLS=https://www.linkedin.com/company/the-famous-group/,https://www.linkedin.com/in/someone/
```

---

## Changing the GPT-4 Writing Style

Open `rewriter.py` and edit the `SYSTEM_PROMPT` at the top, or the
`instruction` strings inside `generate_variants()`. Ask Cursor:
*"Make the personal variant sound more like a founder sharing a lesson learned"*

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
```
