"""
scheduler.py — Core pipeline logic + APScheduler setup.

Pipeline (runs daily at configured time):
  1. Fetch recent posts from all source URLs (with source_type per URL)
  2. Deduplicate against DB
  3. Download media
  4. Select/synthesize best post topic (GPT-4)
  5. Generate ONE AI post in CJ's voice (tuned to source_type)
  6. Send Discord approval message
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config
from database import (
    init_db, is_post_processed, insert_post,
    save_variants, get_variant, mark_post_status,
    save_media, update_media_urn
)
from linkedin import (
    fetch_recent_org_posts, download_post_media,
    upload_image_to_linkedin, post_to_linkedin
)
from rewriter import generate_post, generate_approval_summary, select_and_synthesize

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Post callback (called by Discord on approval)
# ─────────────────────────────────────────────

async def handle_post_approved(source_post_id: str, variant_type: str) -> Optional[str]:
    """
    Called when the user approves a post in Discord.
    Uploads media and publishes to LinkedIn.
    Returns the post URN on success, None on failure.
    """
    logger.info("Post approved: %s variant=%s", source_post_id, variant_type)

    post_text = get_variant(source_post_id, variant_type)
    if not post_text:
        logger.error("No text found for variant '%s' of post %s", variant_type, source_post_id)
        mark_post_status(source_post_id, "failed")
        return None

    # Upload any media
    from database import get_media_for_post
    media_rows = get_media_for_post(source_post_id)
    asset_urns = []

    for media in media_rows:
        local_path = media.get("local_path")
        if not local_path or not os.path.exists(local_path):
            continue

        urn = await asyncio.get_event_loop().run_in_executor(
            None, lambda p=local_path: upload_image_to_linkedin(p)
        )
        if urn:
            update_media_urn(source_post_id, media["original_url"], urn)
            asset_urns.append(urn)

    # Post to LinkedIn
    post_urn = await asyncio.get_event_loop().run_in_executor(
        None, lambda: post_to_linkedin(post_text, asset_urns if asset_urns else None)
    )

    if post_urn:
        mark_post_status(source_post_id, "posted", posted_urn=post_urn)
        logger.info("Successfully posted to LinkedIn. URN: %s", post_urn)
        return post_urn
    else:
        mark_post_status(source_post_id, "failed")
        logger.error("Failed to post to LinkedIn for post %s", source_post_id)
        return None


# ─────────────────────────────────────────────
#  Main pipeline (runs on schedule)
# ─────────────────────────────────────────────

async def run_pipeline(bot):
    """Main pipeline: fetch all → dedupe → analyze/synthesize → one daily approval."""
    logger.info("=== Pipeline starting at %s ===", datetime.now(timezone.utc).isoformat())

    # 1. Fetch recent posts from all source URLs (source_type attached per URL)
    posts = await asyncio.get_event_loop().run_in_executor(
        None, fetch_recent_org_posts
    )

    if not posts:
        logger.info("No new posts found from any source.")
        return

    # 2. Deduplicate — keep only posts not yet processed
    new_posts = []
    for post in posts:
        post_id = post["id"]
        if is_post_processed(post_id):
            logger.debug("Skipping already-processed post: %s", post_id)
            continue
        insert_post(post_id, post["text"], post.get("created_at", ""))
        new_posts.append(post)

    if not new_posts:
        logger.info("All fetched posts were already processed.")
        return

    logger.info("Found %d new post(s) across all sources.", len(new_posts))

    # 3. Analyze / synthesize — pick best single post or merge themes
    selection = await asyncio.get_event_loop().run_in_executor(
        None, lambda: select_and_synthesize(new_posts)
    )

    source_text = selection.get("source_text", "")
    if not source_text:
        logger.warning("Topic analysis returned empty source_text. Skipping.")
        return

    source_type = selection.get("source_type", "inspiration")
    post_urls = selection.get("post_urls", [])
    author_names = selection.get("author_names", [])
    mode = selection.get("mode", "single")
    logger.info(
        "Topic analysis: mode=%s, type=%s, sources=%d",
        mode, source_type, len(post_urls)
    )

    # Build a tracking ID — reuse the individual post ID for single mode,
    # or create a composite key for synthesized posts.
    if mode == "single" and len(new_posts) == 1:
        composite_id = new_posts[0]["id"]
    else:
        composite_id = "synth|" + "|".join(sorted(post_urls))
        if is_post_processed(composite_id):
            logger.info("Synthesized post already processed: %s", composite_id[:60])
            return
        insert_post(composite_id, source_text, datetime.now(timezone.utc).isoformat())

    # 4. Download media from all selected source posts
    local_media = []
    for p in new_posts:
        if p.get("post_url") in post_urls and p.get("media_urls"):
            media = await asyncio.get_event_loop().run_in_executor(
                None, lambda mid=p["id"], urls=p["media_urls"]: download_post_media(mid, urls)
            )
            local_media.extend(media)

    # 5. Generate ONE AI post in CJ's voice, tuned to source_type
    source_urls = list({p["source_url"] for p in new_posts if p.get("source_url")})
    logger.info("Generating post (type=%s)...", source_type)

    post_text = await asyncio.get_event_loop().run_in_executor(
        None, lambda: generate_post(
            source_text,
            source_type=source_type,
            post_urls=post_urls,
            author_names=author_names,
            source_urls=source_urls,
        )
    )

    summary = await asyncio.get_event_loop().run_in_executor(
        None, lambda: generate_approval_summary(source_text, post_text)
    )

    # Save single "post" variant
    save_variants(composite_id, {"post": post_text})

    # 6. Send ONE Discord approval message
    from discord_bot import send_approval_message
    try:
        await send_approval_message(
            bot=bot,
            source_post_id=composite_id,
            source_text=source_text,
            post_text=post_text,
            source_type=source_type,
            summary=summary,
            media_count=len(local_media),
            source_urls=post_urls,
            source_authors=author_names,
        )
    except Exception as e:
        logger.error("Failed to send Discord approval: %s", e)
        mark_post_status(composite_id, "failed")

    logger.info("=== Pipeline complete. Sent 1 daily post for approval. ===")


# ─────────────────────────────────────────────
#  Scheduler setup
# ─────────────────────────────────────────────

def create_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        func=run_pipeline,
        trigger=CronTrigger(
            hour=config.SCHEDULE_HOUR,
            minute=config.SCHEDULE_MINUTE,
            timezone=config.TIMEZONE,
        ),
        args=[bot],
        id="linkedin_pipeline",
        name="Daily LinkedIn Post Pipeline",
        replace_existing=True,
        misfire_grace_time=3600,  # run even if missed by up to 1 hour
    )
    logger.info(
        "Scheduler set for %02d:%02d %s",
        config.SCHEDULE_HOUR, config.SCHEDULE_MINUTE, config.TIMEZONE
    )
    return scheduler
