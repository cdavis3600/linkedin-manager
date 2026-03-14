"""
rewriter.py — Use OpenAI GPT-4 to generate post variants from source posts.

Includes topic analysis (select_and_synthesize) to pick the best single post
or merge overlapping themes across multiple sources into one daily output.
"""
import json
import logging
from openai import OpenAI

from config import config

logger = logging.getLogger(__name__)
client = OpenAI(api_key=config.OPENAI_API_KEY)

SYNTHESIS_PROMPT = """\
You are given recent LinkedIn posts from sources the user follows.
Your job is to decide the best strategy for creating ONE daily LinkedIn post.

If multiple posts share overlapping themes or a common topic, synthesize them
into a combined summary the user can riff on. If there is no meaningful overlap,
pick the single most interesting / engaging post.

Return ONLY a JSON object (no markdown fences) with these keys:
- "mode": "single" or "synthesized"
- "source_text": the text to expand on (combined narrative if synthesized,
  or the selected post text if single)
- "post_urls": list of direct URLs to the original posts being used
- "author_names": list of author names for the posts being used
- "rationale": one sentence explaining your choice
"""


def select_and_synthesize(posts: list[dict]) -> dict:
    """
    Analyze all fetched posts and either pick the best one or synthesize
    overlapping themes into a single topic for the daily post.

    Each post dict has: text, post_url, author_name, source_url.
    Returns dict with: mode, source_text, post_urls, author_names, rationale.
    """
    if not posts:
        return {"mode": "none", "source_text": "", "post_urls": [], "author_names": [], "rationale": "No posts available."}

    if len(posts) == 1:
        p = posts[0]
        return {
            "mode": "single",
            "source_text": p["text"],
            "post_urls": [p.get("post_url", p.get("source_url", ""))],
            "author_names": [p.get("author_name", "")],
            "rationale": "Only one source post available.",
        }

    numbered = "\n\n".join(
        f"--- Post {i+1} (by {p.get('author_name', 'Unknown')}) ---\n"
        f"URL: {p.get('post_url', '')}\n"
        f"{p['text']}"
        for i, p in enumerate(posts)
    )

    prompt = f"Here are {len(posts)} recent posts:\n\n{numbered}"

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        logger.info("Topic analysis: mode=%s, rationale=%s", result.get("mode"), result.get("rationale"))
        return result
    except Exception as e:
        logger.error("Topic analysis failed: %s — falling back to first post", e)
        p = posts[0]
        return {
            "mode": "single",
            "source_text": p["text"],
            "post_urls": [p.get("post_url", p.get("source_url", ""))],
            "author_names": [p.get("author_name", "")],
            "rationale": f"Fallback after error: {e}",
        }


# ─────────────────────────────────────────────
#  Variant generation
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are ghostwriting LinkedIn posts for CJ Davis, a hands-on CTO and creative \
technology leader. Your job is to expand on someone else's LinkedIn post, \
turning it into an original post that sounds authentically like CJ.

CJ's voice:
- Confident, upbeat, and conversational with a modern executive tone
- Direct, clear, and optimistic — never stiff or overly corporate
- Mixes thought leadership with personal perspective, team pride, and genuine enthusiasm
- Sounds credible and experienced but still approachable and human
- Occasionally uses exclamation points for energy and punch
- Focused on: creative technology, mixed reality, fan experience, innovation, leadership

LinkedIn formatting rules:
- First line MUST be a compelling hook under 200 characters (this is what shows before "see more")
- Use short paragraphs (1-3 sentences each) with blank lines between them
- Never start the post with "I"
- Do NOT plagiarise — expand on the ideas with CJ's own perspective and insights
- Do NOT include any credit links or source URLs — those will be appended automatically
- Max 3 hashtags, mid-popularity (not too broad like #innovation, not too niche)
- End with an engaging question or call to action to drive comments"""


def generate_variants(
    source_text: str,
    post_url: str = "",
    author_name: str = "",
    post_urls: list[str] | None = None,
    author_names: list[str] | None = None,
    source_urls: list[str] | None = None,
) -> dict:
    """
    Generate three post variants expanding on source content.
    Credit links prefer post_urls when they point to a real post (contain /posts/
    or /feed/update/). Falls back to source_urls (profile pages) otherwise.
    Returns dict with keys: personal, shorter, technical
    """
    variants = {}

    raw_post_urls = post_urls or ([post_url] if post_url else [])
    fallback_urls = source_urls or raw_post_urls
    names = author_names or ([author_name] if author_name else [])

    credit_urls = [
        u for u in raw_post_urls
        if "/posts/" in u or "/feed/update/" in u
    ] or fallback_urls

    variants["personal"] = _generate(
        source_text,
        style="personal",
        instruction=(
            "Write a LinkedIn post (80–140 words, MUST be under 900 characters total) "
            "expanding on this content. "
            "Open with a bold, attention-grabbing first line. "
            "Add CJ's perspective — why this matters, what he's seen firsthand. "
            "Use short paragraphs with blank lines. "
            "Close with a question or CTA that invites comments. "
            "Do NOT include any source links or credit lines."
        )
    )

    variants["shorter"] = _generate(
        source_text,
        style="shorter",
        instruction=(
            "Write a punchy, short LinkedIn post (40–80 words) that riffs on the key message "
            "with maximum impact. The first line must be a hook that stops the scroll. "
            "Keep it energetic with CJ's upbeat tone. Use line breaks for punchy rhythm. "
            "End with a question or bold statement. "
            "Do NOT include any source links or credit lines."
        )
    )

    variants["technical"] = _generate(
        source_text,
        style="technical",
        instruction=(
            "Write a LinkedIn post (80–140 words, MUST be under 900 characters total) "
            "aimed at a technical audience. "
            "Open with a hook about the technical challenge or innovation. "
            "Speak to engineers, PMs, and builders with specific details. "
            "Use short paragraphs with blank lines. Keep CJ's approachable tone. "
            "Close with a forward-looking question. "
            "Do NOT include any source links or credit lines."
        )
    )

    credit_line = _build_credit_line(credit_urls, names)
    if credit_line:
        for key in variants:
            variants[key] = variants[key].rstrip() + "\n\n" + credit_line

    return variants


def _build_credit_line(urls: list[str], names: list[str]) -> str:
    """Build a credit line from real URLs — never GPT-generated."""
    if not urls:
        return ""
    if len(urls) == 1:
        name = names[0] if names else "the original author"
        return f"See the original post from {name}: {urls[0]}"
    lines = [f"- {names[i] if i < len(names) else 'Source'}: {u}" for i, u in enumerate(urls)]
    return "Inspired by:\n" + "\n".join(lines)


def _generate(source_text: str, style: str, instruction: str) -> str:
    prompt = f"""Here is the original LinkedIn post to expand on:

---
{source_text}
---

{instruction}

Write only the post text — no preamble, no explanation."""

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.75,
            max_tokens=350,
        )
        content = response.choices[0].message.content.strip()
        logger.info("Generated '%s' variant (%d chars)", style, len(content))
        return content
    except Exception as e:
        logger.error("OpenAI error generating '%s' variant: %s", style, e)
        return f"[Error generating {style} variant: {e}]"


def regenerate_with_feedback(original_post: str, current_text: str, feedback: str) -> str:
    """
    Regenerate a variant based on user feedback from Discord.
    e.g., feedback = "more technical", "add more energy", "make it shorter"
    """
    prompt = f"""Original company post:
---
{original_post}
---

Current draft:
---
{current_text}
---

User feedback: "{feedback}"

Rewrite the post incorporating this feedback. Write only the post text."""

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI regeneration error: %s", e)
        return current_text  # fallback to existing text


def generate_approval_summary(source_text: str, personal_variant: str) -> str:
    """Generate a short summary card for the Discord approval message."""
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"In 1–2 sentences, summarize what this LinkedIn post is about and "
                        f"why it's worth posting:\n\n{personal_variant}"
                    ),
                }
            ],
            temperature=0.5,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "AI-generated post based on company content."
