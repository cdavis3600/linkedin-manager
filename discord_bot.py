"""
discord_bot.py — Discord bot for LinkedIn post approval workflow.

Flow:
  1. Bot sends an embed to the approval channel with ONE generated post + action buttons.
  2. User clicks:
       ✅ Approve     → opens team tagging step
       ✏️  Regenerate  → modal/prompt for feedback, regenerates post
       ⏭  Skip        → marks post as skipped
  3. Team tagging step: pick teammates to @-mention (optional), then post.
"""
import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone

import discord
from discord.ext import commands
from typing import Callable, Awaitable, Optional

from config import config
from database import (
    mark_post_status, get_variant, update_variant,
    get_post_history, get_pending_posts,
    insert_post, save_variants, is_post_processed,
)
from rewriter import regenerate_with_feedback

# Matches any linkedin.com URL
_LINKEDIN_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/\S+", re.IGNORECASE
)

logger = logging.getLogger(__name__)


def _parse_time(text: str) -> tuple[int | None, int | None]:
    """
    Parse a user-supplied time string into (hour, minute) in 24h format.
    Accepts: "14:30", "2:30pm", "2:30 PM", "9am", "09:00".
    Returns (None, None) on failure.
    """
    text = text.strip().lower().replace(" ", "")
    try:
        if "am" in text or "pm" in text:
            is_pm = "pm" in text
            text = text.replace("am", "").replace("pm", "")
            if ":" in text:
                h, m = text.split(":", 1)
            else:
                h, m = text, "0"
            hour, minute = int(h), int(m)
            if hour == 12:
                hour = 0 if not is_pm else 12
            elif is_pm:
                hour += 12
        elif ":" in text:
            h, m = text.split(":", 1)
            hour, minute = int(h), int(m)
        else:
            return None, None

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
        return None, None
    except (ValueError, IndexError):
        return None, None


# Source type display labels
SOURCE_TYPE_LABELS = {
    "tfg": "🏢 Company Post",
    "inspiration": "💡 Inspiration",
    "industry": "📰 Industry News",
}


# ─────────────────────────────────────────────
#  Team Tag Select + View
# ─────────────────────────────────────────────

class DepartmentSelect(discord.ui.Select):
    """
    Single-pick select that bulk-adds every member of a department.
    Compound members (e.g. "Tech & Vixi") appear in both groups.
    """

    def __init__(self, department_groups: dict[str, list[dict]], row: int = 0):
        options = []
        for dept in sorted(department_groups):
            count = len(department_groups[dept])
            options.append(
                discord.SelectOption(
                    label=dept,
                    description=f"{count} member{'s' if count != 1 else ''}",
                    value=dept,
                )
            )
        super().__init__(
            placeholder="📂 Tag an entire department (optional)...",
            min_values=0,
            max_values=1,
            options=options[:25],
            row=row,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values:
            dept = self.values[0]
            members = config.DEPARTMENT_GROUPS.get(dept, [])
            self.view.dept_selected_names = {m["name"] for m in members}
        else:
            self.view.dept_selected_names = set()
        await interaction.response.defer()


class IndividualSelect(discord.ui.Select):
    """
    Multi-pick select for tagging specific people.
    Shows title + department in the description so CJ can identify them.
    Sorted so Tech & Vixi people appear first (most commonly tagged).
    Capped at 25 options (Discord limit).
    """

    # Departments that float to the top of the individual list
    _PRIORITY_DEPTS = {"Vixi", "Tech", "Lead"}

    def __init__(self, team_members: list[dict], row: int = 1):
        def sort_key(m):
            depts = {d.strip() for d in m.get("department", "").split("&")}
            priority = 0 if depts & self._PRIORITY_DEPTS else 1
            return (priority, m["name"])

        sorted_members = sorted(team_members, key=sort_key)[:25]
        options = []
        for m in sorted_members:
            title = m.get("title", "")
            dept  = m.get("department", "")
            # Truncate description to Discord's 100-char limit
            desc_parts = [p for p in [title, dept] if p]
            desc = " · ".join(desc_parts)[:100] if desc_parts else None
            options.append(
                discord.SelectOption(
                    label=m["name"],
                    description=desc,
                    value=m["name"],
                )
            )
        super().__init__(
            placeholder="👤 Or tag specific people (optional)...",
            min_values=0,
            max_values=min(len(options), 10),
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.individual_selected_names = set(self.values)
        await interaction.response.defer()


class TeamTagView(discord.ui.View):
    """
    Shown after the user approves a post.
    Two ways to tag:
      1. Pick a whole department  → tags everyone in it
      2. Pick specific individuals → overrides or combines with dept pick
    Final tagged set = union of both selections.
    """

    def __init__(
        self,
        source_post_id: str,
        post_text: str,
        on_post: Callable[[str, str], Awaitable[None]],
        parent_view: "ApprovalView",
    ):
        super().__init__(timeout=3600 * 12)
        self.source_post_id = source_post_id
        self.post_text = post_text
        self.on_post = on_post
        self.parent_view = parent_view
        self.dept_selected_names: set[str] = set()
        self.individual_selected_names: set[str] = set()

        if config.DEPARTMENT_GROUPS:
            self.add_item(DepartmentSelect(config.DEPARTMENT_GROUPS, row=0))
        if config.TEAM_MEMBERS:
            self.add_item(IndividualSelect(config.TEAM_MEMBERS, row=1))

    def _all_selected_names(self) -> list[str]:
        """Union of department and individual selections, preserving roster order."""
        combined = self.dept_selected_names | self.individual_selected_names
        return [m["name"] for m in config.TEAM_MEMBERS if m["name"] in combined]

    def _build_final_text(self) -> str:
        """
        Append tagged names to post text.
        Uses LinkedIn URL when available (plain text — API doesn't support
        clickable @mentions without storing member URNs).
        """
        text = self.post_text.rstrip()
        names = self._all_selected_names()
        if not names:
            return text

        member_map = {m["name"]: m for m in config.TEAM_MEMBERS}
        mention_parts = []
        for name in names:
            url = member_map.get(name, {}).get("linkedin_url", "")
            mention_parts.append(f"{name} ({url})" if url else name)

        return text + "\n\n" + " ".join(mention_parts)

    async def _post(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        final_text = self._build_final_text()
        update_variant(self.source_post_id, "post", final_text)
        self.parent_view.acted = True
        mark_post_status(self.source_post_id, "approved", approved_variant="post")

        tagged = self._all_selected_names()
        tag_note = f" (+{len(tagged)} tagged)" if tagged else ""
        await interaction.response.send_message(
            f"🚀 Posting to LinkedIn{tag_note}...", ephemeral=False
        )
        result = await self.on_post(self.source_post_id, "post")
        if result:
            await interaction.followup.send("✅ Posted to LinkedIn successfully.")
        else:
            await interaction.followup.send(
                "❌ Failed to post to LinkedIn. Check logs for details."
            )

    @discord.ui.button(label="📤 Post Now", style=discord.ButtonStyle.success, row=2)
    async def post_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._post(interaction)

    @discord.ui.button(label="⏭ Skip Tags", style=discord.ButtonStyle.secondary, row=2)
    async def skip_tags(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.dept_selected_names = set()
        self.individual_selected_names = set()
        await self._post(interaction)


# ─────────────────────────────────────────────
#  Regenerate Modal + Confirm View
# ─────────────────────────────────────────────

class RegenerateModal(discord.ui.Modal, title="Regenerate Post"):
    feedback = discord.ui.TextInput(
        label="What should change?",
        placeholder='e.g. "make it shorter", "more technical detail", "punchier opener"',
        style=discord.TextStyle.paragraph,
        max_length=300,
    )

    def __init__(
        self,
        source_post_id: str,
        source_text: str,
        source_type: str,
        on_post: Callable,
        parent_view: "ApprovalView",
    ):
        super().__init__()
        self.source_post_id = source_post_id
        self.source_text = source_text
        self.source_type = source_type
        self.on_post = on_post
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_feedback = self.feedback.value

        current = get_variant(self.source_post_id, "post") or self.source_text
        new_text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: regenerate_with_feedback(
                self.source_text, current, user_feedback, self.source_type
            )
        )
        update_variant(self.source_post_id, "post", new_text)

        label = SOURCE_TYPE_LABELS.get(self.source_type, self.source_type)
        embed = discord.Embed(
            title=f"✏️ Regenerated — {label}",
            description=new_text[:4000],
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Feedback: {user_feedback}")

        confirm_view = ConfirmRegeneratedView(
            source_post_id=self.source_post_id,
            new_text=new_text,
            source_type=self.source_type,
            on_post=self.on_post,
            parent_view=self.parent_view,
        )
        await interaction.followup.send(embed=embed, view=confirm_view)


class ConfirmRegeneratedView(discord.ui.View):
    def __init__(self, source_post_id, new_text, source_type, on_post, parent_view):
        super().__init__(timeout=3600 * 12)
        self.source_post_id = source_post_id
        self.new_text = new_text
        self.source_type = source_type
        self.on_post = on_post
        self.parent_view = parent_view

    @discord.ui.button(label="✅ Approve This", style=discord.ButtonStyle.success)
    async def approve_this(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        tag_view = TeamTagView(
            source_post_id=self.source_post_id,
            post_text=self.new_text,
            on_post=self.on_post,
            parent_view=self.parent_view,
        )

        if config.TEAM_MEMBERS:
            await interaction.response.send_message(
                "👥 **Who should be tagged?** (optional — select and hit Post Now)",
                view=tag_view,
                ephemeral=False,
            )
        else:
            # No team configured — go straight to post
            tag_view.selected_tags = []
            await tag_view._post(interaction)

    @discord.ui.button(label="🔄 Regenerate Again", style=discord.ButtonStyle.secondary)
    async def regen_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            RegenerateModal(
                source_post_id=self.source_post_id,
                source_text=self.new_text,
                source_type=self.source_type,
                on_post=self.on_post,
                parent_view=self.parent_view,
            )
        )

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.danger)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        mark_post_status(self.source_post_id, "skipped")
        self.parent_view.acted = True
        await interaction.response.send_message("⏭ Skipped.", ephemeral=False)


# ─────────────────────────────────────────────
#  Main Approval View
# ─────────────────────────────────────────────

class ApprovalView(discord.ui.View):
    """Interactive buttons for the initial post approval step."""

    def __init__(
        self,
        source_post_id: str,
        source_text: str,
        source_type: str,
        on_post_callback: Callable[[str, str], Awaitable[None]],
        timeout: float = 3600 * 12,
    ):
        super().__init__(timeout=timeout)
        self.source_post_id = source_post_id
        self.source_text = source_text
        self.source_type = source_type
        self.on_post = on_post_callback
        self.acted = False

    async def _disable_all(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=0)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.acted:
            await interaction.response.send_message("Already handled.", ephemeral=True)
            return

        post_text = get_variant(self.source_post_id, "post")
        if not post_text:
            await interaction.response.send_message(
                "⚠️ Could not retrieve post text.", ephemeral=True
            )
            return

        await self._disable_all(interaction)

        tag_view = TeamTagView(
            source_post_id=self.source_post_id,
            post_text=post_text,
            on_post=self.on_post,
            parent_view=self,
        )

        if config.TEAM_MEMBERS:
            await interaction.response.send_message(
                "👥 **Who should be tagged?** (optional — select and hit Post Now)",
                view=tag_view,
                ephemeral=False,
            )
        else:
            # No team configured — go straight to post
            await interaction.response.send_message(
                "🚀 Posting to LinkedIn...", ephemeral=False
            )
            self.acted = True
            update_variant(self.source_post_id, "post", post_text)
            mark_post_status(self.source_post_id, "approved", approved_variant="post")
            result = await self.on_post(self.source_post_id, "post")
            if result:
                await interaction.followup.send("✅ Posted to LinkedIn successfully.")
            else:
                await interaction.followup.send(
                    "❌ Failed to post to LinkedIn. Check logs for details."
                )

    @discord.ui.button(label="✏️ Regenerate", style=discord.ButtonStyle.secondary, row=0)
    async def regenerate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.acted:
            await interaction.response.send_message("Already handled.", ephemeral=True)
            return
        await interaction.response.send_modal(
            RegenerateModal(
                source_post_id=self.source_post_id,
                source_text=self.source_text,
                source_type=self.source_type,
                on_post=self.on_post,
                parent_view=self,
            )
        )

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.danger, row=0)
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

    async def on_timeout(self):
        if not self.acted:
            mark_post_status(self.source_post_id, "skipped")
            logger.info(
                "Post %s auto-skipped after approval timeout.", self.source_post_id
            )


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

    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot:
            return

        # Auto-detect: a LinkedIn URL anywhere in a DM (with or without commentary)
        content = message.content.strip()
        is_dm = isinstance(message.channel, discord.DMChannel)
        url_match = _LINKEDIN_URL_RE.search(content)
        has_linkedin_url = url_match and not content.startswith(self.command_prefix)

        if is_dm and has_linkedin_url:
            linkedin_url = url_match.group(0).rstrip(")")  # trim any trailing paren
            # Everything except the URL is treated as CJ's reaction / tone hint
            reaction = content.replace(linkedin_url, "").strip().strip('"\'')

            logger.info("Auto-detected LinkedIn URL in DM: %s", linkedin_url[:80])
            if reaction:
                logger.info("User reaction hint: %s", reaction)

            await message.channel.send(
                "💡 Spotted a LinkedIn link — generating an inspiration post…"
            )
            from linkedin import fetch_posts_from_url
            try:
                posts = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fetch_posts_from_url(linkedin_url, hours_back=0)
                )
            except Exception as e:
                await message.channel.send(f"❌ Fetch failed: {e}")
                return

            if posts:
                post = posts[0]
                # Prepend CJ's reaction as context so the rewriter picks up his angle
                source_text = post["text"]
                if reaction:
                    source_text = f"[CJ's reaction: {reaction}]\n\n{source_text}"
                await _run_inspire_pipeline(
                    reply_target=message,
                    bot=self,
                    source_text=source_text,
                    author_name=post.get("author_name", ""),
                    source_url=linkedin_url,
                    post_url=post.get("post_url", linkedin_url),
                )
            else:
                await message.channel.send(
                    "⚠️ Couldn't pull the post text automatically. "
                    "Try `!inspire` and paste the text manually."
                )
            return  # Don't process as a command

        # Normal command processing
        await self.process_commands(message)


# ─────────────────────────────────────────────
#  Send approval message
# ─────────────────────────────────────────────

async def send_approval_message(
    bot: LinkedInBot,
    source_post_id: str,
    source_text: str,
    post_text: str,
    source_type: str,
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

    type_label = SOURCE_TYPE_LABELS.get(source_type, source_type.upper())

    embed = discord.Embed(
        title=f"📢 {type_label} → Your LinkedIn",
        description=f"**{summary}**",
        color=discord.Color.blue(),
    )

    if source_urls:
        source_lines = []
        for i, url in enumerate(source_urls):
            name = (
                source_authors[i]
                if source_authors and i < len(source_authors)
                else "Source"
            )
            source_lines.append(f"[{name}]({url})")
        embed.add_field(
            name="📌 Based on",
            value=" • ".join(source_lines),
            inline=False,
        )

    def trunc(text, limit=1800):
        return text[:limit] + "…" if len(text) > limit else text

    embed.add_field(
        name="✍️ Generated Post",
        value=trunc(post_text),
        inline=False,
    )

    footer_parts = [f"Type: {type_label}"]
    if media_count > 0:
        footer_parts.append(f"📎 {media_count} image(s) will be attached when posted.")
    embed.set_footer(text=" • ".join(footer_parts))

    view = ApprovalView(
        source_post_id=source_post_id,
        source_text=source_text,
        source_type=source_type,
        on_post_callback=bot.post_callback,
    )

    msg = await channel.send(embed=embed, view=view)
    logger.info(
        "Sent approval message (msg ID: %s) for post %s [%s]",
        msg.id, source_post_id, source_type,
    )
    return msg


# ─────────────────────────────────────────────
#  On-demand inspiration pipeline
# ─────────────────────────────────────────────

async def _run_inspire_pipeline(
    reply_target,           # ctx or discord.Message — used to send status updates
    bot: "LinkedInBot",
    source_text: str,
    author_name: str = "",
    source_url: str = "",   # LinkedIn profile/company page
    post_url: str = "",     # direct link to the specific post
) -> None:
    """
    Generate an inspiration post from source_text and send it to the
    approval channel, same as the scheduled pipeline.
    Works for both fetched URLs and pasted text.
    """
    from rewriter import generate_post, generate_approval_summary

    # Stable dedup ID based on content hash
    content_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]
    post_id = f"inspire_{content_hash}"

    if is_post_processed(post_id):
        await reply_target.channel.send(
            "⚠️ Looks like you've already generated a post from this content. "
            "Check your pending approvals with `!pending`."
        )
        return

    insert_post(post_id, source_text, datetime.now(timezone.utc).isoformat())

    status_msg = await reply_target.channel.send("⏳ Generating your post…")

    try:
        post_text = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: generate_post(
                source_text,
                source_type="inspiration",
                post_urls=[post_url] if post_url else [],
                author_names=[author_name] if author_name else [],
                source_urls=[source_url] if source_url else [],
            ),
        )
        summary = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_approval_summary(source_text, post_text)
        )
    except Exception as e:
        logger.error("Inspiration pipeline failed: %s", e)
        await status_msg.edit(content=f"❌ Generation failed: {e}")
        mark_post_status(post_id, "failed")
        return

    save_variants(post_id, {"post": post_text})
    await status_msg.delete()

    await send_approval_message(
        bot=bot,
        source_post_id=post_id,
        source_text=source_text,
        post_text=post_text,
        source_type="inspiration",
        summary=summary,
        source_urls=[post_url or source_url] if (post_url or source_url) else [],
        source_authors=[author_name] if author_name else [],
    )


class InspirationInputModal(discord.ui.Modal, title="Repost with My Thoughts"):
    """Modal for pasting a LinkedIn post when !inspire is called with no URL."""

    post_content = discord.ui.TextInput(
        label="Paste the LinkedIn post text",
        style=discord.TextStyle.paragraph,
        placeholder="Paste the full post text you want to riff on…",
        max_length=2000,
        row=0,
    )
    author_name = discord.ui.TextInput(
        label="Author name (optional)",
        placeholder="e.g. Andrew Ng",
        required=False,
        max_length=100,
        row=1,
    )
    source_url = discord.ui.TextInput(
        label="Their LinkedIn URL (optional)",
        placeholder="https://www.linkedin.com/in/…",
        required=False,
        max_length=500,
        row=2,
    )

    def __init__(self, bot: "LinkedInBot"):
        super().__init__()
        self._bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _run_inspire_pipeline(
            reply_target=interaction.message or interaction,
            bot=self._bot,
            source_text=self.post_content.value.strip(),
            author_name=self.author_name.value.strip(),
            source_url=self.source_url.value.strip(),
        )

    # Give the modal somewhere to send status updates when reply_target
    # is an Interaction (which has no .channel directly after defer)
    class _FakeChannel:
        def __init__(self, interaction):
            self._i = interaction
        async def send(self, content):
            return await self._i.followup.send(content)


class InspireButtonView(discord.ui.View):
    """Shown when !inspire is called with no arguments."""

    def __init__(self, bot: "LinkedInBot"):
        super().__init__(timeout=300)
        self._bot = bot

    @discord.ui.button(label="📝 Paste post text", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = InspirationInputModal(bot=self._bot)
        await interaction.response.send_modal(modal)


# ─────────────────────────────────────────────
#  Bot commands
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
            emoji = {
                "posted": "✅", "skipped": "⏭",
                "pending": "⏳", "failed": "❌",
            }.get(p["status"], "❓")
            lines.append(
                f"{emoji} `{p['source_post_id'][:25]}` — {p['status']} — {p['created_at'][:10]}"
            )
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

    @bot.command(name="inspire")
    async def inspire_cmd(ctx, *, arg: str = ""):
        """
        !inspire                    — opens a form to paste post text
        !inspire <linkedin_url>     — fetches that post and generates inspiration
        !inspire <any text>         — uses your text directly as the source
        """
        arg = arg.strip()

        # No argument → open the paste modal via a button
        if not arg:
            await ctx.send(
                "💡 **Repost with your thoughts** — click below to paste a post:",
                view=InspireButtonView(bot),
            )
            return

        # Looks like a LinkedIn URL → fetch it first
        if _LINKEDIN_URL_RE.match(arg):
            status = await ctx.send(f"🔍 Fetching post from `{arg[:60]}`…")
            from linkedin import fetch_posts_from_url
            try:
                posts = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: fetch_posts_from_url(arg, hours_back=0)
                )
            except Exception as e:
                await status.edit(content=f"❌ Fetch failed: {e}")
                return

            if not posts:
                await status.edit(
                    content=(
                        "⚠️ Couldn't pull the post text automatically. "
                        "Try `!inspire` (no args) and paste the text manually."
                    )
                )
                return

            post = posts[0]
            await status.delete()
            await _run_inspire_pipeline(
                reply_target=ctx,
                bot=bot,
                source_text=post["text"],
                author_name=post.get("author_name", ""),
                source_url=arg,
                post_url=post.get("post_url", arg),
            )
            return

        # Plain text pasted directly into the command
        await _run_inspire_pipeline(
            reply_target=ctx,
            bot=bot,
            source_text=arg,
        )

    @bot.command(name="team")
    async def team_cmd(ctx):
        """!team — show team roster grouped by department."""
        if not config.TEAM_MEMBERS:
            await ctx.send("No team members configured. Add TEAM_MEMBERS to your .env.")
            return
        lines = []
        for dept in sorted(config.DEPARTMENT_GROUPS):
            members = config.DEPARTMENT_GROUPS[dept]
            lines.append(f"\n**{dept}** ({len(members)})")
            for m in members:
                title = f" — {m['title']}" if m.get("title") else ""
                lines.append(f"  • {m['name']}{title}")
        await ctx.send("**Team roster by department:**" + "\n".join(lines))

    @bot.command(name="schedule")
    async def schedule_cmd(ctx, *, time_str: str = ""):
        """
        !schedule          — show current schedule and next run
        !schedule 14:30    — change to 2:30 PM (24h format)
        !schedule 2:30pm   — change to 2:30 PM (12h format)
        """
        from scheduler import reschedule_pipeline

        if not time_str.strip():
            job = bot.scheduler.get_job("linkedin_pipeline")
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %I:%M %p %Z")
                current = job.next_run_time.strftime("%I:%M %p")
                await ctx.send(
                    f"📅 **Schedule:** daily at **{current}** ({config.TIMEZONE})\n"
                    f"⏭ **Next run:** {next_run}"
                )
            else:
                await ctx.send("⚠️ No scheduled job found.")
            return

        hour, minute = _parse_time(time_str.strip())
        if hour is None:
            await ctx.send(
                "⚠️ Couldn't parse that time. Use `HH:MM` (24h) or `H:MMam/pm`.\n"
                "Examples: `!schedule 14:30` or `!schedule 2:30pm`"
            )
            return

        reschedule_pipeline(bot.scheduler, hour, minute)

        job = bot.scheduler.get_job("linkedin_pipeline")
        next_run = job.next_run_time.strftime("%Y-%m-%d %I:%M %p %Z") if job else "unknown"
        display = f"{hour:02d}:{minute:02d}"
        await ctx.send(
            f"✅ Schedule updated to **{display}** ({config.TIMEZONE})\n"
            f"⏭ **Next run:** {next_run}"
        )
