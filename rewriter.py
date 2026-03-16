"""
rewriter.py — GPT-4 post generator tuned to CJ Davis's voice.

Three source types, each with its own tone and prompt:
  - tfg        → Brief personal reaction to TFG company news (1-4 sentences, team pride)
  - inspiration → Thoughtful curiosity about something someone CJ follows posted
  - industry    → CJ's opinionated take on industry news/trends

One output only — no variant carousel.
"""
import json
import logging
from openai import OpenAI

from config import config

logger = logging.getLogger(__name__)
client = OpenAI(api_key=config.OPENAI_API_KEY)


# ─────────────────────────────────────────────
#  CJ's voice — injected into every prompt
# ─────────────────────────────────────────────

CJ_VOICE = """\
You are ghostwriting LinkedIn posts for CJ Davis, CTO at The Famous Group — \
a creative technology company that builds fan experience products (Vixi, Mixed Reality, \
Virtual Camera) for live events, sports, and entertainment.

CJ's voice — study these real examples:

EXAMPLE 1 (TFG reaction, ultra brief):
"Mixed Reality has evolved. And tonight, we got to prove it.
We developed Virtual Camera to solve the logistical and quality challenges that \
has been holding Mixed Reality back. Seeing our team take this to the next level—and \
watching it come to life in a real broadcast—was incredible.
We are so pumped for what's ahead. Super proud of this team and everything we're building!"

EXAMPLE 2 (personal experiment, curiosity-led):
"🚀 Wild what you can create in just 4 hours with the right AI tools.
I did a quick test using Google Veo2, Flux PullID, MMAudio, and a few other AI platforms — \
all pulled together with Premiere. Every shot, every sound, every frame was AI-generated or AI-enhanced.
Not for a client. Just for fun. Exploring the edges of what's possible.
Curious where this is all headed? Me too."

EXAMPLE 3 (reacting to Vixi being used at Adele concert):
"This is awesome. Great use of the entire Vixi Suite and such a natural fit for the fans \
experience! It's pretty incredible the way she is creating core memories by bringing the \
audience into the show via the MASSIVE screen and even directly addressing messages they \
send in from the stage."

EXAMPLE 4 (team win, very short):
"Vixi is on tour! Great job team. Behind the scenes, there are many new updates and features \
being used! I cant wait for us to start talking about! Stay tuned."

EXAMPLE 5 (event excitement):
"This is one of my favorite events to be a part of. Excited that we get to power both venues \
and the broadcast with our tech this year. The Vixi and Mixed Reality!"

Voice rules — follow these precisely:
- SHORT. TFG reactions are 1-4 sentences. Inspiration/industry go up to 6-8 max.
- NEVER start the post with the word "I"
- Use "we" for team accomplishments — never "our company" or "The Famous Group is proud to..."
- Conversational and authentic — sounds like a real person texting, not a press release
- Genuine excitement without hype — no "thrilled to announce", no "delighted to share"
- Playful self-awareness when it fits naturally ("Ha!", "Me too.", "when I should be sleeping")
- Team pride is real and specific ("Great job team", "Super proud of this team")
- Forward-looking energy but not forced ("Stay tuned", "Curious where this is all headed?")
- Emojis: use 0-2 max, only when they add energy (🚀 for something exciting, ✅ for confirmation)
- Hashtags: 3-5 MAX, relevant only. No spam.
- Do NOT plagiarise source content — add CJ's perspective and angle
- Do NOT include any source URLs or credit lines — those get appended separately"""


# ─────────────────────────────────────────────
#  Source-type specific instructions
# ─────────────────────────────────────────────

TYPE_INSTRUCTIONS = {
    "tfg": """\
SOURCE TYPE: TFG Company Post

CJ is reacting to something his own company just announced or achieved.

Tone: Personal pride, "we built this", authentic team excitement.
Length: 1-4 sentences, 40-100 words MAX. This should feel like a quick, genuine reaction — \
not a full essay.
Pattern: [Short reaction that adds CJ's personal angle] [What makes it special or meaningful] \
[Optional: team shoutout or forward tease]

Do NOT just summarize what TFG said. Add what it means to CJ personally — \
what it felt like to be in the room, why this problem mattered, what he's proud of.
Do NOT start with "I".""",

    "inspiration": """\
SOURCE TYPE: Inspiration Post (someone CJ follows)

CJ is sharing something he found interesting from someone else's feed.

Tone: Curious, observational, shows what CJ is thinking about.
Length: 3-6 sentences, 80-150 words.
Pattern: [What caught CJ's attention and why] [What it makes him think about / his angle on it] \
[Curiosity hook or question at the end]

This is CJ showing his intellectual interests — innovation, AI tools, fan experience, \
creative technology, storytelling. He's not summarizing the post — he's riffing on it.
Do NOT start with "I".""",

    "industry": """\
SOURCE TYPE: Industry News

CJ is sharing his perspective on something happening in the industry.

Tone: Opinionated observer, forward-looking, "here's what I'm watching."
Length: 3-6 sentences, 80-150 words.
Pattern: [Sharp observation about what's happening] [CJ's specific take or angle] \
[What to watch / where this is headed]

CJ's domains: live events tech, sports broadcasting, immersive fan experience, \
AI in creative production, mixed reality, generative media tools.
He doesn't just report — he has a point of view.
Do NOT start with "I".""",
}


# ─────────────────────────────────────────────
#  Topic selection (unchanged from Cursor version)
# ─────────────────────────────────────────────

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
- "source_type": the source_type of the selected/primary post ("tfg", "inspiration", or "industry")
- "post_urls": list of direct URLs to the original posts being used
- "author_names": list of author names for the posts being used
- "rationale": one sentence explaining your choice
"""


def select_and_synthesize(posts: list[dict]) -> dict:
    """
    Analyze all fetched posts and pick the best one or synthesize overlapping themes.
    Each post dict has: text, post_url, author_name, source_url, source_type.
    """
    if not posts:
        return {"mode": "none", "source_text": "", "source_type": "tfg",
                "post_urls": [], "author_names": [], "rationale": "No posts available."}

    if len(posts) == 1:
        p = posts[0]
        return {
            "mode": "single",
            "source_text": p["text"],
            "source_type": p.get("source_type", "tfg"),
            "post_urls": [p.get("post_url", p.get("source_url", ""))],
            "author_names": [p.get("author_name", "")],
            "rationale": "Only one source post available.",
        }

    numbered = "\n\n".join(
        f"--- Post {i+1} (by {p.get('author_name', 'Unknown')}, type: {p.get('source_type','tfg')}) ---\n"
        f"URL: {p.get('post_url', '')}\n"
        f"{p['text']}"
        for i, p in enumerate(posts)
    )

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": f"Here are {len(posts)} recent posts:\n\n{numbered}"},
            ],
            temperature=0.4,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        logger.info("Topic analysis: mode=%s, type=%s, rationale=%s",
                    result.get("mode"), result.get("source_type"), result.get("rationale"))
        return result
    except Exception as e:
        logger.error("Topic analysis failed: %s — falling back to first post", e)
        p = posts[0]
        return {
            "mode": "single",
            "source_text": p["text"],
            "source_type": p.get("source_type", "tfg"),
            "post_urls": [p.get("post_url", p.get("source_url", ""))],
            "author_names": [p.get("author_name", "")],
            "rationale": f"Fallback after error: {e}",
        }


# ─────────────────────────────────────────────
#  Single post generation
# ─────────────────────────────────────────────

def generate_post(
    source_text: str,
    source_type: str = "tfg",
    post_urls: list[str] | None = None,
    author_names: list[str] | None = None,
    source_urls: list[str] | None = None,
) -> str:
    """
    Generate ONE LinkedIn post in CJ's voice, tuned to the source type.
    source_type: "tfg" | "inspiration" | "industry"
    Returns the final post text including credit line.
    """
    instruction = TYPE_INSTRUCTIONS.get(source_type, TYPE_INSTRUCTIONS["tfg"])

    prompt = f"""Here is the source content to riff on:

---
{source_text}
---

{instruction}

Write only the post text. No preamble, no explanation, no title."""

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CJ_VOICE},
                {"role": "user", "content": prompt},
            ],
            temperature=0.75,
            max_tokens=400,
        )
        post_text = response.choices[0].message.content.strip()
        logger.info("Generated %s post (%d chars)", source_type, len(post_text))
    except Exception as e:
        logger.error("OpenAI error: %s", e)
        post_text = f"[Error generating post: {e}]"

    # Append credit line for inspiration/industry posts
    if source_type in ("inspiration", "industry"):
        raw_urls = post_urls or []
        fallback = source_urls or raw_urls
        credit_urls = [u for u in raw_urls if "/posts/" in u or "/feed/update/" in u] or fallback
        credit_line = _build_credit_line(credit_urls, author_names or [])
        if credit_line:
            post_text = post_text.rstrip() + "\n\n" + credit_line

    return post_text


def _build_credit_line(urls: list[str], names: list[str]) -> str:
    if not urls:
        return ""
    if len(urls) == 1:
        name = names[0] if names else "the original author"
        return f"Via {name}: {urls[0]}"
    lines = [f"- {names[i] if i < len(names) else 'Source'}: {u}" for i, u in enumerate(urls)]
    return "Inspired by:\n" + "\n".join(lines)


# ─────────────────────────────────────────────
#  Regeneration with feedback
# ─────────────────────────────────────────────

def regenerate_with_feedback(
    original_post: str,
    current_text: str,
    feedback: str,
    source_type: str = "tfg",
) -> str:
    instruction = TYPE_INSTRUCTIONS.get(source_type, TYPE_INSTRUCTIONS["tfg"])
    prompt = f"""Original source content:
---
{original_post}
---

Current draft:
---
{current_text}
---

User feedback: "{feedback}"

{instruction}

Rewrite incorporating this feedback. Write only the post text."""

    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": CJ_VOICE},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI regeneration error: %s", e)
        return current_text


def generate_approval_summary(source_text: str, post_text: str) -> str:
    """One-line summary for the Discord embed header."""
    try:
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": f"In one short sentence (max 15 words), what is this LinkedIn post about?\n\n{post_text}"
            }],
            temperature=0.3,
            max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "New post ready for review."
