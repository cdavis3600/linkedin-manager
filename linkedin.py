"""
linkedin.py — LinkedIn client.

READING  → OpenAI Responses API with web_search (finds posts on LinkedIn)
WRITING  → LinkedIn official API (posts to your personal profile)
"""
import hashlib
import json
import os
import logging
import requests
import mimetypes
from datetime import datetime, timedelta, timezone
from typing import Optional

from openai import OpenAI

from config import config
from database import save_media, update_media_urn

logger = logging.getLogger(__name__)

LINKEDIN_BASE_URL = "https://api.linkedin.com/v2"

_openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

FETCH_PROMPT = """\
Visit the LinkedIn profile at {linkedin_url} and find the most recent post \
published by this person or company.

Return ONLY a JSON object (no markdown fences, no commentary) with these keys:
- "post_text": the full text of the post (preserve line breaks)
- "post_url": the direct URL to the SPECIFIC post on LinkedIn. This should be \
the activity URL (e.g. https://www.linkedin.com/posts/username_topic-activity-1234567890/) \
NOT the profile page URL. Look for the share/activity link for this particular post.
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


# ─────────────────────────────────────────────
#  Fetch posts via OpenAI web search
# ─────────────────────────────────────────────

def fetch_posts_from_url(linkedin_url: str, hours_back: int = 24) -> list[dict]:
    """
    Fetch the most recent post from a LinkedIn profile or company page
    using OpenAI's Responses API with web search.

    Returns a list with 0 or 1 post dicts matching the pipeline's expected shape.
    """
    prompt = FETCH_PROMPT.format(linkedin_url=linkedin_url)

    try:
        response = _openai_client.responses.create(
            model=config.OPENAI_MODEL,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
    except Exception as e:
        logger.error("OpenAI web search failed for %s: %s", linkedin_url, e)
        return []

    raw_text = _extract_response_text(response)
    if not raw_text:
        logger.warning("Empty response from OpenAI for %s", linkedin_url)
        return []

    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error("Failed to parse JSON from OpenAI response for %s: %s\nRaw: %s",
                      linkedin_url, e, raw_text[:500])
        return []

    post_text = data.get("post_text")
    if not post_text:
        logger.info("No post found by OpenAI for %s", linkedin_url)
        return []

    citation_url = _extract_post_url_from_citations(response)
    json_url = data.get("post_url") or ""
    if citation_url:
        post_url = citation_url
    elif json_url and _POST_URL_RE.search(json_url):
        post_url = json_url.split("?")[0]
    else:
        post_url = linkedin_url

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


import re

_POST_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/"
    r"(?:posts/|feed/update/urn:li:activity:)"
)


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
