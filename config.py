"""
config.py — Load and validate all environment variables.

SOURCE_LINKEDIN_URLS format (supports type prefixes):
  tfg:https://www.linkedin.com/company/the-famous-group/
  inspiration:https://www.linkedin.com/in/someone/
  industry:https://www.linkedin.com/company/somecompany/

  If no prefix is given, "inspiration" is assumed.

TEAM_MEMBERS format: pipe-delimited fields, semicolon-separated entries
  Name|Title|Department|LinkedInURL
  e.g. "Jane Smith|Creative Director|Creative|https://www.linkedin.com/in/jane-smith/"

  Department supports compound values like "Tech & Vixi" — the person will
  appear in BOTH the Tech group and the Vixi group when tagging by department.
  Title and Department are shown in Discord. LinkedIn URL is appended when tagged.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return val


def _parse_source_urls(raw: str) -> tuple[list[dict], list[str]]:
    """
    Parse SOURCE_LINKEDIN_URLS into typed entries.

    Returns:
        (typed_list, plain_url_list)
        typed_list: [{"url": str, "source_type": "tfg"|"inspiration"|"industry"}, ...]
        plain_url_list: just the URLs (for backward compat)
    """
    typed = []
    plain = []
    valid_types = {"tfg", "inspiration", "industry"}

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        if ":" in entry:
            prefix, _, rest = entry.partition(":")
            prefix = prefix.strip().lower()
            url = rest.strip()
            if prefix in valid_types:
                source_type = prefix
            else:
                # Prefix is part of the URL (e.g. https://...)
                url = entry
                source_type = "inspiration"
        else:
            url = entry
            source_type = "inspiration"

        # Handle full URLs that start with https:// — re-join if split accidentally
        if url.startswith("//"):
            url = "https:" + url

        if url:
            typed.append({"url": url, "source_type": source_type})
            plain.append(url)

    return typed, plain


def _parse_team_members(raw: str) -> list[dict]:
    """
    Parse TEAM_MEMBERS into a list of dicts.

    Format: "Name|Title|Department|LinkedInURL;Name|Title|Department|LinkedInURL;..."
    Entries separated by SEMICOLONS (titles can contain commas).

    Fields:
      - name        (required)
      - title       (optional — shown in Discord so CJ knows who to pick)
      - department  (optional — used for bulk department tagging;
                     compound values like "Tech & Vixi" expand to multiple groups)
      - linkedin_url (optional — appended to post text when tagged)
    """
    members = []
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue

        parts = [p.strip() for p in entry.split("|")]
        name       = parts[0] if len(parts) > 0 else ""
        title      = parts[1] if len(parts) > 1 else ""
        department = parts[2] if len(parts) > 2 else ""
        linkedin_url = parts[3] if len(parts) > 3 else ""

        if name:
            members.append({
                "name": name,
                "title": title,
                "department": department,
                "linkedin_url": linkedin_url.rstrip("/"),
            })

    return members


def _build_department_groups(members: list[dict]) -> dict[str, list[dict]]:
    """
    Build a mapping of department → members list.
    Compound departments like "Tech & Vixi" expand the person into each group.
    """
    groups: dict[str, list[dict]] = {}
    for member in members:
        raw_dept = member.get("department", "")
        depts = [d.strip() for d in raw_dept.split("&") if d.strip()]
        if not depts:
            depts = ["Other"]
        for dept in depts:
            groups.setdefault(dept, []).append(member)
    return groups


class Config:
    # LinkedIn App (for posting only)
    LINKEDIN_CLIENT_ID: str = _require("LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET: str = _require("LINKEDIN_CLIENT_SECRET")
    LINKEDIN_REDIRECT_URI: str = os.getenv(
        "LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback"
    )

    # LinkedIn Tokens (filled by oauth_setup.py)
    LINKEDIN_ACCESS_TOKEN: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    LINKEDIN_MEMBER_ID: str = os.getenv("LINKEDIN_MEMBER_ID", "")

    # Source LinkedIn URLs — with optional type prefixes
    # e.g. tfg:https://www.linkedin.com/company/the-famous-group/
    #      inspiration:https://www.linkedin.com/in/someone/
    #      industry:https://www.linkedin.com/company/somecompany/
    _raw_urls: str = os.getenv("SOURCE_LINKEDIN_URLS", "")
    SOURCE_URLS_WITH_TYPES: list
    SOURCE_LINKEDIN_URLS: list  # plain URL list (backward compat)

    # Team members for Discord tagging step
    # Format: "Name|Title|Department|LinkedInURL;Name|Title|Department|LinkedInURL"
    TEAM_MEMBERS: list        # list of dicts: {name, title, department, linkedin_url}
    DEPARTMENT_GROUPS: dict   # department → list of member dicts (compound depts expanded)

    # Google Custom Search (for LinkedIn post discovery)
    GOOGLE_CSE_API_KEY: str = os.getenv("GOOGLE_CSE_API_KEY", "")
    GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "")

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

    def __init__(self):
        typed, plain = _parse_source_urls(self._raw_urls)
        self.SOURCE_URLS_WITH_TYPES = typed
        self.SOURCE_LINKEDIN_URLS = plain
        self.TEAM_MEMBERS = _parse_team_members(os.getenv("TEAM_MEMBERS", ""))
        self.DEPARTMENT_GROUPS = _build_department_groups(self.TEAM_MEMBERS)


config = Config()
