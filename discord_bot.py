"""
discord_bot.py — Discord bot for LinkedIn post approval workflow.

Flow:
  1. Bot sends an embed to the approval channel with 3 post variants + action buttons.
  2. User clicks a button or types a command:
       ✅ Approve Personal    → posts the "personal" variant
       📏 Use Shorter         → posts the "shorter" variant
       🔧 Use Technical       → posts the "technical" variant
       ✏️  Regenerate          → modal/prompt for feedback, regenerates
       ⏭  Skip                → marks post as skipped
  3. Bot confirms the action in Discord.
"""
import asyncio
import logging
import discord
from discord.ext import commands
from discord import app_commands
from typing import Callable, Awaitable, Optional

from config import config
from database import (
    mark_post_status, get_variant, update_variant,
    get_post_history, get_pending_posts
)
from rewriter import regenerate_with_feedback

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Discord UI Views (buttons)
# ─────────────────────────────────────────────

class ApprovalView(discord.ui.View):
    """Interactive buttons for approving/rejecting a post."""

    def __init__(
        self,
        source_post_id: str,
        source_text: str,
        on_post_callback: Callable[[str, str], Awaitable[None]],
        timeout: float = 3600 * 12,  # 12 hours
    ):
        super().__init__(timeout=timeout)
        self.source_post_id = source_post_id
        self.source_text = source_text
        self.on_post = on_post_callback
        self.acted = False

    async def _disable_all(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="✅ Approve Personal", style=discord.ButtonStyle.success, row=0)
    async def approve_personal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_approve(interaction, "personal")

    @discord.ui.button(label="📏 Use Shorter", style=discord.ButtonStyle.primary, row=0)
    async def use_shorter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_approve(interaction, "shorter")

    @discord.ui.button(label="🔧 Use Technical", style=discord.ButtonStyle.secondary, row=0)
    async def use_technical(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_approve(interaction, "technical")

    @discord.ui.button(label="✏️ Regenerate", style=discord.ButtonStyle.secondary, row=1)
    async def regenerate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            RegenerateModal(
                source_post_id=self.source_post_id,
                source_text=self.source_text,
                on_post=self.on_post,
                parent_view=self,
            )
        )

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.danger, row=1)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.acted:
            await interaction.response.send_message("Already handled.", ephemeral=True)
            return
        self.acted = True
        mark_post_status(self.source_post_id, "skipped")
        await self._disable_all(interaction)
        await interaction.response.send_message(
            f"⏭ Skipped post `{self.source_post_id[:30]}...`", ephemeral=False
        )

    async def _handle_approve(self, interaction: discord.Interaction, variant_type: str):
        if self.acted:
            await interaction.response.send_message("Already handled.", ephemeral=True)
            return
        self.acted = True
        content = get_variant(self.source_post_id, variant_type)
        if not content:
            await interaction.response.send_message(
                f"⚠️ Could not find '{variant_type}' variant.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🚀 Posting **{variant_type}** variant to LinkedIn...", ephemeral=False
        )
        await self._disable_all(interaction)
        mark_post_status(self.source_post_id, "approved", approved_variant=variant_type)
        result = await self.on_post(self.source_post_id, variant_type)
        if result:
            await interaction.followup.send("✅ Posted to LinkedIn successfully.")
        else:
            await interaction.followup.send("❌ Failed to post to LinkedIn. Check logs for details.")

    async def on_timeout(self):
        # Auto-skip if no response
        if not self.acted:
            mark_post_status(self.source_post_id, "skipped")
            logger.info("Post %s auto-skipped after approval timeout.", self.source_post_id)


class RegenerateModal(discord.ui.Modal, title="Regenerate Post"):
    feedback = discord.ui.TextInput(
        label="What should change?",
        placeholder='e.g. "make it more inspiring", "more technical detail", "shorter and punchier"',
        style=discord.TextStyle.paragraph,
        max_length=300,
    )

    def __init__(
        self,
        source_post_id: str,
        source_text: str,
        on_post: Callable,
        parent_view: "ApprovalView",
    ):
        super().__init__()
        self.source_post_id = source_post_id
        self.source_text = source_text
        self.on_post = on_post
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_feedback = self.feedback.value

        current = get_variant(self.source_post_id, "personal") or self.source_text
        new_text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: regenerate_with_feedback(self.source_text, current, user_feedback)
        )
        update_variant(self.source_post_id, "personal_custom", new_text)

        embed = discord.Embed(
            title="✏️ Regenerated Post",
            description=new_text[:4000],
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Feedback: {user_feedback}")

        confirm_view = ConfirmRegeneratedView(
            source_post_id=self.source_post_id,
            new_text=new_text,
            on_post=self.on_post,
            parent_view=self.parent_view,
        )
        await interaction.followup.send(embed=embed, view=confirm_view)


class ConfirmRegeneratedView(discord.ui.View):
    def __init__(self, source_post_id, new_text, on_post, parent_view):
        super().__init__(timeout=3600 * 12)
        self.source_post_id = source_post_id
        self.new_text = new_text
        self.on_post = on_post
        self.parent_view = parent_view

    @discord.ui.button(label="✅ Post This", style=discord.ButtonStyle.success)
    async def post_this(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        self.parent_view.acted = True
        mark_post_status(self.source_post_id, "approved", approved_variant="personal_custom")
        update_variant(self.source_post_id, "personal_custom", self.new_text)
        await interaction.response.send_message("🚀 Posting regenerated version...", ephemeral=False)
        result = await self.on_post(self.source_post_id, "personal_custom")
        if result:
            await interaction.followup.send("✅ Posted to LinkedIn successfully.")
        else:
            await interaction.followup.send("❌ Failed to post to LinkedIn. Check logs for details.")

    @discord.ui.button(label="🔄 Regenerate Again", style=discord.ButtonStyle.secondary)
    async def regen_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            RegenerateModal(
                source_post_id=self.source_post_id,
                source_text=self.new_text,
                on_post=self.on_post,
                parent_view=self.parent_view,
            )
        )

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.danger)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        mark_post_status(self.source_post_id, "skipped")
        await interaction.response.send_message("⏭ Skipped.", ephemeral=False)


# ─────────────────────────────────────────────
#  Bot class
# ─────────────────────────────────────────────

class LinkedInBot(commands.Bot):
    def __init__(self, post_callback: Callable[[str, str], Awaitable[None]]):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.post_callback = post_callback
        self._ready_event = asyncio.Event()

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        logger.info("Discord bot ready: %s (ID: %s)", self.user, self.user.id)
        self._ready_event.set()

    async def wait_until_bot_ready(self):
        await self._ready_event.wait()


# ─────────────────────────────────────────────
#  Send approval message
# ─────────────────────────────────────────────

async def send_approval_message(
    bot: LinkedInBot,
    source_post_id: str,
    source_text: str,
    variants: dict,
    summary: str,
    media_count: int = 0,
    source_urls: list[str] | None = None,
    source_authors: list[str] | None = None,
) -> Optional[discord.Message]:
    """
    Send the approval embed + buttons to the approval channel.
    """
    await bot.wait_until_bot_ready()

    channel = bot.get_channel(config.DISCORD_APPROVAL_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(config.DISCORD_APPROVAL_CHANNEL_ID)

    embed = discord.Embed(
        title="📢 Daily Post → Your LinkedIn",
        description=f"**Summary:** {summary}",
        color=discord.Color.blue()
    )

    if source_urls:
        source_lines = []
        for i, url in enumerate(source_urls):
            name = source_authors[i] if source_authors and i < len(source_authors) else "Source"
            source_lines.append(f"[{name}]({url})")
        embed.add_field(
            name="📌 Based on",
            value=" • ".join(source_lines),
            inline=False,
        )

    def trunc(text, limit=900):
        return text[:limit] + "…" if len(text) > limit else text

    embed.add_field(
        name="✅ Personal Version",
        value=trunc(variants.get("personal", "N/A")),
        inline=False
    )
    embed.add_field(
        name="📏 Shorter Version",
        value=trunc(variants.get("shorter", "N/A")),
        inline=False
    )
    embed.add_field(
        name="🔧 Technical Version",
        value=trunc(variants.get("technical", "N/A")),
        inline=False
    )

    footer_parts = []
    if media_count > 0:
        footer_parts.append(f"📎 {media_count} image(s) will be attached when posted.")
    if footer_parts:
        embed.set_footer(text=" ".join(footer_parts))

    view = ApprovalView(
        source_post_id=source_post_id,
        source_text=source_text,
        on_post_callback=bot.post_callback,
    )

    msg = await channel.send(embed=embed, view=view)
    logger.info("Sent approval message (msg ID: %s) for post %s", msg.id, source_post_id)
    return msg


# ─────────────────────────────────────────────
#  Status command
# ─────────────────────────────────────────────

def register_commands(bot: LinkedInBot):
    @bot.command(name="status")
    async def status_cmd(ctx):
        """!status — show recent post history."""
        history = get_post_history(limit=10)
        if not history:
            await ctx.send("No post history yet.")
            return

        lines = []
        for p in history:
            emoji = {"posted": "✅", "skipped": "⏭", "pending": "⏳", "failed": "❌"}.get(
                p["status"], "❓"
            )
            lines.append(f"{emoji} `{p['source_post_id'][:25]}` — {p['status']} — {p['created_at'][:10]}")
        await ctx.send("**Recent Posts:**\n" + "\n".join(lines))

    @bot.command(name="pending")
    async def pending_cmd(ctx):
        """!pending — show posts awaiting approval."""
        pending = get_pending_posts()
        if not pending:
            await ctx.send("No pending posts.")
            return
        lines = [f"⏳ `{p['source_post_id'][:40]}`" for p in pending]
        await ctx.send("**Pending approval:**\n" + "\n".join(lines))
