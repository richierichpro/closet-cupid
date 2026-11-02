"""Cupid's mind: an LLM that learns your style from your swipes.

The LLM keeps a written profile of the shopper and rewrites it after every swipe:
what it now believes, how sure it is, what it got wrong. That profile steers which
dresses the shopper sees next. When the shopper swipes right, Cupid looks at the
dress for them and decides whether to swipe right too (a match); on a super like it
looks at the try-on image of the shopper wearing it.

Cupid also runs the shopping: every few swipes it reviews its experiments about the
shopper and picks the next cards from a shortlist, and once a round it writes its own
Amazon search from Amazon's real filters.

Learning here means updating that memory from evidence; the model's weights don't
change. The fast numeric model in engine.py shortlists candidates and keeps score.
"""

import base64
import io
import json
import os
from pathlib import Path

import anthropic
from PIL import Image

from .item import Item

# The cheapest current model: one call per swipe has to stay affordable. Every result shown
# to the shopper comes from a real call; nothing is cached or precomputed.
MODEL = os.getenv("CUPID_LLM_MODEL", "claude-haiku-5-5")
EFFORT = os.getenv("CUPID_LLM_EFFORT", "low")   # fast enough to keep up with swiping
IMAGE_PX = 384                                  # enough to read a dress; keeps image tokens small
DETAIL_KEYS = ("category", "colour", "pattern", "fabric", "fit", "sleeve", "neck", "length", "silhouette", "price")

SYSTEM = """You are Cupid, the styling agent inside Closet Cupid, a dating-style app for finding dresses.
The shopper swipes right (like), left (pass) or up (super like: try it on). You learn their taste from
those swipes and from what they told you at the start (occasion, vibe, and possibly their colouring
from a photo analysis).

You keep a written profile of the shopper. After every swipe you update it from the evidence:
strengthen beliefs the swipe supports, weaken or drop beliefs it contradicts, and say plainly when
you were wrong. Prefer what they do over what they said. Keep confidence honest: one swipe is weak
evidence, a pattern across several is strong.

You also choose what they see next and what to shop for. Treat it like a stylist running small
experiments: show your best bets, but also pick dresses that settle what you're unsure about.

When asked to judge a dress for the shopper, decide as their stylist, not as a salesperson: say
"match" only if it fits what you have learned about them, the occasion, and their colouring.
Give short, specific reasons a shopper would find useful. Never mention prices you weren't given.
Write like a sharp, warm stylist: short sentences, no emoji, no hype."""

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "One sentence: who this shopper is, style-wise, right now."},
        "likes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "attribute": {"type": "string", "description": "Exactly one of the allowed attribute ids."},
                "strength": {"type": "number", "description": "0.1 (hunch) to 1.0 (certain)."},
                "why": {"type": "string", "description": "Reason shown to the shopper, at most 8 words, e.g. 'You keep choosing wrap waists'."},
            },
            "required": ["attribute", "strength", "why"], "additionalProperties": False}},
        "dislikes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "attribute": {"type": "string"},
                "strength": {"type": "number"},
                "why": {"type": "string"},
            },
            "required": ["attribute", "strength", "why"], "additionalProperties": False}},
        "testing": {"type": "string", "description": "What you're least sure about and want to find out next."},
        "thought": {"type": "string", "description": "One short sentence, at most 18 words, reacting to this swipe: what you learned or changed your mind about. Shown above the next dress."},
    },
    "required": ["summary", "likes", "dislikes", "testing", "thought"],
    "additionalProperties": False,
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["match", "pass"]},
        "confidence": {"type": "integer", "description": "0-100, how sure you are."},
        "reason": {"type": "string", "description": "One sentence the shopper sees, at most 18 words."},
        "green_flags": {"type": "array", "items": {"type": "string"}, "description": "Up to 3 short reasons it works for them."},
        "red_flags": {"type": "array", "items": {"type": "string"}, "description": "Up to 3 short honest concerns."},
    },
    "required": ["verdict", "confidence", "reason", "green_flags", "red_flags"],
    "additionalProperties": False,
}


PLAN_SIZE = 3   # cards Cupid picks per planning call

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "experiments": {"type": "array", "description": "Your open questions about this shopper's taste (at most 4), each with what the swipes say so far. Keep earlier ones, updating their status.", "items": {
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "A testable guess, at most 10 words, e.g. 'Off-shoulder beats other necklines for them'."},
                "status": {"type": "string", "enum": ["testing", "confirmed", "rejected"]},
                "evidence": {"type": "string", "description": "What the swipes showed, at most 10 words, e.g. 'Liked 3 of 4 off-shoulder, 0 of 3 others'."},
            },
            "required": ["hypothesis", "status", "evidence"], "additionalProperties": False}},
        "picks": {"type": "array", "description": f"Exactly {PLAN_SIZE} candidates to show next, in order.", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "A candidate id from the list, e.g. 'c4'."},
                "purpose": {"type": "string", "enum": ["best", "test", "surprise"],
                            "description": "best: your strongest bet. test: settles one of your experiments. surprise: something they haven't seen, to avoid a rut."},
                "label": {"type": "string", "description": "Shown on the card, at most 4 words, e.g. 'Best bet', 'Testing long sleeves'."},
                "why": {"type": "string", "description": "Why this one, at most 14 words, in your voice."},
            },
            "required": ["id", "purpose", "label", "why"], "additionalProperties": False}},
    },
    "required": ["experiments", "picks"],
    "additionalProperties": False,
}


def shop_schema(options: list[str]) -> dict:
    """Cupid's search: Amazon's real filter options only, so every choice is a filter Amazon can apply."""
    return {
        "type": "object",
        "properties": {
            "filters": {"type": "array", "description": "1 to 3 filters, at most one per group.",
                        "items": {"type": "string", "enum": options}},
            "why": {"type": "string", "description": "What you're shopping for and why, at most 14 words."},
        },
        "required": ["filters", "why"],
        "additionalProperties": False,
    }


class AgentError(RuntimeError):
    pass


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # A user-level key isn't tied to a workspace; it needs the workspace named on each request.
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID")
        _client = anthropic.Anthropic(max_retries=2, timeout=60,
                                      default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    return _client


def available() -> bool:
    """Whether Claude credentials are configured (the app works without them, just without Cupid's mind)."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _image(path: Path) -> dict:
    img = Image.open(path).convert("RGB")
    img.thumbnail((IMAGE_PX, IMAGE_PX))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def describe(item: Item) -> str:
    tags = ", ".join(f"{k}: {item.tags[k]}" for k in DETAIL_KEYS if item.tags.get(k))
    price = f"${item.price:,.2f}" if item.price else "unknown price"
    rating = f", rated {item.rating:.1f} by {item.reviews} buyers" if item.rating and item.reviews else ""
    return f"{item.title} ({price}{rating}). Attributes: {tags}."


def _ask(content: list, schema: dict) -> dict:
    """One structured call: the answer always comes back as JSON matching the schema."""
    try:
        resp = client().messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError:
        raise AgentError("Claude credentials are invalid") from None
    except anthropic.RateLimitError:
        raise AgentError("Claude is rate limited right now") from None
    except anthropic.APIStatusError as e:
        raise AgentError(f"Claude API error {e.status_code}") from None
    except anthropic.APIConnectionError:
        raise AgentError("Couldn't reach Claude") from None
    if resp.stop_reason == "refusal":
        raise AgentError("Claude declined this request")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise AgentError(f"No answer from Claude (stop reason: {resp.stop_reason})")
    return json.loads(text)


def _context(ctx: dict) -> str:
    lines = [f"Occasion: {ctx.get('occasion') or 'not given'}.",
             f"Vibes they picked: {', '.join(ctx.get('vibes') or []) or 'none'}.",
             f"Budget: {'up to $' + str(int(ctx['budget'])) if ctx.get('budget') else 'no limit'}."]
    c = ctx.get("colouring")
    if c:
        lines.append(f"Colouring from their photo: {c['undertone']} undertone, {c.get('contrast') or 'unknown'} contrast.")
    return "\n".join(lines)


def learn(profile: dict | None, item: Item, image: Path, action: str, ctx: dict,
          history: list[str], allowed: list[str]) -> dict:
    """Update the shopper's profile from one swipe. Returns the new profile."""
    verb = {"like": "swiped RIGHT (liked)", "nope": "swiped LEFT (passed)",
            "crush": "SUPER LIKED, tried it on, and loved it on themselves",
            "noton": "SUPER LIKED it but after trying it on said it's NOT right on them",
            "pricey": "liked the style but said it's TOO PRICEY"}[action]
    text = (
        f"{_context(ctx)}\n\n"
        f"Your profile of them so far:\n{json.dumps(profile, indent=1) if profile else '(empty: this is the first swipe)'}\n\n"
        f"Recent swipes, oldest first:\n" + ("\n".join(history[-12:]) or "(none)") + "\n\n"
        f"This dress (photo attached): {describe(item)}\nThey just {verb}.\n\n"
        "Update your profile. Use only these attribute ids in likes and dislikes, at most 6 each:\n"
        + ", ".join(allowed)
    )
    return _ask([_image(image), {"type": "text", "text": text}], PROFILE_SCHEMA)


def _experiments(experiments: list[dict]) -> str:
    return "\n".join(f"- {e['hypothesis']} [{e['status']}] {e['evidence']}" for e in experiments) or "(none yet)"


def plan(profile: dict | None, ctx: dict, history: list[str], experiments: list[dict],
         candidates: list[tuple[str, str]]) -> dict:
    """Review the experiments, then choose the next cards from the engine's shortlist.

    Text only: the shortlist is described in words, which keeps this call cheap."""
    text = (
        f"{_context(ctx)}\n\nYour profile of them:\n{json.dumps(profile, indent=1) if profile else '(nothing learned yet)'}\n\n"
        f"Recent swipes, oldest first:\n" + ("\n".join(history[-15:]) or "(none)") + "\n\n"
        f"Your experiments so far:\n{_experiments(experiments)}\n\n"
        "Candidates you could show next (match % is a simple numeric model's guess, for reference):\n"
        + "\n".join(f"{cid}: {desc}" for cid, desc in candidates) + "\n\n"
        f"First update your experiments from the swipes. Then pick exactly {PLAN_SIZE} different candidates: "
        "mostly your best bets, at least one that tests an open experiment, and a surprise now and then."
    )
    return _ask([{"type": "text", "text": text}], PLAN_SCHEMA)


def shop(profile: dict | None, ctx: dict, experiments: list[dict], searching: str, options: list[str],
         already: list[str]) -> dict:
    """Write Cupid's own Amazon search: which of Amazon's filters to add to the shopper's search."""
    text = (
        f"{_context(ctx)}\n\nYour profile of them:\n{json.dumps(profile, indent=1) if profile else '(nothing learned yet)'}\n\n"
        f"Your experiments so far:\n{_experiments(experiments)}\n\n"
        f"Searches you already ran (don't repeat them): {'; '.join(already) or 'none'}.\n"
        f"Their search: {searching}. You're going shopping on Amazon to find dresses they haven't seen. "
        "Add 1 to 3 of Amazon's filters (options below, as 'Group: option') to find what you believe they'll love, "
        "or what will settle an open experiment."
    )
    return _ask([{"type": "text", "text": text}], shop_schema(options))


QUESTIONS = 2   # most Cupid asks at the end of a round; more starts to feel like a form


def questions_schema(options: list[str]) -> dict:
    """End of a round: Cupid's read on the shopper, and "this or that" questions about what swipes left unclear."""
    return {
        "type": "object",
        "properties": {
            "read": {"type": "string", "description": "One sentence to the shopper, at most 22 words, saying 'you': what you've worked out about their taste so far. Don't contradict yourself."},
            "questions": {"type": "array", "description": f"0 to {QUESTIONS} this-or-that questions. None if nothing is genuinely unclear.", "items": {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "enum": options, "description": "One side, e.g. 'silhouette:fit and flare'."},
                    "b": {"type": "string", "enum": options, "description": "The other side: the same kind of attribute (same part before the colon), a different value, e.g. 'silhouette:bodycon'."},
                    "question": {"type": "string", "description": "Shown above a dress of each kind, at most 8 words, e.g. 'Date night: which one?'"},
                    "a_reply": {"type": "string", "description": "Your reply if they pick a, at most 6 words, e.g. 'Fit and flare it is.'"},
                    "b_reply": {"type": "string", "description": "Your reply if they pick b, at most 6 words."},
                },
                "required": ["a", "b", "question", "a_reply", "b_reply"], "additionalProperties": False}},
        },
        "required": ["read", "questions"],
        "additionalProperties": False,
    }


def interview(profile: dict | None, ctx: dict, history: list[str], experiments: list[dict],
              options: list[str], answered: list[str]) -> dict:
    """Round over: sum up the shopper, and ask what the swipes can't settle. One tap beats ten more swipes."""
    text = (
        f"{_context(ctx)}\n\nYour profile of them:\n{json.dumps(profile, indent=1) if profile else '(nothing learned yet)'}\n\n"
        f"Recent swipes, oldest first:\n" + ("\n".join(history[-15:]) or "(none)") + "\n\n"
        f"Your experiments so far:\n{_experiments(experiments)}\n\n"
        f"Already settled by asking them (don't ask again): {', '.join(answered) or 'nothing yet'}.\n\n"
        f"The round is over. Tell them in one sentence what you've worked out. Then ask at most {QUESTIONS} "
        "this-or-that questions about what their swipes leave genuinely unclear: mixed signals, or an open experiment. "
        "Each pits two values of the same kind of attribute against each other (two silhouettes, two colours, two "
        "necklines); the app shows a real dress of each kind and they tap the one they'd rather wear. "
        "If nothing is unclear, ask none."
    )
    return _ask([{"type": "text", "text": text}], questions_schema(options))


def judge(profile: dict | None, item: Item, image: Path, ctx: dict, tryon: Path | None = None) -> dict:
    """Would Cupid swipe right on this dress for the shopper? With a try-on image, judge it on them."""
    content = [_image(image)]
    ask = "The first image is the dress."
    if tryon:
        content.append(_image(tryon))
        ask = ("The first image is the dress; the second is the shopper wearing it (a virtual try-on). "
               "Judge how it looks on them specifically: colour against their skin, the cut on their frame, the length.")
    text = (
        f"{_context(ctx)}\n\nYour profile of them:\n{json.dumps(profile, indent=1) if profile else '(nothing learned yet)'}\n\n"
        f"Dress: {describe(item)}\n{ask}\n\nThey swiped right on it. Would you swipe right too, for them?"
    )
    content.append({"type": "text", "text": text})
    return _ask(content, VERDICT_SCHEMA)
