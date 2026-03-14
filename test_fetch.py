"""
test_fetch.py — Isolated test for OpenAI web-search-based LinkedIn post fetching.

Validates that the Responses API + web_search can find posts from configured
SOURCE_LINKEDIN_URLS. Does NOT trigger Discord or LinkedIn posting.

Usage:
    python3 test_fetch.py
"""
import logging
import sys

from config import config
from linkedin import fetch_posts_from_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_fetch")

HOURS_BACK = 168  # 7 days


def main():
    logger.info("=== OpenAI Web Search Fetch Test ===")
    logger.info("Model: %s", config.OPENAI_MODEL)

    urls = config.SOURCE_LINKEDIN_URLS
    if not urls:
        logger.error("FAIL — SOURCE_LINKEDIN_URLS is empty in .env")
        return

    logger.info("Configured source URLs (%d):", len(urls))
    for i, url in enumerate(urls, 1):
        logger.info("  %d. %s", i, url)

    all_ok = True

    for url in urls:
        logger.info("--- Fetching from: %s (last %d hours) ---", url, HOURS_BACK)
        posts = fetch_posts_from_url(url, hours_back=HOURS_BACK)

        if posts is None:
            logger.error("FAIL — fetch_posts_from_url returned None for %s", url)
            all_ok = False
            continue

        logger.info("Found %d post(s) from %s", len(posts), url)

        for j, post in enumerate(posts, 1):
            text_preview = post["text"][:300].replace("\n", " ")
            author = post.get("author_name", "unknown")
            post_url = post.get("post_url", "N/A")
            created = post.get("created_at", "unknown")

            logger.info("  Post %d:", j)
            logger.info("    Author:  %s", author)
            logger.info("    Date:    %s", created)
            logger.info("    Link:    %s", post_url)
            logger.info("    Text:    %s...", text_preview)

        if not posts:
            logger.warning(
                "0 posts in the last %d hours from %s", HOURS_BACK, url
            )

    logger.info("=== Test complete. %s ===", "ALL PASSED" if all_ok else "SOME FAILED")


if __name__ == "__main__":
    main()
