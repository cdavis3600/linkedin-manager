"""
database.py — SQLite operations for deduplication, post history, and pending approvals.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime
from typing import Optional

from config import config

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS processed_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_post_id TEXT UNIQUE NOT NULL,
                source_text TEXT,
                fetched_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                -- status: pending | approved | posted | skipped | failed
                approved_variant TEXT,
                posted_at TEXT,
                posted_urn TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS post_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_post_id TEXT NOT NULL,
                variant_type TEXT NOT NULL,  -- personal | shorter | technical
                content TEXT NOT NULL,
                discord_message_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (source_post_id) REFERENCES processed_posts(source_post_id)
            );

            CREATE TABLE IF NOT EXISTS media_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_post_id TEXT NOT NULL,
                original_url TEXT NOT NULL,
                local_path TEXT,
                linkedin_asset_urn TEXT,
                downloaded_at TEXT,
                FOREIGN KEY (source_post_id) REFERENCES processed_posts(source_post_id)
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
    logger.info("Database initialized at %s", config.DB_PATH)


def get_setting(key: str, default: str = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO bot_settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')""",
            (key, value, value)
        )


def is_post_processed(source_post_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM processed_posts WHERE source_post_id = ?",
            (source_post_id,)
        ).fetchone()
        return row is not None


def insert_post(source_post_id: str, source_text: str, fetched_at: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO processed_posts
               (source_post_id, source_text, fetched_at, status)
               VALUES (?, ?, ?, 'pending')""",
            (source_post_id, source_text, fetched_at)
        )


def save_variants(source_post_id: str, variants: dict, discord_message_id: Optional[str] = None):
    """Save all AI-generated variants for a post."""
    with get_connection() as conn:
        for variant_type, content in variants.items():
            conn.execute(
                """INSERT INTO post_variants
                   (source_post_id, variant_type, content, discord_message_id)
                   VALUES (?, ?, ?, ?)""",
                (source_post_id, variant_type, content, discord_message_id)
            )


def get_variant(source_post_id: str, variant_type: str) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT content FROM post_variants WHERE source_post_id = ? AND variant_type = ?",
            (source_post_id, variant_type)
        ).fetchone()
        return row["content"] if row else None


def update_variant(source_post_id: str, variant_type: str, content: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO post_variants
               (source_post_id, variant_type, content)
               VALUES (?, ?, ?)""",
            (source_post_id, variant_type, content)
        )


def mark_post_status(source_post_id: str, status: str,
                     approved_variant: Optional[str] = None,
                     posted_urn: Optional[str] = None):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """UPDATE processed_posts
               SET status = ?,
                   approved_variant = COALESCE(?, approved_variant),
                   posted_urn = COALESCE(?, posted_urn),
                   posted_at = CASE WHEN ? = 'posted' THEN ? ELSE posted_at END
               WHERE source_post_id = ?""",
            (status, approved_variant, posted_urn, status, now, source_post_id)
        )


def save_media(source_post_id: str, original_url: str, local_path: Optional[str] = None):
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO media_files
               (source_post_id, original_url, local_path, downloaded_at)
               VALUES (?, ?, ?, ?)""",
            (source_post_id, original_url, local_path,
             datetime.utcnow().isoformat() if local_path else None)
        )


def update_media_urn(source_post_id: str, original_url: str, asset_urn: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE media_files SET linkedin_asset_urn = ? WHERE source_post_id = ? AND original_url = ?",
            (asset_urn, source_post_id, original_url)
        )


def get_media_for_post(source_post_id: str) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM media_files WHERE source_post_id = ?",
            (source_post_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_posts() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM processed_posts WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_post_history(limit: int = 20) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM processed_posts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
