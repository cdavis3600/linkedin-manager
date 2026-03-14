"""
config.py — Load and validate all environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return val


class Config:
    # LinkedIn App (for posting only)
    LINKEDIN_CLIENT_ID: str = _require("LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET: str = _require("LINKEDIN_CLIENT_SECRET")
    LINKEDIN_REDIRECT_URI: str = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback")

    # LinkedIn Tokens (filled by oauth_setup.py)
    LINKEDIN_ACCESS_TOKEN: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    LINKEDIN_MEMBER_ID: str = os.getenv("LINKEDIN_MEMBER_ID", "")

    # Source LinkedIn URLs to monitor — comma-separated list
    # Can be company pages AND/OR personal profiles
    # e.g. https://www.linkedin.com/company/the-famous-group/,https://www.linkedin.com/in/someone/
    SOURCE_LINKEDIN_URLS: list = [
        u.strip() for u in os.getenv("SOURCE_LINKEDIN_URLS", "").split(",") if u.strip()
    ]

    # OpenAI
    OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # Discord
    DISCORD_BOT_TOKEN: str = _require("DISCORD_BOT_TOKEN")
    DISCORD_APPROVAL_CHANNEL_ID: int = int(_require("DISCORD_APPROVAL_CHANNEL_ID"))

    # Scheduler
    SCHEDULE_HOUR: int = int(os.getenv("SCHEDULE_HOUR", "10"))
    SCHEDULE_MINUTE: int = int(os.getenv("SCHEDULE_MINUTE", "0"))
    TIMEZONE: str = os.getenv("TIMEZONE", "America/New_York")

    # App
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DB_PATH: str = os.getenv("DB_PATH", "data/linkedin_manager.db")
    MEDIA_DIR: str = os.getenv("MEDIA_DIR", "data/media")
    MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS_PER_RUN", "5"))
    APPROVAL_TIMEOUT_HOURS: int = int(os.getenv("APPROVAL_TIMEOUT_HOURS", "12"))


config = Config()
