"""
main.py — Entry point for the LinkedIn Manager bot.

Usage:
  python main.py          # Run normally (bot + scheduler)
  python main.py --now    # Run the pipeline immediately (for testing)
"""
import asyncio
import logging
import sys
import os

from config import config
from database import init_db
from discord_bot import LinkedInBot, register_commands
from scheduler import create_scheduler, run_pipeline, handle_post_approved

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
os.makedirs("data/logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/logs/linkedin_manager.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Main async entrypoint
# ─────────────────────────────────────────────

async def main():
    run_now = "--now" in sys.argv

    # 1. Init database
    init_db()
    logger.info("Database initialized.")

    # 2. Create bot with post callback
    bot = LinkedInBot(post_callback=handle_post_approved)
    register_commands(bot)

    # 3. Create scheduler and expose it on the bot for Discord commands
    scheduler = create_scheduler(bot)
    bot.scheduler = scheduler

    async with bot:
        await bot.login(config.DISCORD_BOT_TOKEN)

        # Start the scheduler
        scheduler.start()
        logger.info("Scheduler started.")

        # Start bot in background
        bot_task = asyncio.create_task(bot.connect())

        # Wait for bot to be ready
        await bot.wait_until_bot_ready()
        logger.info("Bot is ready.")

        if run_now:
            logger.info("--now flag detected. Running pipeline immediately.")
            await run_pipeline(bot)

        # Keep running until interrupted
        try:
            await bot_task
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
        finally:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down. Goodbye!")
