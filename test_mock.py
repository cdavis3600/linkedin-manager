"""
test_mock.py — End-to-end mock test for the LinkedIn Manager.

What this does:
  1. Starts the Discord bot (real connection)
  2. Injects a fake source post (no LinkedIn fetch, no OpenAI web search)
  3. Runs the REAL GPT-4 rewriter so you can evaluate CJ's voice and tone
  4. Sends the REAL Discord approval message with all buttons + team tagging
  5. On approval: prints the final post text to terminal instead of posting to LinkedIn

Usage:
  python3 test_mock.py              # tfg post (default)
  python3 test_mock.py inspiration  # inspiration post
  python3 test_mock.py industry     # industry news post
  python3 test_mock.py --post       # actually post to LinkedIn on approval

This is safe to run repeatedly — it uses a unique mock post ID each time
so deduplication won't block it.
"""
import asyncio
import logging
import sys
import os
import uuid
from datetime import datetime, timezone

from config import config
from database import init_db, insert_post, save_variants, mark_post_status
from discord_bot import LinkedInBot, register_commands, send_approval_message
from rewriter import generate_post, generate_approval_summary
from scheduler import handle_post_approved

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Mock source posts — one per type
# ─────────────────────────────────────────────

MOCK_POSTS = {
    "tfg": {
        "source_text": (
            "The Famous Group just wrapped an incredible real-time LED volume shoot "
            "for a major automotive brand. Our team built a fully custom Unreal Engine "
            "environment — 200 million polygons, dynamic lighting, and zero post compositing. "
            "The client was on set watching live playback that looked like final delivery. "
            "Proud of what this crew pulled off in 6 days of prep and 2 days of shooting."
        ),
        "post_url": "https://www.linkedin.com/posts/the-famous-group_ledvolume-activity-mock",
        "author_name": "The Famous Group",
        "source_url": "https://www.linkedin.com/company/the-famous-group/",
    },
    "inspiration": {
        "source_text": (
            "Really interesting thread from @AndrewNg today on the difference between "
            "AI tools that augment human creativity vs. ones that replace the creative "
            "decision entirely. His framing: the best AI products keep the human in the "
            "loop for judgment calls, not just approvals. Agree more than I expected to."
        ),
        "post_url": "https://www.linkedin.com/posts/andrewyng_ai-creativity-activity-mock",
        "author_name": "Andrew Ng",
        "source_url": "https://www.linkedin.com/in/andrewyng/",
    },
    "industry": {
        "source_text": (
            "New report from PQ Media: live entertainment technology spend is projected "
            "to hit $4.2B by 2027, driven almost entirely by LED volume stages and "
            "real-time rendering pipelines. Three years ago this market barely existed "
            "as a line item. The convergence of game engine tech and broadcast production "
            "is happening faster than anyone predicted."
        ),
        "post_url": "https://www.linkedin.com/posts/pqmedia_liveentertainment-activity-mock",
        "author_name": "PQ Media",
        "source_url": "https://www.linkedin.com/company/pq-media/",
    },
}


# ─────────────────────────────────────────────
#  Mock post callback — prints instead of posting
# ─────────────────────────────────────────────

def make_mock_post_callback(actually_post: bool):
    async def mock_post_approved(source_post_id: str, variant_type: str) -> str:
        from database import get_variant
        text = get_variant(source_post_id, variant_type) or "(no text found)"

        print("\n" + "═" * 60)
        print("🧪 MOCK TEST — Final post that would go to LinkedIn:")
        print("═" * 60)
        print(text)
        print("═" * 60 + "\n")

        if actually_post:
            logger.info("--post flag set. Calling real LinkedIn post API...")
            return await handle_post_approved(source_post_id, variant_type)
        else:
            # Simulate success without hitting LinkedIn
            mock_urn = f"urn:li:ugcPost:mock_{uuid.uuid4().hex[:8]}"
            mark_post_status(source_post_id, "posted", posted_urn=mock_urn)
            logger.info("Mock post complete. Fake URN: %s", mock_urn)
            return mock_urn

    return mock_post_approved


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

async def main():
    # Parse args
    args = sys.argv[1:]
    source_type = "tfg"
    actually_post = False
    for arg in args:
        if arg in MOCK_POSTS:
            source_type = arg
        elif arg == "--post":
            actually_post = True

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    mock = MOCK_POSTS[source_type]
    post_id = f"mock_{source_type}_{uuid.uuid4().hex[:8]}"

    print(f"\n🧪 Mock test — type: {source_type}  |  post_id: {post_id}")
    print(f"   Actually post to LinkedIn: {actually_post}")
    print(f"   Source text: {mock['source_text'][:80]}...\n")

    # Init DB
    init_db()
    insert_post(post_id, mock["source_text"], datetime.now(timezone.utc).isoformat())

    # Generate post with real GPT-4
    print("⏳ Generating post with GPT-4...\n")
    post_text = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: generate_post(
            mock["source_text"],
            source_type=source_type,
            post_urls=[mock["post_url"]],
            author_names=[mock["author_name"]],
            source_urls=[mock["source_url"]],
        )
    )
    summary = await asyncio.get_event_loop().run_in_executor(
        None, lambda: generate_approval_summary(mock["source_text"], post_text)
    )

    print("✅ Generated post:")
    print("-" * 50)
    print(post_text)
    print("-" * 50 + "\n")

    save_variants(post_id, {"post": post_text})

    # Start Discord bot and send approval message
    post_callback = make_mock_post_callback(actually_post)
    bot = LinkedInBot(post_callback=post_callback)
    register_commands(bot)

    async with bot:
        await bot.login(config.DISCORD_BOT_TOKEN)
        bot_task = asyncio.create_task(bot.connect())
        await bot.wait_until_bot_ready()

        print("📨 Sending to Discord for approval...\n")
        await send_approval_message(
            bot=bot,
            source_post_id=post_id,
            source_text=mock["source_text"],
            post_text=post_text,
            source_type=source_type,
            summary=summary,
            media_count=0,
            source_urls=[mock["post_url"]],
            source_authors=[mock["author_name"]],
        )

        print("✅ Approval message sent to Discord.")
        print("   → Go approve/regenerate/tag in Discord.")
        print("   → Press Ctrl+C here when done.\n")

        try:
            await bot_task
        except (KeyboardInterrupt, SystemExit):
            print("\n👋 Test session ended.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down.")
