"""
test_discord.py — Isolated Discord bot test.

Tests bot login, channel access, approval embed + buttons, and commands
without touching Proxycurl, OpenAI, or LinkedIn APIs.

Usage:
    python3 test_discord.py
"""
import asyncio
import logging
import sys
import os
from datetime import datetime

from config import config
from database import init_db, insert_post, save_variants
from discord_bot import LinkedInBot, register_commands, send_approval_message

os.makedirs("data/logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_discord")

FAKE_POST_ID = f"test-discord-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

FAKE_VARIANTS = {
    "personal": (
        "Just saw something exciting from our team — we shipped a brand-new "
        "feature that lets creators schedule posts with one click. Proud of "
        "what this crew pulled off in just two sprints.\n\n#product #teamwork"
    ),
    "shorter": (
        "New feature alert: one-click post scheduling is live. Two sprints, "
        "zero drama. #shipping"
    ),
    "technical": (
        "We built an async job queue on top of Redis + APScheduler to power "
        "one-click post scheduling. Batched writes to the LinkedIn API keep "
        "us well under rate limits while handling bursty traffic.\n\n"
        "#engineering #architecture"
    ),
}

FAKE_SOURCE_TEXT = (
    "The Famous Group is thrilled to announce our new one-click scheduling "
    "feature for content creators, built in just two sprints by our product "
    "engineering team."
)


async def fake_post_callback(source_post_id: str, variant_type: str):
    """Stub that logs instead of posting to LinkedIn."""
    logger.info(
        "STUB: Would post '%s' variant for post '%s' to LinkedIn (no-op)",
        variant_type,
        source_post_id,
    )


async def main():
    logger.info("=== Discord Isolated Test ===")

    init_db()
    logger.info("Database initialized.")

    insert_post(FAKE_POST_ID, FAKE_SOURCE_TEXT, datetime.utcnow().isoformat())
    save_variants(FAKE_POST_ID, FAKE_VARIANTS)
    logger.info("Inserted fake post '%s' with 3 variants.", FAKE_POST_ID)

    bot = LinkedInBot(post_callback=fake_post_callback)
    register_commands(bot)

    async with bot:
        await bot.login(config.DISCORD_BOT_TOKEN)
        bot_task = asyncio.create_task(bot.connect())
        await bot.wait_until_bot_ready()
        logger.info("Bot is ready — sending test approval message...")

        msg = await send_approval_message(
            bot=bot,
            source_post_id=FAKE_POST_ID,
            source_text=FAKE_SOURCE_TEXT,
            variants=FAKE_VARIANTS,
            summary="Test post: one-click scheduling feature announcement",
            media_count=0,
        )

        if msg:
            logger.info("SUCCESS — Approval message sent (msg ID: %s)", msg.id)
            logger.info(
                "Check your Discord DM. Try the buttons and !status / !pending."
            )
            logger.info("Press Ctrl+C to stop the bot when done testing.")
        else:
            logger.error("FAILED — Could not send approval message.")
            return

        try:
            await bot_task
        except (KeyboardInterrupt, SystemExit):
            pass

    logger.info("Test complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest stopped.")
