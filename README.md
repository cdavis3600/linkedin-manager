# LinkedIn Manager — Automated Post Rewriter

Automatically fetches posts from any LinkedIn company page or personal profile,
rewrites them into personal versions using GPT-4, sends them to Discord for approval,
and posts to your personal LinkedIn profile with one click.

---

## How It Works

```
10:00 AM daily
     ↓
Proxycurl fetches posts from SOURCE_LINKEDIN_URLS
     ↓
Deduplicate (SQLite)
     ↓
Download media
     ↓
GPT-4 generates 3 variants:
  • Personal  (~200 words)
  • Shorter   (~80 words)
  • Technical (for builders/engineers)
     ↓
Discord DM with approval buttons:
  ✅ Approve Personal | 📏 Use Shorter | 🔧 Use Technical
  ✏️  Regenerate      | ⏭ Skip
     ↓
On approve → post to your personal LinkedIn (with images)
```

---

## Architecture

| Component | Purpose |
|---|---|
| `Proxycurl API` | Reads posts from any public LinkedIn URL (company or person) |
| `LinkedIn API` | Posts to your personal profile only |
| `GPT-4o` | Rewrites company posts into personal variants |
| `Discord bot` | Sends approval messages, handles your responses |
| `APScheduler` | Runs the pipeline daily at configured time |
| `SQLite` | Deduplication and post history |

---

## Setup (Completed Steps)

- ✅ LinkedIn Developer App created at [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
- ✅ Products added: **Share on LinkedIn** + **Sign In with LinkedIn using OpenID Connect**
- ✅ Redirect URI set: `http://localhost:8080/callback`
- ✅ Proxycurl account at [nubela.co](https://nubela.co) — API key obtained
- ✅ OpenAI API key obtained
- ✅ Discord bot created, token obtained, added to server
- ✅ `.env` file fully configured
- ✅ OAuth complete — `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_MEMBER_ID` saved to `.env`
- ✅ All dependencies installed

---

## Installation

### Python Requirements (Python 3.13)

```bash
pip3 install discord.py==2.4.0 openai>=1.52.0 requests==2.31.0 python-dotenv==1.0.1 \
  apscheduler==3.10.4 aiohttp==3.10.5 aiofiles==23.2.1 Pillow==10.4.0 audioop-lts
```

> `audioop-lts` is required for Python 3.13 compatibility with discord.py

### SSL Certificates (Mac only, one-time)

```bash
/Applications/Python\ 3.13/Install\ Certificates.command
```

---

## Configuration (`.env`)

```env
# LinkedIn App (posting only)
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REDIRECT_URI=http://localhost:8080/callback

# Filled automatically by oauth_setup.py
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_MEMBER_ID=

# Proxycurl (reading posts)
PROXYCURL_API_KEY=
PROXYCURL_BASE_URL=https://nubela.co/proxycurl/api

# URLs to monitor — comma-separated, any mix of companies and people
SOURCE_LINKEDIN_URLS=https://www.linkedin.com/company/the-famous-group/

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# Discord
DISCORD_BOT_TOKEN=
DISCORD_APPROVAL_CHANNEL_ID=   # your DM channel ID with the bot

# Schedule
SCHEDULE_HOUR=10
SCHEDULE_MINUTE=0
TIMEZONE=America/New_York
```

---

## Running

### Test run (fires pipeline immediately)
```bash
python3 main.py --now
```

### Normal run (starts bot + daily scheduler)
```bash
python3 main.py
```

### Re-authorize LinkedIn (every ~55 days)
```bash
python3 oauth_setup.py
```

---

## Discord Commands

| Command | Description |
|---|---|
| `!status` | Recent post history |
| `!pending` | Posts awaiting approval |

Approval buttons appear automatically in your Discord DM for each new post.

---

## Adding More Sources

Add any LinkedIn URL to `SOURCE_LINKEDIN_URLS` in `.env` (comma-separated):

```env
SOURCE_LINKEDIN_URLS=https://www.linkedin.com/company/the-famous-group/,https://www.linkedin.com/in/gary-vaynerchuk/,https://www.linkedin.com/company/apple/
```

Supports both company pages and personal profiles. No code changes needed.

---

## Project Structure

```
linkedin_manager/
├── main.py           ← Entry point + scheduler
├── config.py         ← Environment variable loader
├── database.py       ← SQLite deduplication + history
├── linkedin.py       ← Proxycurl (read) + LinkedIn API (post)
├── rewriter.py       ← GPT-4 post rewriter
├── discord_bot.py    ← Discord bot + approval UI
├── scheduler.py      ← Pipeline logic
├── oauth_setup.py    ← One-time LinkedIn OAuth (re-run every ~55 days)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env              ← Your credentials (never commit this)
├── .env.example      ← Template
└── data/             ← Created at runtime
    ├── linkedin_manager.db
    ├── media/
    └── logs/
```

---

## Deployment (24/7 Cloud VM)

For always-on operation, deploy to a cloud VM (~$5–6/month):

```bash
# On your VM
git clone <your-repo> linkedin_manager
cd linkedin_manager
cp .env.example .env  # fill in your values including tokens
docker compose up -d
docker compose logs -f
```

Providers: DigitalOcean, Vultr, Linode, Railway

---

## Token Refresh

LinkedIn access tokens expire after **~60 days**. Set a calendar reminder.

To refresh:
```bash
python3 oauth_setup.py
```
