"""
linkedin.py — LinkedIn client.

READING  → Brave Search finds post URLs + OpenAI reads content (two-step)
         → Falls back to OpenAI-only web_search if Brave not configured
WRITING  → LinkedIn official API (posts to your personal profile)
"""
import hashlib
import json
import os
import logging
import re
import requests
import mimetypes
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from openai import OpenAI

from config import config
from database import save_media, update_media_urn

logger = logging.getLogger(__name__)

LINKEDIN_BASE_URL = "https://api.linkedin.com/v2"

_openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

_POST_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/"
    r"(?:posts/|feed/update/urn:li:activity:)"
)

_ACTIVITY_ID_RE = re.compile(r"activity[:-](\d+)")
_UGCPOST_ID_RE = re.compile(r"ugcPost[:-](\d+)")

LINKEDIN_REST_URL = "https://api.linkedin.com/rest"

# Used when we already have a specific post URL (from Brave Search or user paste)
READ_POST_PROMPT = """\
Visit this LinkedIn post: {post_url}

Read the FULL text of the post. Return ONLY a JSON object (no markdown fences, \
no commentary) with these keys:
- "post_text": the full text of the post (preserve line breaks)
- "post_url": "{post_url}"
- "author_name": the name of the person or company who wrote it
- "post_date": the date of the post in ISO 8601 format (YYYY-MM-DD), or null if unknown

If the post cannot be read, return: {{"post_text": null}}
"""

# Fallback: used when Brave Search is not configured
FETCH_PROMPT = """\
Today is {today}. Visit the LinkedIn profile at {linkedin_url} and find the \
MOST RECENT post published by this person or company. It should be from the \
last 1-2 days. Do NOT return older posts if a newer one exists.

CRITICAL — you MUST return the direct URL to the SPECIFIC post, not the \
profile or company page URL. The URL must contain "activity-" or "ugcPost-" \
followed by a numeric ID.

Correct post URL examples:
  https://www.linkedin.com/posts/username_topic-activity-7430263630484480000-XXXX
  https://www.linkedin.com/posts/username_topic-ugcPost-7434979636482101250-XXXX
  https://www.linkedin.com/feed/update/urn:li:activity:7430263630484480000/

WRONG (do NOT return these):
  https://www.linkedin.com/company/the-famous-group/
  https://www.linkedin.com/in/someone/

Return ONLY a JSON object (no markdown fences, no commentary) with these keys:
- "post_text": the full text of the post (preserve line breaks)
- "post_url": the direct URL to the specific post (must contain activity- or ugcPost-)
- "author_name": the name of the person or company
- "post_date": the date of the post in ISO 8601 format (YYYY-MM-DD), or null if unknown

If you cannot find any recent post, return: {{"post_text": null}}
"""


def _li_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _is_specific_post_url(url: str) -> bool:
    """True if the URL points to a specific LinkedIn post (not a profile/company page)."""
    return bool(_ACTIVITY_ID_RE.search(url) or _UGCPOST_ID_RE.search(url))


def _extract_slug(linkedin_url: str) -> str:
    """
    Extract the LinkedIn slug from a profile or company page URL.
    /company/the-famous-group/ → the-famous-group
    /in/jacob-woerther/        → jacob-woerther
    """
    path = urlparse(linkedin_url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[-1]
    return parts[0] if parts else ""


# ─────────────────────────────────────────────
#  Step 1: Brave Search — find the latest post URL
# ─────────────────────────────────────────────

def _brave_find_latest_post(linkedin_url: str) -> Optional[str]:
    """
    Use Brave Search API to find the most recent LinkedIn post
    from a profile or company page. Returns a post URL or None.
    """
    if not config.BRAVE_SEARCH_API_KEY:
        return None

    slug = _extract_slug(linkedin_url)
    if not slug:
        logger.warning("Could not extract slug from %s", linkedin_url)
        return None

    query = f"site:linkedin.com/posts/{slug}"
    logger.info("Brave Search: %s", query)

    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": query,
                "count": 5,
                "freshness": "pw",
            },
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": config.BRAVE_SEARCH_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Brave Search request failed: %s", e)
        return None

    results = data.get("web", {}).get("results", [])
    if not results:
        logger.info("Brave Search returned no results for: %s", query)
        return None

    for result in results:
        link = result.get("url", "")
        if _POST_URL_RE.search(link) and _is_specific_post_url(link):
            clean_url = link.split("?")[0]
            logger.info("Brave Search found post: %s", clean_url)
            return clean_url

    logger.info("Brave Search results didn't contain a valid post URL for: %s", query)
    return None


# ─────────────────────────────────────────────
#  Step 2: OpenAI — read content from a known URL
# ─────────────────────────────────────────────

def _openai_read_post(post_url: str) -> Optional[dict]:
    """
    Use OpenAI web search to read the content of a specific LinkedIn post URL.
    Returns parsed JSON dict or None.
    """
    prompt = READ_POST_PROMPT.format(post_url=post_url)

    try:
        response = _openai_client.responses.create(
            model=config.OPENAI_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
    except Exception as e:
        logger.error("OpenAI read-post failed for %s: %s", post_url, e)
        return None

    raw_text = _extract_response_text(response)
    if not raw_text:
        logger.warning("Empty OpenAI response when reading %s", post_url)
        return None

    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse JSON from OpenAI for %s: %s\nRaw: %s",
                      post_url, e, raw_text[:500])
        return None

    if not data.get("post_text"):
        return None

    data["post_url"] = post_url
    return data


# ─────────────────────────────────────────────
#  Fallback: OpenAI-only search+read (original method)
# ─────────────────────────────────────────────

def _openai_search_and_read(linkedin_url: str) -> Optional[tuple[dict, object]]:
    """
    Original single-step approach: ask OpenAI to find AND read the latest post.
    Returns (parsed_data, response_obj) or None.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = FETCH_PROMPT.format(linkedin_url=linkedin_url, today=today)

    try:
        response = _openai_client.responses.create(
            model=config.OPENAI_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
    except Exception as e:
        logger.error("OpenAI web search failed for %s: %s", linkedin_url, e)
        return None

    raw_text = _extract_response_text(response)
    if not raw_text:
        logger.warning("Empty response from OpenAI for %s", linkedin_url)
        return None

    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse JSON from OpenAI for %s: %s\nRaw: %s",
                      linkedin_url, e, raw_text[:500])
        return None

    if not data.get("post_text"):
        return None

    citation_url = _extract_post_url_from_citations(response)
    json_url = data.get("post_url") or ""
    if citation_url:
        data["post_url"] = citation_url
    elif json_url and _POST_URL_RE.search(json_url):
        data["post_url"] = json_url.split("?")[0]
    else:
        data["post_url"] = linkedin_url
        logger.warning(
            "No specific post URL found for %s — falling back to profile URL. "
            "Reshare will not be available for this post.", linkedin_url
        )

    return (data, response)


# ─────────────────────────────────────────────
#  Main entry point: fetch posts from URL
# ─────────────────────────────────────────────

def fetch_posts_from_url(linkedin_url: str, hours_back: int = 24) -> list[dict]:
    """
    Fetch the most recent post from a LinkedIn profile or company page.

    Strategy:
      1. If URL is already a specific post → read it directly with OpenAI
      2. If Brave Search is configured → find URL via Brave, then read with OpenAI
      3. Fallback → original OpenAI search+read in one step
    """
    data = None

    if _is_specific_post_url(linkedin_url):
        logger.info("URL is a specific post, reading directly: %s", linkedin_url[:80])
        data = _openai_read_post(linkedin_url)
    elif config.BRAVE_SEARCH_API_KEY:
        post_url = _brave_find_latest_post(linkedin_url)
        if post_url:
            logger.info("Brave found post, reading with OpenAI: %s", post_url[:80])
            data = _openai_read_post(post_url)
        else:
            logger.info("Brave found nothing for %s, falling back to OpenAI search",
                        linkedin_url[:60])
            result = _openai_search_and_read(linkedin_url)
            if result:
                data = result[0]
    else:
        logger.info("Brave Search not configured, using OpenAI search for %s", linkedin_url[:60])
        result = _openai_search_and_read(linkedin_url)
        if result:
            data = result[0]

    if not data:
        logger.info("No post found for %s", linkedin_url)
        return []

    post_text = data.get("post_text", "")
    post_url = data.get("post_url", linkedin_url)
    author = data.get("author_name") or ""
    post_date_str = data.get("post_date") or ""

    if post_date_str and hours_back:
        try:
            post_dt = datetime.fromisoformat(post_date_str).replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            if post_dt < cutoff:
                logger.info("Post from %s is older than %dh, skipping.", linkedin_url, hours_back)
                return []
        except ValueError:
            pass

    text_hash = hashlib.sha256(post_text.encode()).hexdigest()[:16]
    post = {
        "id": f"{linkedin_url}#{text_hash}",
        "text": post_text,
        "post_url": post_url,
        "author_name": author,
        "media_urls": [],
        "created_at": post_date_str,
        "source_url": linkedin_url,
    }
    logger.info("Found post from %s (%s): %.80s...", linkedin_url, author, post_text)
    return [post]


def _extract_response_text(response) -> Optional[str]:
    """Pull the assistant's text from a Responses API result."""
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if block.type == "output_text":
                    return block.text
    return None


def _extract_post_url_from_citations(response) -> Optional[str]:
    """Extract a real LinkedIn post URL from web search citation annotations."""
    for item in response.output:
        if item.type == "message":
            for block in item.content:
                if block.type == "output_text" and hasattr(block, "annotations"):
                    for ann in block.annotations:
                        if ann.type == "url_citation" and _POST_URL_RE.search(ann.url):
                            url = ann.url.split("?")[0]
                            logger.info("Extracted post URL from citation: %s", url)
                            return url
    return None


def fetch_recent_org_posts(hours_back: int = 24) -> list[dict]:
    """
    Fetch posts from all SOURCE_LINKEDIN_URLS configured in .env.
    Supports any mix of company pages and personal profiles.
    Attaches source_type to each returned post dict.
    """
    all_posts = []
    for entry in config.SOURCE_URLS_WITH_TYPES:
        url = entry["url"].strip()
        source_type = entry.get("source_type", "inspiration")
        if url:
            posts = fetch_posts_from_url(url, hours_back=hours_back)
            for p in posts:
                p["source_type"] = source_type
            all_posts.extend(posts)
    return all_posts[:config.MAX_POSTS_PER_RUN]


# ─────────────────────────────────────────────
#  Download media locally
# ─────────────────────────────────────────────

def download_post_media(post_id: str, media_urls: list[str]) -> list[str]:
    os.makedirs(config.MEDIA_DIR, exist_ok=True)
    local_paths = []
    for i, url in enumerate(media_urls):
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            ext = _guess_extension(url, resp.headers.get("Content-Type", ""))
            safe_id = post_id.replace(":", "_").replace(",", "_").replace("/", "_")[:60]
            filename = f"{safe_id}_img{i}{ext}"
            path = os.path.join(config.MEDIA_DIR, filename)
            with open(path, "wb") as f:
                f.write(resp.content)
            save_media(post_id, url, local_path=path)
            local_paths.append(path)
            logger.info("Downloaded media: %s → %s", url[:60], path)
        except Exception as e:
            logger.warning("Failed to download media %s: %s", url[:60], e)
            save_media(post_id, url)
    return local_paths


def _guess_extension(url: str, content_type: str) -> str:
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
    if ext and ext != ".jpe":
        return ext
    if ".jpg" in url or ".jpeg" in url:
        return ".jpg"
    if ".png" in url:
        return ".png"
    if ".gif" in url:
        return ".gif"
    return ".jpg"


# ─────────────────────────────────────────────
#  Upload media to LinkedIn
# ─────────────────────────────────────────────

def upload_image_to_linkedin(local_path: str) -> Optional[str]:
    member_urn = f"urn:li:person:{config.LINKEDIN_MEMBER_ID}"
    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": member_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ]
        }
    }
    try:
        reg_resp = requests.post(
            f"{LINKEDIN_BASE_URL}/assets?action=registerUpload",
            headers=_li_headers(), json=register_payload, timeout=15
        )
        reg_resp.raise_for_status()
        reg_data = reg_resp.json()
        upload_url = reg_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = reg_data["value"]["asset"]
    except Exception as e:
        logger.error("Failed to register LinkedIn upload: %s", e)
        return None

    try:
        with open(local_path, "rb") as f:
            img_data = f.read()
        up_resp = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
                     "Content-Type": "application/octet-stream"},
            data=img_data, timeout=30
        )
        up_resp.raise_for_status()
        logger.info("Uploaded image to LinkedIn: %s → %s", local_path, asset_urn)
        return asset_urn
    except Exception as e:
        logger.error("Failed to upload image binary: %s", e)
        return None


# ─────────────────────────────────────────────
#  Post to personal LinkedIn profile
# ─────────────────────────────────────────────

def post_to_linkedin(text: str, asset_urns: Optional[list[str]] = None) -> Optional[str]:
    member_urn = f"urn:li:person:{config.LINKEDIN_MEMBER_ID}"
    if asset_urns:
        share_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "IMAGE",
            "media": [
                {"status": "READY", "description": {"text": ""},
                 "media": urn, "title": {"text": ""}}
                for urn in asset_urns
            ],
        }
    else:
        share_content = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE",
        }

    payload = {
        "author": member_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }

    try:
        resp = requests.post(
            f"{LINKEDIN_BASE_URL}/ugcPosts",
            headers=_li_headers(), json=payload, timeout=15
        )
        resp.raise_for_status()
        post_urn = resp.headers.get("X-RestLi-Id") or resp.json().get("id")
        logger.info("Posted to LinkedIn. URN: %s", post_urn)
        return post_urn
    except requests.HTTPError as e:
        logger.error("Failed to post to LinkedIn: %s — %s", e, resp.text)
        return None


def extract_share_urn(url: str) -> Optional[str]:
    """
    Extract a post URN from a LinkedIn post URL.
    Returns urn:li:ugcPost:ID for ugcPost URLs, urn:li:activity:ID for activity URLs.
    """
    match = _UGCPOST_ID_RE.search(url)
    if match:
        return f"urn:li:ugcPost:{match.group(1)}"
    match = _ACTIVITY_ID_RE.search(url)
    if match:
        return f"urn:li:activity:{match.group(1)}"
    return None


def _rest_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Linkedin-Version": "202601",
        "Content-Type": "application/json",
    }


def _build_reshare_payload(text: str, member_urn: str, parent_urn: str) -> dict:
    return {
        "author": member_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
        "reshareContext": {"parent": parent_urn},
    }


def reshare_to_linkedin(text: str, share_urn: str) -> Optional[str]:
    """
    Reshare an existing LinkedIn post with commentary using the Posts API.
    Tries multiple URN formats if the first attempt gets a 403 or 422.
    """
    member_urn = f"urn:li:person:{config.LINKEDIN_MEMBER_ID}"

    _id_match = re.search(r"urn:li:\w+:(\d+)", share_urn)
    if not _id_match:
        logger.error("Invalid URN format: %s", share_urn)
        return None
    numeric_id = _id_match.group(1)

    urn_formats = [
        share_urn,
        f"urn:li:ugcPost:{numeric_id}",
        f"urn:li:share:{numeric_id}",
        f"urn:li:activity:{numeric_id}",
    ]
    seen = set()
    unique_urns = [u for u in urn_formats if u not in seen and not seen.add(u)]

    for urn in unique_urns:
        payload = _build_reshare_payload(text, member_urn, urn)
        try:
            resp = requests.post(
                f"{LINKEDIN_REST_URL}/posts",
                headers=_rest_headers(), json=payload, timeout=15,
            )
            resp.raise_for_status()
            post_urn = resp.headers.get("x-restli-id") or resp.json().get("id")
            logger.info("Reshared to LinkedIn. URN: %s (parent: %s)", post_urn, urn)
            return post_urn
        except requests.HTTPError as e:
            logger.warning("Reshare failed with %s: %s — %s", urn, e, resp.text[:200])
            if resp.status_code not in (403, 422):
                break

    logger.error("All reshare URN formats failed for ID %s", numeric_id)
    return None


def get_member_id(access_token: str) -> Optional[str]:
    try:
        resp = requests.get(
            f"{LINKEDIN_BASE_URL}/me",
            headers={"Authorization": f"Bearer {access_token}",
                     "X-Restli-Protocol-Version": "2.0.0"},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        logger.error("Failed to fetch member ID: %s", e)
        return None
