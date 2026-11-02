"""Closet Cupid API: sessions, swipes, round payoffs, and the analytics board.

    uv run uvicorn cupid.api:app --port 8000

Amazon is only searched for what the shopper says they're looking for: one
search per answer (cached, so the next shopper with the same answer costs
nothing), plus Cupid's own filtered searches as it learns, capped per session
on top of the daily cap.
"""

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from dataclasses import dataclass, field, replace

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import agent, amazon, catalogue, colours, db, faces, metrics, youcam
from .amazon import ANSWER_FOR_CATEGORY, LOOKING_FOR, AmazonSearch, SerpError, answer_search, with_occasion
from .config import DATA_DIR, IMAGE_DIR, SERPAPI_DAILY_LIMIT, VIBE_VECTORS
from .engine import ACTIONS, NEGATIVE, ROUND_SIZE, TOLD, WARMUP, Cupid, Pool, Prediction, Stated, _LABELS
from .item import Item
from .tagging import VIBES, tags_from_title

LIVE_SEARCHES_PER_SESSION = 2  # Cupid's own searches; first searches for an answer are separate
SHOP_OPTIONS = 12              # filter options per group offered to Cupid's LLM when it shops
ALIKE = {"like": 1, "pricey": 1, "crush": 2}   # look-alikes of a dress you loved, shown in the next cards
ASK_AT = ROUND_SIZE - 2       # Cupid writes its end-of-round read and questions 2 swipes early, so they're ready
CACHED_PAGES = 3               # later pages of a search join the deck if prefetched
SHOP_AT = ROUND_SIZE - 4       # Cupid goes shopping 4 cards before the round ends
CUPID_FILTERS = 2              # attributes per Cupid search; more often finds nothing
VIBE_DRESSES = 25              # per chosen vibe, from the whole catalogue, added to the first deck
CALLED_SHOT_FROM = 10          # after this many swipes Cupid starts betting
PHOTO_WAIT = 25                # seconds a new session waits for skin tone analysis to finish
PHOTO_MAX = 1600               # px, longest side of the shopper's photo we keep
BELIEF_WEIGHT = 1.5            # how strongly a belief at full strength moves the match score
BET_CONFIDENCE = 0.75
# "It's a fit!" is a special moment, not a every-like popup: a crush Cupid saw
# coming, or a like it was very sure of, and never twice within a few swipes.
FIT_CRUSH = 0.6
FIT_LIKE = 0.9
FIT_COOLDOWN = 6

# "What's it for?": shapes the Amazon search itself (amazon.OCCASION_WORDS), and gives
# Cupid a starting nudge until the swipes take over.
GOALS = {
    "date": {"label": "Date night", "likes": [], "budget": None},
    "wedding": {"label": "Wedding guest", "likes": [], "budget": None},
    "work": {"label": "Work", "likes": [], "budget": None},
    "party": {"label": "Party", "likes": [], "budget": None},
    "everyday": {"label": "Everyday", "likes": [], "budget": None},
}


app = FastAPI(title="Closet Cupid")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")
PHOTO_DIR = DATA_DIR / "photos"     # shoppers' photos: never committed, never sent anywhere but YouCam
for d in (PHOTO_DIR, youcam.TRYON_DIR):
    d.mkdir(parents=True, exist_ok=True)
app.mount("/tryon", StaticFiles(directory=youcam.TRYON_DIR), name="tryon")

conn = db.connect()
db_lock = threading.Lock()
catalogue_lock = threading.Lock()     # one ingest at a time
ALL = Pool(db.load_items(conn))
SESSIONS: dict[str, "Session"] = {}
_encoder = None
_encoder_lock = threading.Lock()


def encoder():
    global _encoder
    with _encoder_lock:
        if _encoder is None:
            from .vision import FashionEncoder
            _encoder = FashionEncoder()
        return _encoder


class LazyEncoder:
    """The fashion model is only needed to fingerprint dresses that aren't in the catalogue yet.
    With a prefetched catalogue it never loads, which keeps 1-2 GB of memory free."""

    def encode_images(self, images):
        return encoder().encode_images(images)

    def zero_shot(self, embs):
        return encoder().zero_shot(embs)


# ---------- what you're looking for ----------

@dataclass
class Pick:
    id: str
    label: str
    base: AmazonSearch               # the answer + occasion, before the shopper's filters
    node: str | None = None          # hint for Amazon's category refinement
    allows: set[str] | None = None   # garments this answer may show; None = anything
    chosen: dict[str, list[str]] = field(default_factory=dict)   # Amazon filter group → options set
    search: AmazonSearch | None = None   # base narrowed with the shopper's filters
    colours: set[str] | None = None      # visible colours the chosen colour filter accepts
    items: set[str] = field(default_factory=set)

    @property
    def deck_search(self) -> AmazonSearch:
        return self.search or self.base

    def fits(self, item: Item) -> bool:
        """Amazon returns whatever its search matches ("women dress" is mostly kurta sets, and
        its colour filter matches any colour variant), so the deck keeps only what was asked for
        and what the photo actually shows."""
        if self.allows is not None and item.tags.get("category") not in self.allows:
            return False
        colour = item.tags.get("colour")
        return not (self.colours and colour and colour not in self.colours)


def _budget_from(text: str) -> float | None:
    m = re.search(r"under\s*\$?\s*(\d[\d,]*)", text.lower())
    return float(m.group(1).replace(",", "")) if m else None


def _pick(looking: list[str], text: str | None, goal: str) -> Pick | None:
    occasion = GOALS[goal]["label"] if goal in GOALS and goal != "everyday" else None

    def label(what: str) -> str:
        return f"{what} for {occasion}" if occasion else what

    if text and text.strip():
        words = re.sub(r"under\s*\$?\s*\d[\d,]*", "", text, flags=re.I).strip() or text.strip()
        k = with_occasion(words if "women" in words.lower() else f"women {words}", goal)
        # "black linen dress" → only dresses; words with no garment in them allow anything.
        answer = LOOKING_FOR.get(ANSWER_FOR_CATEGORY.get(tags_from_title(words).get("category"), ""), {})
        return Pick("typed", text.strip(), AmazonSearch(k=k, label=label(text.strip())),
                    answer.get("node"), answer.get("allows"))
    a = next((i for i in looking if i in LOOKING_FOR), None)
    if a is None:
        return None
    v = LOOKING_FOR[a]
    return Pick(a, v["label"], answer_search(a, goal, label(v["label"])), v["node"], v["allows"])


def _fetch(search: AmazonSearch) -> tuple[list[Item], str]:
    """Run one search through the pipeline. Returns its items and 'cache' or 'live'."""
    global ALL
    with catalogue_lock:
        bg = db.connect()
        try:
            cached = db.get_search(bg, search.key()) is not None
            report = catalogue.ingest(bg, [search], LazyEncoder(), log=lambda *_: None)
            if not cached and db.get_search(bg, search.key()) is None:
                raise SerpError("SerpAPI budget reached")   # the call was refused; nothing was spent
            # Reload everything returned: new items, and old ones whose filter tags just got sharper.
            fresh = {it.id: it for it in db.load_items(bg, report.item_ids)}
            ALL = Pool([fresh.pop(it.id, it) for it in ALL.items] + list(fresh.values()))
        finally:
            bg.close()
    return [ALL.by_id[i] for i in report.item_ids if i in ALL.by_id], "cache" if cached else "live"


def _filters(pick: Pick) -> dict:
    """Amazon's filter options for this answer, from its first (unfiltered) search."""
    with db_lock:
        raw = db.get_search(conn, pick.base.key())
    return amazon.parse_filters(raw) if raw else {}


def _apply_filters(pick: Pick, chosen: dict[str, list[str]]) -> list[str]:
    """Narrow the answer with the shopper's own Amazon filters. Returns Cupid likes they imply."""
    filters = _filters(pick)
    menu = {m["group"]: {o["name"]: o["rh"] for o in m["options"]} for m in amazon.filter_menu(filters)}
    codes, words, certain, likes = [], [], [], []
    for group, names in chosen.items():
        options = menu.get(group, {})
        picked = [n for n in names if n in options]
        if not picked:
            continue
        pick.chosen[group] = picked
        codes += [options[n] for n in picked]
        words.append(f"size {', '.join(picked)}" if group in amazon.SIZE_GROUPS else ", ".join(picked))
        for n in picked:
            mapped = amazon.to_vocab(group, n)
            if mapped:
                likes.append(f"{mapped[0]}:{mapped[1]}")
                # One material/fit/pattern means every result has it. Colour never does: it's per variant.
                if len(picked) == 1 and group not in amazon.COLOUR_GROUPS:
                    certain.append(mapped)
    colour_group = next((g for g in amazon.COLOUR_GROUPS if g in pick.chosen), None)
    if colour_group:
        pick.colours = amazon.visible_colours(pick.chosen[colour_group])
    if codes:
        node = amazon.category_node(filters, pick.node)
        pick.search = AmazonSearch(k=pick.base.k, rh=amazon.combine_rh(([node] if node else []) + codes),
                                   tags=tuple(certain), label=" · ".join([pick.base.label] + words))
    return likes


# ---------- your photo: skin tone, and try-on later ----------

@dataclass
class Photo:
    path: Path
    file_id: str | None = None       # the YouCam upload, reused for every try-on
    colouring: dict | None = None    # undertone and contrast from Skin Tone Analysis
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event)


PHOTOS: dict[str, Photo] = {}


def _analyse(photo: Photo):
    """Upload the full photo once (for try-ons), then read the shopper's colouring with Skin
    Tone Analysis on a face close-up cut from the same photo."""
    try:
        photo.file_id = youcam.upload(photo.path)
        face = faces.face_crop(photo.path, photo.path.with_name(f"{photo.path.stem}_face.jpg"))
        if face is None:
            photo.error = "Cupid couldn't find your face in this photo, so it can't read your colouring. Try-on still works."
        else:
            photo.colouring = colours.read_colouring(youcam.skin_tone(youcam.upload(face)))
    except youcam.YouCamError as e:
        photo.error = str(e)
    finally:
        photo.done.set()


@app.post("/api/photo")
def upload_photo(file: UploadFile = File(...)):
    """The shopper's photo. Analysis starts now, so it's ready by the end of onboarding."""
    try:
        img = ImageOps.exif_transpose(Image.open(file.file)).convert("RGB")
    except Exception:
        raise HTTPException(400, "That doesn't look like a photo")
    img.thumbnail((PHOTO_MAX, PHOTO_MAX))
    pid = uuid.uuid4().hex[:12]
    path = PHOTO_DIR / f"{pid}.jpg"
    img.save(path, "JPEG", quality=92)
    PHOTOS[pid] = Photo(path)
    threading.Thread(target=_analyse, args=(PHOTOS[pid],), daemon=True).start()
    return {"photo_id": pid}


@app.get("/api/photo/{pid}")
def photo_status(pid: str):
    photo = PHOTOS.get(pid)
    if not photo:
        raise HTTPException(404, "photo not found")
    return {"ready": photo.done.is_set(), "colouring": photo.colouring, "error": photo.error}


# ---------- sessions ----------

@dataclass
class Session:
    id: str
    cupid: Cupid
    pool: Pool
    goal: str
    picks: list[Pick]
    seen: set[str] = field(default_factory=set)
    current: dict | None = None          # the card on screen: item, slot, pred, bet
    searches: list[dict] = field(default_factory=list)
    shopped: set[str] = field(default_factory=set)   # items from Cupid's own searches
    live_used: int = 0
    bets: list[dict] = field(default_factory=list)
    fits: list[int] = field(default_factory=list)    # swipe numbers that were "It's a fit!"
    photo: Photo | None = None
    first_pick: str | None = None    # Cupid's pick before a single swipe, for "first pick vs now"
    thoughts: list[dict] = field(default_factory=list)   # what Cupid concluded after each swipe
    tryons: list[dict] = field(default_factory=list)
    # Cupid's LLM mind: its written profile, the swipe history it reads, and what it decided.
    context: dict = field(default_factory=dict)
    profile: dict | None = None
    history: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)       # streamed to the app: thoughts, matches
    verdicts: dict[str, dict] = field(default_factory=dict)  # item id → Cupid's verdict on your try-on
    plan: list[dict] = field(default_factory=list)          # the next cards Cupid's LLM chose, with why
    experiments: list[dict] = field(default_factory=list)   # its open questions about the shopper
    planning: bool = False
    planned_shown: int = 0
    shop_asks: int = 0
    asks: dict[int, dict] = field(default_factory=dict)    # round → Cupid's read on you and its yes/no questions
    answered: list[str] = field(default_factory=list)      # attributes the shopper settled by answering
    worker: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(1))  # one LLM call at a time, in order
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_active: float = field(default_factory=time.time)


class LookingIn(BaseModel):
    looking: list[str] = []
    text: str | None = None
    filters: dict[str, list[str]] = {}   # Amazon filter group → option names


class NewSession(LookingIn):
    goal: str = "everyday"
    vibes: list[str] = []
    budget: float | None = None
    photo_id: str | None = None


class SwipeIn(BaseModel):
    item_id: str
    action: str
    dwell_ms: int = 1500


def get_session(sid: str) -> Session:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    s.last_active = time.time()
    return s


def _base_items(pick: Pick) -> list[Item]:
    try:
        items, _ = _fetch(pick.base)
    except SerpError as e:
        raise HTTPException(503, f"Cupid couldn't go shopping right now ({e})")
    return items


def _shop_for(s: Session, pick: Pick) -> Pool:
    """The first deck: the answer, narrowed with the shopper's filters. Only what was asked for."""
    search = pick.deck_search
    try:
        items, source = _fetch(search)
    except SerpError as e:
        if search is pick.base:
            raise HTTPException(503, f"Cupid couldn't go shopping right now ({e})")
        # The filtered search couldn't run (budget or network): shop the unfiltered deck instead
        # of failing. Cupid still learns; it just starts wider.
        s.searches.append({"round": s.cupid.n // ROUND_SIZE + 1, "query": search.label, "by": "you",
                           "source": f"skipped ({e})", "items": 0})
        search = pick.base
        items, source = _fetch(search)
    for page in range(2, CACHED_PAGES + 1):   # more of the same search, only if already cached
        more = replace(search, page=page)
        with db_lock:
            cached = db.get_search(conn, more.key()) is not None
        if cached:
            items += [it for it in _fetch(more)[0] if it.id not in {i.id for i in items}]
    items = [it for it in items if pick.fits(it)]
    s.searches.append({"round": s.cupid.n // ROUND_SIZE + 1, "query": search.label, "by": "you",
                       "source": source, "items": len(items)})
    if not items:
        raise HTTPException(409, f"Nothing on Amazon matches {search.label}. Try removing a filter.")
    pick.items = {it.id for it in items}
    return Pool(items)


def _vibe_scores(items: list[Item]) -> tuple[list[str], np.ndarray] | None:
    """How strongly the fashion model sees each vibe in each dress: one row per dress, summing to 1."""
    if not VIBE_VECTORS.exists() or not items:
        return None
    saved = np.load(VIBE_VECTORS)
    logits = 100.0 * np.stack([it.emb for it in items]) @ saved["vectors"].T
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    return list(saved["vibes"]), probs / probs.sum(axis=1, keepdims=True)


def _with_vibes(s: Session, pick: Pick, pool: Pool) -> Pool:
    """Your occasion's search only has the vibes Amazon happens to return (a wedding search has
    almost no minimal dresses), so add the catalogue's most on-vibe dresses, as the fashion model
    sees them, for each vibe you picked."""
    vibes = s.context.get("vibes") or []
    candidates = [it for it in ALL.items if pick.fits(it) and it.id not in pool.by_id]
    scored = _vibe_scores(candidates)
    if not vibes or not scored:
        return pool
    names, probs = scored
    extra: dict[str, Item] = {}
    for v in vibes:
        for j in np.argsort(-probs[:, names.index(v)])[:VIBE_DRESSES]:
            extra[candidates[j].id] = candidates[j]
    pick.items.update(extra)
    s.searches.append({"round": 1, "query": f"{' + '.join(vibes)} dresses, picked by the fashion model",
                       "by": "you", "source": "catalogue", "items": len(extra)})
    return Pool(pool.items + list(extra.values()))


def _start_pick(body: LookingIn, goal: str) -> tuple[Pick, list[str]]:
    pick = _pick(body.looking, body.text, goal)
    if pick is None:
        raise HTTPException(400, "tell Cupid what you're looking for")
    _base_items(pick)   # Amazon's filter options come from this search (cached once fetched)
    return pick, _apply_filters(pick, body.filters)


def _showcase(n: int = 2) -> list[dict]:
    """Two of the best-rated dresses from the cached occasion searches, for the welcome screen."""
    found: dict[str, Item] = {}
    with db_lock:
        for occasion in ("wedding", "date", "party"):
            raw = db.get_search(conn, answer_search("dresses", occasion).key())
            if raw:
                for i in db.resolve_ids(conn, [o["id"] for o in amazon.parse_results(raw)]):
                    if i in ALL.by_id:
                        found[i] = ALL.by_id[i]
    ranked = sorted(found.values(), key=lambda it: -((it.rating or 0) * min(it.reviews or 0, 500)))
    return [{"image": f"/images/{it.image}", "title": it.title, "price": it.price} for it in ranked[:n]]


@app.get("/api/options")
def options():
    with db_lock:
        ready = {g: [a for a in LOOKING_FOR if db.get_search(conn, answer_search(a, g).key())] for g in GOALS}
    return {
        "looking": [{"id": k, "label": v["label"], "hint": v["hint"]} for k, v in LOOKING_FOR.items()],
        "ready": ready,   # occasion → answers already cached (instant, no SerpAPI call)
        "goals": [{"id": k, "label": v["label"]} for k, v in GOALS.items()],
        "showcase": _showcase(),
    }


@app.get("/api/filters")
def filters_for(goal: str = "everyday", looking: str | None = None, text: str | None = None):
    """Amazon's real filters for what you're looking for. The first time for an answer this is
    its one search; afterwards it's cached."""
    pick = _pick([looking] if looking else [], text, goal if goal in GOALS else "everyday")
    if pick is None:
        raise HTTPException(400, "tell Cupid what you're looking for")
    items = [it for it in _base_items(pick) if pick.fits(it)]
    return {"label": pick.base.label, "items": len(items), "groups": amazon.filter_menu(_filters(pick))}


@app.post("/api/sessions")
def new_session(body: NewSession):
    goal_id = body.goal if body.goal in GOALS else "everyday"
    pick, likes = _start_pick(body, goal_id)
    goal = GOALS[goal_id]
    budget = body.budget or (_budget_from(body.text) if body.text else None) or goal["budget"]
    vibes = [f"vibe:{v}" for v in body.vibes if v in VIBES]
    stated = Stated(likes=goal["likes"] + likes + vibes, budget=budget,
                    reasons={f: f"{f.split(':')[1].capitalize()} vibe, as you asked" for f in vibes})
    s = Session(id=uuid.uuid4().hex[:10], cupid=Cupid(stated=stated), pool=Pool([]), goal=goal_id, picks=[pick])
    s.photo = PHOTOS.get(body.photo_id or "")
    if s.photo:
        s.photo.done.wait(PHOTO_WAIT)
        if s.photo.colouring:
            # Skin Tone Analysis becomes Cupid's first belief about colour; swipes can overrule it.
            good, bad = colours.palette(s.photo.colouring)
            stated.likes += [f"colour:{c}" for c in good if f"colour:{c}" not in stated.likes]
            stated.avoid += [f"colour:{c}" for c in bad]
            stated.reasons.update({f"colour:{c}": why for c, why in {**good, **bad}.items()})
    s.context = {"occasion": goal["label"], "vibes": [v for v in body.vibes if v in VIBES], "budget": budget,
                 "colouring": s.photo.colouring if s.photo else None}
    s.pool = _with_vibes(s, pick, _shop_for(s, pick))
    first = s.cupid.next_card(s.pool, s.seen, slot="best")
    s.first_pick = first[0].id if first else None
    SESSIONS[s.id] = s
    with db_lock:
        db.save_shopper(conn, s.id, goal_id, (s.context["colouring"] or {}).get("undertone"),
                        bool(s.photo and s.photo.file_id))
    return {"id": s.id, "pool": len(s.pool.items), "budget": budget, "searches": s.searches,
            "first_pick": _card(s, first[0], "pick", first[2]) if first else None,
            "colouring": s.photo.colouring if s.photo else None}


@app.get("/api/sessions/{sid}")
def session_info(sid: str):
    s = get_session(sid)
    return {"looking": [{"id": p.id, "label": p.deck_search.label} for p in s.picks], "swipes": s.cupid.n,
            "goal": s.goal, "has_photo": s.photo is not None, "has_mind": agent.available()}


@app.post("/api/sessions/{sid}/looking")
def change_looking(sid: str, body: LookingIn):
    """Looking for something else: new deck, same Cupid. What it learned carries over."""
    s = get_session(sid)
    pick, likes = _start_pick(body, s.goal)
    with s.lock:
        s.pool = _with_vibes(s, pick, _shop_for(s, pick))
        s.picks = [pick]
        s.cupid.stated.likes = list(dict.fromkeys(s.cupid.stated.likes + likes))
        s.current = None
        return _deal(s)


# ---------- cards ----------

def _line(s: Session, item: Item, slot: str, pred: Prediction, bet: str | None) -> str:
    # Shown as Cupid's note on the card, in Cupid's own voice.
    if item.id in s.shopped:
        return "Found this when I searched Amazon for you."
    if bet == "like":
        return "Calling it: you'll like this one."
    if bet == "nope":
        return "Calling it: not your style."
    if slot == "warmup":
        return f"Getting a feel for your taste · {s.cupid.n + 1} of {WARMUP}"
    if slot == "test":
        unsure = s.cupid.unsure_about(item)
        if len(unsure) == 2:
            return f"Testing a hunch: {unsure[0]} or {unsure[1]}?"
        return "Testing a hunch about this one."
    if slot in ("wild", "random"):
        return "Something a little different."
    if pred.p >= 0.85:
        return "This one is very you."
    if pred.p >= 0.65:
        return "I think you'll like this."
    return "Not sure about this one."


def _card(s: Session, item: Item, slot: str, pred: Prediction, bet: str | None = None, pick: dict | None = None) -> dict:
    green, red = s.cupid.flags(item, pred, s.pool)
    return {
        "id": item.id, "title": item.title, "price": item.price, "old_price": item.old_price,
        "brand": item.brand, "rating": item.rating, "reviews": item.reviews, "bought": item.bought,
        "store": item.store, "link": item.link, "image": f"/images/{item.image}", "n_stores": item.n_stores,
        "match": round(pred.p * 100), "slot": slot, "bet": bet,
        "line": pick["why"] if pick else _line(s, item, slot, pred, bet),
        "pick": {"purpose": pick["purpose"], "label": pick["label"], "of": pick.get("of")} if pick else None,
        "green": green, "red": red, "tags": item.tags,
    }


PURPOSE_SLOT = {"best": "best", "test": "test", "surprise": "wild", "alike": "best"}


def _from_plan(s: Session) -> tuple[Item, dict] | None:
    while s.plan:
        p = s.plan.pop(0)
        item = s.pool.by_id.get(p["id"])
        if item and item.id not in s.seen:
            return item, p
    return None


def _wide(s: Session) -> Pool:
    """One search's deck is small: this is the whole catalogue, within what they're shopping for."""
    return Pool(s.pool.items + [it for it in ALL.items if it.id not in s.pool.by_id and any(p.fits(it) for p in s.picks)])


def _queue_alikes(s: Session, item: Item, k: int):
    """You loved a dress: its closest look-alikes come next.
    Like one of those too and it brings its own look-alikes, so Cupid leans in for as long as you do."""
    found = s.cupid.lookalikes(_wide(s), s.seen | {p["id"] for p in s.plan}, item, k)
    new = [it for it in found if it.id not in s.pool.by_id]
    if new:
        s.pool = Pool(s.pool.items + new)
    s.plan[:0] = [{"id": it.id, "purpose": "alike", "label": "Like the one you loved",
                      "why": "Looks like a dress you loved", "from": item.id, "of": f"/images/{item.image}"}
                     for it in found]


def _deal(s: Session) -> dict | None:
    if s.current is None:
        card = s.cupid.next_card(s.pool, s.seen)
        if card is None:
            return None
        item, slot, pred = card
        pick = None
        # Cupid's LLM chooses the cards, apart from the warm-up and the random control group
        # it's measured against. Until its first plan arrives, the engine's choice stands.
        # Look-alikes of a dress you just loved always come first.
        urgent = bool(s.plan) and s.plan[0]["purpose"] == "alike"
        if urgent or slot not in ("warmup", "random"):
            planned = _from_plan(s)
            if planned:
                item, pick = planned
                slot, pred = PURPOSE_SLOT[pick["purpose"]], s.cupid.predict(item)
                s.planned_shown += pick["purpose"] != "alike"   # that one's the image model's, not Claude's
        bet = None
        if s.cupid.n >= CALLED_SHOT_FROM:
            bet = "like" if pred.p >= BET_CONFIDENCE else "nope" if pred.p <= 1 - BET_CONFIDENCE else None
        s.current = {"item": item, "slot": slot, "pred": pred, "bet": bet, "pick": pick}
    c = s.current
    return _card(s, c["item"], c["slot"], c["pred"], c["bet"], c.get("pick"))


@app.get("/api/sessions/{sid}/next")
def next_card(sid: str):
    s = get_session(sid)
    with s.lock:
        card = _deal(s)
    if card is None:
        raise HTTPException(410, "Cupid has shown you everything in this search")
    return card


def _cupid_search(s: Session) -> tuple[Pick, AmazonSearch] | None:
    """Cupid's own search: your answer and your filters, plus Amazon's filters for what Cupid
    has the strongest evidence you like, in the groups you left open."""
    pick = s.picks[0]
    filters = _filters(pick)
    ev = s.cupid.explainable()
    wanted = []
    for key in amazon.SHOPPABLE:
        if any(g in pick.chosen for g, (k, _) in amazon.FILTER_GROUPS.items() if k == key):
            continue   # you set this one yourself
        value = s.cupid.favourite(key)
        option = amazon.option_for(filters, key, value) if value else None
        if option:
            wanted.append((ev[f"{key}:{value}"], key, value, option))
    wanted = sorted(wanted, reverse=True)[:CUPID_FILTERS]
    if not wanted:
        return None   # nothing learned yet that Amazon can filter on
    yours = amazon.split_rh(pick.deck_search.rh)
    node = amazon.category_node(filters, pick.node)
    rh = amazon.combine_rh(([node] if node else []) + yours + [option[1] for *_, option in wanted])
    words = [pick.deck_search.label] + [f"+ {option[0]}" for *_, option in wanted]
    return pick, AmazonSearch(k=pick.base.k, rh=rh,
                              tags=pick.deck_search.tags + tuple((key, value) for _, key, value, _ in wanted),
                              label=" ".join(words))


def _go_shopping(s: Session):
    """Cupid goes shopping: its LLM writes the search when it can, else the rule above does."""
    with db_lock:
        budget_left = db.calls_last_24h(conn) < SERPAPI_DAILY_LIMIT
    # Only ask the LLM when a new search could actually run; otherwise the rule's cached search will do.
    if (agent.available() and s.profile and budget_left and s.live_used < LIVE_SEARCHES_PER_SESSION
            and s.shop_asks < LIVE_SEARCHES_PER_SESSION):
        s.shop_asks += 1
        s.worker.submit(_agent_shop, s, s.picks[0])
        return
    planned = _cupid_search(s)
    if planned:
        _launch(s, *planned)


def _agent_shop(s: Session, pick: Pick):
    """Cupid's LLM chooses which of Amazon's real filters to add to the shopper's search."""
    filters = _filters(pick)
    menu = [m for m in amazon.filter_menu(filters) if m["group"] not in pick.chosen and m["group"] not in amazon.SIZE_GROUPS]
    # Amazon lists the most common options first; the top few per group keep the call small.
    options = {f"{m['label']}: {o['name']}": (m["group"], o) for m in menu for o in m["options"][:SHOP_OPTIONS]}
    already = [x["query"] for x in s.searches if x["by"] == "cupid"]
    out, chosen = None, []
    if options:
        try:
            out = agent.shop(s.profile, s.context, list(s.experiments), pick.deck_search.label, list(options), already)
        except agent.AgentError as e:
            _event(s, "error", f"Cupid couldn't plan its search: {e}")
        for name in (out or {}).get("filters", []):
            group, option = options.get(name, (None, None))
            if group and group not in {g for g, _ in chosen}:
                chosen.append((group, option))
    with s.lock:
        if not chosen:
            planned = _cupid_search(s)
            if planned:
                _launch(s, *planned)
            return
        chosen = chosen[:3]
        # Like the shopper's own filters: one material/fit/pattern is guaranteed on every result; colour isn't.
        certain = tuple(m for g, o in chosen if g not in amazon.COLOUR_GROUPS and (m := amazon.to_vocab(g, o["name"])))
        node = amazon.category_node(filters, pick.node)
        rh = amazon.combine_rh(([node] if node else []) + amazon.split_rh(pick.deck_search.rh) + [o["rh"] for _, o in chosen])
        search = AmazonSearch(k=pick.base.k, rh=rh, tags=pick.deck_search.tags + certain,
                              label=" ".join([pick.deck_search.label] + [f"+ {o['name']}" for _, o in chosen]))
        _launch(s, pick, search, why=out["why"])


def _launch(s: Session, pick: Pick, search: AmazonSearch, why: str | None = None):
    """Run one of Cupid's searches in the background and add what it finds to the deck."""
    if any(x.get("key") == search.key() for x in s.searches):
        return
    entry = {"round": s.cupid.n // ROUND_SIZE + 1, "query": search.label, "by": "cupid", "source": "pending",
             "items": 0, "key": search.key(), "why": why}
    s.searches.append(entry)
    with db_lock:
        cached = db.get_search(conn, search.key()) is not None
    if not cached and s.live_used >= LIVE_SEARCHES_PER_SESSION:
        entry["source"] = "skipped (session limit)"
        return

    def run():
        try:
            items, source = _fetch(search)
        except SerpError as e:
            entry["source"] = f"skipped ({e})"
            return
        with s.lock:
            s.live_used += source == "live"
            items = [it for it in items if pick.fits(it)]
            fresh = [it for it in items if it.id not in s.pool.by_id and s.cupid.allowed(it)]
            if fresh:
                s.pool = Pool(s.pool.items + fresh)
            pick.items.update(it.id for it in items)
            s.shopped.update(it.id for it in fresh)
            entry.update(source=source, items=len(fresh))

    threading.Thread(target=run, daemon=True).start()


def _payoff(s: Session) -> dict:
    """End of a round: what you liked, and your type. Cupid's read on you and its questions arrive by their own endpoint."""
    log = s.cupid.log[-ROUND_SIZE:]
    return {
        "round": s.cupid.n // ROUND_SIZE,
        "liked": sum(x.liked for x in log),
        "swipes": len(log),
        "your_type": s.cupid.your_type(),
    }


def _event(s: Session, kind: str, text: str, item: Item | None = None, **extra):
    with s.lock:
        s.events.append({"id": len(s.events), "type": kind, "text": text,
                         "item": {"id": item.id, "image": f"/images/{item.image}", "title": item.title} if item else None,
                         **extra})


def _allowed(s: Session) -> list[str]:
    """Attribute ids the agent may hold beliefs about: the ones present in this deck."""
    return sorted({f for it in s.pool.items for f in it.features if not f.startswith("group:")})


TURN_MIN = 0.15   # a belief has to move at least this much to count as a change of mind


def _stance(profile: dict | None) -> dict[str, float]:
    """What a profile believes: attribute → strength, likes positive and dislikes negative."""
    if not profile:
        return {}
    out = {b["attribute"]: b["strength"] for b in profile.get("likes", [])}
    out.update({b["attribute"]: -b["strength"] for b in profile.get("dislikes", [])})
    return out


def _change(f: str, before: float, after: float) -> str:
    name = _label(f)
    if not before:
        return f"New {'like' if after > 0 else 'dislike'}: {name}"
    if not after:
        return f"Dropped: {name}"
    if (before > 0) != (after > 0):
        return f"{name.capitalize()}: {'dislike → like' if after > 0 else 'like → dislike'}"
    return f"{'More' if abs(after) > abs(before) else 'Less'} sure about {name}"


def _turn(old: dict | None, new: dict) -> tuple[float, list[str]]:
    """How far one swipe moved Cupid's mind, and the biggest changes in words."""
    if old is None:   # the first swipe forms a first impression; nothing to change yet
        return 0.0, []
    a, b = _stance(old), _stance(new)
    moved = sorted(((abs(b.get(f, 0.0) - a.get(f, 0.0)), f) for f in set(a) | set(b)), reverse=True)
    return round(sum(d for d, _ in moved), 2), [_change(f, a.get(f, 0.0), b.get(f, 0.0)) for d, f in moved[:3] if d >= TURN_MIN]


def _agent_learn(s: Session, item: Item, action: str, n: int):
    """Cupid's LLM mind reads the swipe and rewrites its profile of the shopper."""
    try:
        profile = agent.learn(s.profile, item, IMAGE_DIR / item.image, action, s.context, s.history, _allowed(s))
    except agent.AgentError as e:
        _event(s, "error", f"Cupid's mind is offline: {e}")
        return
    shift, changes = _turn(s.profile, profile)
    allowed = set(_allowed(s))
    beliefs, reasons = {}, {}
    for sign, key in ((1, "likes"), (-1, "dislikes")):
        for b in profile.get(key, []):
            if b["attribute"] in allowed:
                beliefs[b["attribute"]] = sign * BELIEF_WEIGHT * max(0.0, min(1.0, b["strength"]))
                reasons[b["attribute"]] = b["why"]
    with s.lock:
        s.profile = profile
        # Drop reasons for beliefs Cupid has let go of, so a card never quotes an old idea.
        for f in set(s.cupid.beliefs) - set(beliefs):
            s.cupid.stated.reasons.pop(f, None)
        s.cupid.beliefs = beliefs                # the next cards are ranked with what it just learned
        s.cupid.stated.reasons.update(reasons)   # and its own words explain the flags
        s.thoughts.append({"n": n, "text": profile["thought"], "by": "llm", "action": action, "shift": shift,
                           "changes": changes, "item": {"image": f"/images/{item.image}", "title": item.title},
                           "stance": {f: round(v, 2) for f, v in _stance(profile).items()}})
    with db_lock:
        db.save_profile(conn, s.id, profile)
    _event(s, "thought", profile["thought"])


PAIR_SIDE = 12   # best-rated dresses on each side of a this-or-that, paired by how alike they look


def _pair(s: Session, a: str, b: str, used: set[str]) -> tuple[Item, Item] | None:
    """A real dress for each side of a this-or-that. Both are ones Cupid rates, and they look as alike as
    possible otherwise, so the tap is about the one thing that differs."""
    pool = _wide(s)
    open_ = [it for it in pool.items if it.id not in s.seen and it.id not in used and s.cupid.allowed(it)]
    sides = []
    for f, g in ((a, b), (b, a)):
        items = [it for it in open_ if f in it.features and g not in it.features]
        if not items:
            return None
        preds = s.cupid.predict_many(items)
        sides.append([it for it, _ in sorted(zip(items, preds), key=lambda x: -x[1].p)[:PAIR_SIDE]])
    sims = np.stack([x.emb for x in sides[0]]) @ np.stack([x.emb for x in sides[1]]).T
    i, j = np.unravel_index(int(np.argmax(sims)), sims.shape)
    return sides[0][i], sides[1][j]


def _agent_interview(s: Session, rnd: int):
    """Near a round's end: Cupid's read on the shopper, and the this-or-that questions it most wants answered."""
    ask = s.asks[rnd]
    with s.lock:
        options = [f for f in _allowed(s) if f not in s.answered]
        answered = [_label(f) for f in s.answered]
    try:
        out = agent.interview(s.profile, s.context, s.history, s.experiments, options, answered)
    except agent.AgentError:
        ask["status"] = "done"   # no read, no questions: the round's end falls back to your type
        return
    questions, used = [], set()
    with s.lock:
        for q in out["questions"]:
            a, b = q["a"], q["b"]
            if a == b or a.split(":")[0] != b.split(":")[0] or not {a, b} <= set(options):
                continue
            if any({a, b} & {x["a"]["attribute"], x["b"]["attribute"]} for x in questions):
                continue
            pair = _pair(s, a, b, used)
            if not pair:
                continue
            used |= {pair[0].id, pair[1].id}
            questions.append({"question": q["question"], "a_reply": q["a_reply"], "b_reply": q["b_reply"],
                              "a": {"attribute": a, "label": _label(a), "id": pair[0].id, "image": f"/images/{pair[0].image}"},
                              "b": {"attribute": b, "label": _label(b), "id": pair[1].id, "image": f"/images/{pair[1].image}"},
                              "answer": None, "reply": None})
        ask.update(read=out["read"], questions=questions[:agent.QUESTIONS], status="done")


@app.get("/api/sessions/{sid}/questions/{rnd}")
def questions(sid: str, rnd: int):
    s = get_session(sid)
    with s.lock:
        return s.asks.get(rnd) or {"status": "none", "read": None, "questions": []}


class AnswerIn(BaseModel):
    answer: Literal["a", "b", "neither"]


@app.post("/api/sessions/{sid}/questions/{rnd}/{i}")
def answer(sid: str, rnd: int, i: int, body: AnswerIn):
    """The shopper answers one of Cupid's this-or-thats. Their own word counts for good, and doesn't fade:
    the side they picked goes up and the other down; neither pushes both down a little."""
    s = get_session(sid)
    with s.lock:
        qs = (s.asks.get(rnd) or {}).get("questions", [])
        if not 0 <= i < len(qs):
            raise HTTPException(404, "no such question")
        q = qs[i]
        if q["answer"]:
            return q
        a, b = q["a"], q["b"]
        if body.answer == "neither":
            s.cupid.told[a["attribute"]] = s.cupid.told[b["attribute"]] = -TOLD / 2
            q["reply"], changes, shown = "Noted, neither. I'll keep looking.", [f"Less keen on: {a['label']}", f"Less keen on: {b['label']}"], a
            picked = "neither"
        else:
            win, lose = (a, b) if body.answer == "a" else (b, a)
            s.cupid.told[win["attribute"]], s.cupid.told[lose["attribute"]] = TOLD, -TOLD
            q["reply"], changes, shown = q[f"{body.answer}_reply"], [f"You want: {win['label']}", f"Less keen on: {lose['label']}"], win
            picked = win["label"]
        q["answer"] = body.answer
        s.answered += [a["attribute"], b["attribute"]]
        s.history.append(f"You asked \"{q['question']}\" ({a['label']} or {b['label']}). They picked: {picked}.")
        s.thoughts.append({"n": s.cupid.n, "text": q["reply"], "by": "llm", "action": "told", "shift": TOLD,
                           "changes": changes, "item": {"image": shown["image"], "title": q["question"]},
                           "question": q["question"]})
    return q


@app.get("/api/sessions/{sid}/tryons")
def tried_on(sid: str):
    """Every dress the shopper has tried on (their super likes), newest first, with Cupid's verdict on each."""
    s = get_session(sid)
    with s.lock:
        looks = [(t["item"], t["tryon"], s.verdicts.get(t["item"])) for t in reversed(s.tryons) if t.get("tryon")]
    out = []
    for item_id, tryon, verdict in looks:
        item = ALL.by_id.get(item_id)
        if item:
            out.append({"id": item.id, "title": item.title, "price": item.price, "link": item.link,
                        "image": f"/images/{item.image}", "tryon": tryon,
                        "verdict": verdict if verdict and "verdict" in verdict else None})
    return out


def _agent_plan(s: Session):
    """Cupid's LLM reviews its experiments and picks the next cards from the engine's shortlist."""
    try:
        with s.lock:
            queued = {p["id"] for p in s.plan} | ({s.current["item"].id} if s.current else set())
            shortlist = s.cupid.shortlist(s.pool, s.seen | queued, must=s.shopped - s.seen)
            ids = {f"c{i + 1}": item for i, (item, _) in enumerate(shortlist)}
            candidates = [(f"c{i + 1}", agent.describe(item) + f" Match {round(pred.p * 100)}%."
                           + (" New from your own Amazon search." if item.id in s.shopped else ""))
                          for i, (item, pred) in enumerate(shortlist)]
            profile, history, experiments = s.profile, list(s.history), list(s.experiments)
        if not candidates:
            return
        try:
            out = agent.plan(profile, s.context, history, experiments, candidates)
        except agent.AgentError as e:
            _event(s, "error", f"Cupid couldn't plan the next cards: {e}")
            return
        picks = []
        for p in out["picks"]:
            item = ids.get(p["id"])
            if item and item.id not in {x["id"] for x in picks}:
                picks.append({"id": item.id, "purpose": p["purpose"], "label": p["label"], "why": p["why"]})
        with s.lock:
            s.experiments = out["experiments"][:4]
            s.plan += picks[:agent.PLAN_SIZE]
    finally:
        s.planning = False


@app.get("/api/sessions/{sid}/events")
def events(sid: str, after: int = -1):
    """What Cupid's mind has thought and decided since `after` (the app polls this)."""
    s = get_session(sid)
    with s.lock:
        return [e for e in s.events if e["id"] > after]


def _label(f: str) -> str:
    key, value = f.split(":", 1)
    return _LABELS.get(key, lambda v: v)(value).lower()


def _thought(item: Item, record, pred: Prediction, before: dict, after: dict) -> str:
    """What Cupid concluded from one swipe, in a sentence: the visible part of the learning."""
    moved = sorted(((after.get(f, 0.0) - before.get(f, 0.0), f) for f in item.features
                    if f.split(":", 1)[0] not in ("group", "tone", "category")), key=lambda d: -abs(d[0]))
    delta, feature = moved[0] if moved else (0.0, None)
    sure = round(100 * max(pred.p, 1 - pred.p))
    if record.action == "noton":
        return f"Good to know: {_label(feature)} doesn't work on you." if feature else "Noted: not on you."
    if (pred.p >= 0.5) == record.liked and sure >= 70:
        return f"Called it. I was {sure}% sure."
    if record.liked and pred.p < 0.4:
        return f"Didn't see that coming. Rethinking {_label(feature)}." if feature else "Didn't see that coming."
    if not record.liked and pred.p > 0.6:
        return f"I was sure about that one. Less {_label(feature)} from now on." if feature else "Noted."
    if not feature:
        return "Noted."
    return f"Noted: {'more' if delta > 0 else 'less'} {_label(feature)}."


@app.post("/api/sessions/{sid}/swipe")
def swipe(sid: str, body: SwipeIn):
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {ACTIONS}")
    s = get_session(sid)
    with s.lock:
        c = s.current
        if not c or c["item"].id != body.item_id:
            raise HTTPException(409, "that card isn't the one on screen")
        item, pred, bet = c["item"], c["pred"], c["bet"]
        before = s.cupid.relative()
        record = s.cupid.swipe(item, body.action, body.dwell_ms, c["slot"], pred)
        thought = _thought(item, record, pred, before, s.cupid.relative())
        s.thoughts.append({"n": record.n, "text": thought})
        s.history.append(f"{record.n + 1}. {agent.describe(item)} → {body.action}")
        if agent.available():
            s.worker.submit(_agent_learn, s, item, body.action, record.n)
            # Then, with what it just learned, it picks the next few cards before the queue runs dry.
            if s.cupid.n >= WARMUP - 1 and len(s.plan) <= 1 and not s.planning:
                s.planning = True
                s.worker.submit(_agent_plan, s)
            rnd = s.cupid.n // ROUND_SIZE + 1
            if s.cupid.n % ROUND_SIZE == ASK_AT and rnd not in s.asks:
                s.asks[rnd] = {"status": "thinking", "read": None, "questions": []}
                # Its own thread: behind a fast swiper's queue of learn and plan calls it would miss the round's end.
                threading.Thread(target=_agent_interview, args=(s, rnd), daemon=True).start()
        s.seen.add(item.id)
        s.current = None
        with db_lock:
            db.record_swipe(conn, s.id, record)
        if body.action in ALIKE:
            _queue_alikes(s, item, ALIKE[body.action])
        elif (c.get("pick") or {}).get("from"):
            # Passed on a look-alike: the look wasn't what they loved, so drop the rest of them.
            s.plan = [p for p in s.plan if p.get("from") != c["pick"]["from"]]

        predicted = (body.action == "crush" and pred.p >= FIT_CRUSH) or (body.action == "like" and pred.p >= FIT_LIKE)
        cooled = not s.fits or record.n - s.fits[-1] >= FIT_COOLDOWN
        result = {"its_a_fit": predicted and cooled, "called_it": None, "thought": thought,
                  "early_refresh": False, "payoff": None, "swipes": s.cupid.n}
        if result["its_a_fit"]:
            s.fits.append(record.n)
        if bet:
            right = (bet == "like") == record.liked
            s.bets.append({"n": record.n, "bet": bet, "right": right})
            result["called_it"] = right
        if s.cupid.n % ROUND_SIZE == SHOP_AT:
            _go_shopping(s)
        elif s.cupid.should_refresh_early():
            result["early_refresh"] = True
            _go_shopping(s)
        if s.cupid.n % ROUND_SIZE == 0:
            result["payoff"] = _payoff(s)
        result["next"] = _deal(s)
    return result


@app.post("/api/sessions/{sid}/rewind")
def rewind(sid: str):
    s = get_session(sid)
    with s.lock:
        item_id = s.cupid.rewind()
        if item_id is None:
            raise HTTPException(400, "nothing to rewind")
        s.seen.discard(item_id)
        s.bets = [b for b in s.bets if b["n"] < s.cupid.n]
        s.fits = [n for n in s.fits if n < s.cupid.n]
        s.plan = [p for p in s.plan if p.get("from") != item_id]   # the look-alikes that like brought on
        with db_lock:
            db.delete_last_swipe(conn, s.id)
        item = ALL.by_id.get(item_id) or s.pool.by_id[item_id]
        s.current = {"item": item, "slot": "rewind", "pred": s.cupid.predict(item), "bet": None}
        return _deal(s)


@app.post("/api/sessions/{sid}/tryon/{item_id}")
def try_on(sid: str, item_id: str):
    """Super like: render the shopper wearing this dress (YouCam Clothes Try-On), with pros and cons."""
    s = get_session(sid)
    item = ALL.by_id.get(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    if not s.photo:
        raise HTTPException(400, "Add a photo of yourself to try things on")
    s.photo.done.wait(PHOTO_WAIT)
    if not s.photo.file_id:
        raise HTTPException(503, f"Your photo couldn't be prepared for try-on ({s.photo.error or 'not ready'})")
    out = youcam.TRYON_DIR / f"{s.photo.path.stem}_{item.id}.jpg"
    started = time.time()
    try:
        youcam.try_on(s.photo.file_id, IMAGE_DIR / item.image, out)
    except youcam.YouCamError as e:
        raise HTTPException(502, f"Try-on didn't work for this one ({e})")
    verdict = None
    if agent.available():
        try:
            verdict = agent.judge(s.profile, item, IMAGE_DIR / item.image, s.context, tryon=out)
        except agent.AgentError as e:
            verdict = {"error": str(e)}
    with s.lock:
        s.tryons.append({"item": item.id, "seconds": round(time.time() - started, 1), "tryon": f"/tryon/{out.name}"})
        if verdict and "verdict" in verdict:
            s.verdicts[item.id] = verdict
        card = _card(s, item, "tryon", s.cupid.predict(item))
    return {"image": f"/tryon/{out.name}", "card": card, "verdict": verdict}


@app.get("/api/sessions/{sid}/matches")
def matches(sid: str):
    """Everything you liked, crushes first, with today's flags."""
    s = get_session(sid)
    with s.lock:
        liked = [x for x in s.cupid.log if x.liked]
        order = sorted(liked, key=lambda x: (x.action != "crush", -x.n))
        items = [ALL.by_id[x.item_id] for x in order if x.item_id in ALL.by_id]
        preds = s.cupid.predict_many(items) if items else []
        # The dresses they tried on show that way here too.
        looks = {t["item"]: t["tryon"] for t in s.tryons if t.get("tryon")}
        return [dict(_card(s, it, "match", p), action=x.action, verdict=s.verdicts.get(it.id), tryon=looks.get(it.id))
                for it, p, x in zip(items, preds, order)]


# ---------- analytics ----------

MIND_ROWS, MIND_SWIPES = 10, 48   # the heatmap of Cupid's mind: its strongest beliefs, over the latest swipes


def _mind_map(s: Session) -> dict:
    """What Cupid believed after each swipe: attribute rows × swipe columns, + like / − dislike.
    Rows are the beliefs it held most strongly at any point, ordered by where they ended up."""
    steps = [t for t in s.thoughts if "stance" in t][-MIND_SWIPES:]
    if not steps:
        return {"swipes": [], "rows": [], "told": []}
    peak: dict[str, float] = {}
    for t in steps:
        for f, v in t["stance"].items():
            peak[f] = max(peak.get(f, 0.0), abs(v))
    final = steps[-1]["stance"]
    rows = sorted(sorted(peak, key=lambda f: -peak[f])[:MIND_ROWS], key=lambda f: -final.get(f, 0.0))
    return {"swipes": [t["n"] + 1 for t in steps],
            "rows": [{"label": _label(f), "values": [t["stance"].get(f, 0.0) for t in steps]} for f in rows],
            "told": [{"after": t["n"], "question": t.get("question"), "changes": t["changes"]}
                     for t in s.thoughts if t.get("action") == "told"]}


def _report(s: Session) -> dict:
    rel, ev = s.cupid.relative(), s.cupid.explainable()
    taste = [kv for kv in sorted(ev.items(), key=lambda kv: -abs(kv[1])) if kv[1]][:12]
    recent = []
    for x in s.cupid.log[-12:][::-1]:
        it = ALL.by_id.get(x.item_id)
        if it:
            recent.append({"title": it.title, "image": f"/images/{it.image}", "action": x.action,
                           "match": round(x.p_before * 100), "correct": x.correct, "slot": x.slot})
    # With the LLM on, its thoughts replace the engine's one-liners rather than doubling up.
    thoughts = [t for t in s.thoughts if t.get("by") == "llm"] or s.thoughts
    return {
        "session": s.id,
        "goal": " + ".join(p.deck_search.label for p in s.picks),
        "swipes": s.cupid.n,
        "minutes": round(sum(x.dwell_ms for x in s.cupid.log) / 60000, 1),
        "report": metrics.report(s.cupid.log),
        "taste": [{"feature": f, "label": _LABELS.get(f.split(":", 1)[0], lambda v: v)(f.split(":", 1)[1]),
                   "score": round(rel[f], 3), "evidence": round(e, 2)} for f, e in taste],
        "your_type": s.cupid.your_type(),
        "searches": [{k: v for k, v in x.items() if k != "key"} for x in s.searches],
        "bets": {"made": len(s.bets), "right": sum(b["right"] for b in s.bets)},
        "recent": recent,
        "thoughts": [{k: v for k, v in t.items() if k != "item"} for t in thoughts[-14:][::-1]],
        # What they told Cupid, then the swipes that moved its mind most, in the order they happened.
        "turning_points": sorted(sorted((t for t in s.thoughts if t.get("changes")),
                                        key=lambda t: (t["action"] != "told", -t["shift"]))[:4], key=lambda t: t["n"]),
        "profile": s.profile,
        "mind_map": _mind_map(s),
        "experiments": s.experiments,
        "planned_shown": s.planned_shown,
        "llm": agent.MODEL if agent.available() else None,
        "colouring": s.photo.colouring if s.photo else None,
        "tryons": len(s.tryons),
    }


@app.get("/api/sessions/{sid}/report")
def report(sid: str):
    s = get_session(sid)
    with s.lock:
        return _report(s)


@app.get("/api/board")
def board():
    """The live board on the projector follows whoever swiped most recently."""
    if not SESSIONS:
        return {"live": None}
    s = max(SESSIONS.values(), key=lambda x: x.last_active if x.cupid.n else 0)
    with s.lock:
        return {"live": _report(s) if s.cupid.n else None}


@app.get("/api/brand")
def brand():
    """Pooled across every shopper: what's wanted, and where price blocks it."""
    with db_lock:
        rows = db.all_swipes(conn)
        shoppers = {sh["session"]: sh for sh in db.all_shoppers(conn)}
    stats: dict[str, dict] = {}
    for r in rows:
        it = ALL.by_id.get(r["item_id"])
        if not it:
            continue
        for f in it.features:
            d = stats.setdefault(f, {"n": 0, "liked": 0, "pricey": 0})
            d["n"] += 1
            d["liked"] += r["action"] not in NEGATIVE
            d["pricey"] += r["action"] == "pricey"

    def label(f):
        key, value = f.split(":", 1)
        return _LABELS.get(key, lambda v: v)(value)

    solid = {f: d for f, d in stats.items() if d["n"] >= 5}
    loved = sorted(solid.items(), key=lambda kv: -kv[1]["liked"] / kv[1]["n"])[:8]
    blocked = sorted(((f, d) for f, d in solid.items() if d["pricey"]), key=lambda kv: -kv[1]["pricey"] / kv[1]["n"])[:6]
    return {
        "shoppers": len({r["session"] for r in rows}),
        "swipes": len(rows),
        "minutes": round(sum(r["dwell_ms"] for r in rows) / 60000, 1),
        "loved": [{"label": label(f), "like_rate": round(d["liked"] / d["n"], 2), "n": d["n"]} for f, d in loved],
        "too_pricey": [{"label": label(f), "pricey_rate": round(d["pricey"] / d["n"], 2), "n": d["n"]} for f, d in blocked],
        **_brand_insights(rows, shoppers, label),
    }


UNDERTONES = ("warm", "neutral", "cool")
GRID_ROWS, GRID_COLS, GRID_MIN = 8, 6, 3   # heatmap size; a cell needs this many swipes to show a rate


def _grid(rows, row_of, col_of, cols: tuple[str, ...] | None = None) -> dict:
    """Like rates on a grid: rows and columns are the most-swiped values (or the columns given).
    A cell with fewer than GRID_MIN swipes has no rate: too few to mean anything."""
    cells: dict[tuple[str, str], dict] = {}
    for r in rows:
        a, b = row_of(r), col_of(r)
        if a and b:
            d = cells.setdefault((a, b), {"n": 0, "liked": 0})
            d["n"] += 1
            d["liked"] += r["action"] not in NEGATIVE

    def top(i: int, k: int) -> list[str]:
        totals: dict[str, int] = {}
        for key, d in cells.items():
            totals[key[i]] = totals.get(key[i], 0) + d["n"]
        return sorted(totals, key=lambda v: -totals[v])[:k]

    rs, cs = top(0, GRID_ROWS), list(cols) if cols else top(1, GRID_COLS)
    out = [[{"n": (d := cells.get((a, b), {"n": 0, "liked": 0}))["n"],
             "rate": round(d["liked"] / d["n"], 2) if d["n"] >= GRID_MIN else None} for b in cs] for a in rs]
    keep = [i for i, row in enumerate(out) if any(c["rate"] is not None for c in row)]   # a row of all gray says nothing
    return {"rows": [rs[i] for i in keep], "cols": cs, "cells": [out[i] for i in keep]}


def _brand_insights(rows, shoppers: dict, label) -> dict:
    """What only Closet Cupid can tell a brand: how dresses look on real shoppers (YouCam try-on),
    who likes which colour (YouCam skin tone), and why shoppers pass (Cupid's LLM profiles)."""
    # Try-on gap: a super like means "I love it on the model"; the try-on shows it on them.
    tried: dict[str, dict] = {}
    for r in rows:
        sh = shoppers.get(r["session"])
        if r["action"] in ("crush", "noton") and sh and sh["has_photo"] and r["item_id"] in ALL.by_id:
            d = tried.setdefault(r["item_id"], {"tries": 0, "not_on": 0})
            d["tries"] += 1
            d["not_on"] += r["action"] == "noton"
    dresses = sorted(tried.items(), key=lambda kv: (-kv[1]["not_on"], -kv[1]["tries"]))[:6]

    # Colour by undertone (YouCam Skin Tone Analysis), and silhouette by colour: like rates on a grid.
    def tone(r):
        sh = shoppers.get(r["session"])
        return sh and sh["undertone"] in UNDERTONES and sh["undertone"]

    def tag(key):
        return lambda r: (ALL.by_id[r["item_id"]].tags.get(key) if r["item_id"] in ALL.by_id else None)

    # Why shoppers pass: the dislikes Cupid's LLM concluded for each shopper, in its own words.
    why: dict[str, dict] = {}
    profiled = 0
    for sh in shoppers.values():
        if not sh["profile"]:
            continue
        profiled += 1
        for b in json.loads(sh["profile"]).get("dislikes", []):
            d = why.setdefault(b["attribute"], {"shoppers": 0, "strength": 0.0, "why": []})
            d["shoppers"] += 1
            d["strength"] += b["strength"]
            if len(d["why"]) < 2 and b["why"] not in d["why"]:
                d["why"].append(b["why"])
    passes = sorted(why.items(), key=lambda kv: (-kv[1]["shoppers"], -kv[1]["strength"]))[:6]

    return {
        "tryon": {"tries": sum(d["tries"] for d in tried.values()), "not_on": sum(d["not_on"] for d in tried.values()),
                  "dresses": [{"title": ALL.by_id[i].title, "image": f"/images/{ALL.by_id[i].image}", **d} for i, d in dresses]},
        "undertones": {t: sum(sh["undertone"] == t for sh in shoppers.values()) for t in UNDERTONES},
        "undertone_map": _grid(rows, tag("colour"), tone, cols=UNDERTONES),
        "style_map": _grid(rows, tag("silhouette"), tag("colour")),
        "profiled": profiled,
        "dislikes": [{"label": label(f), "shoppers": d["shoppers"], "why": d["why"]} for f, d in passes],
    }


@app.get("/api/status")
def status():
    with db_lock:
        used = db.calls_last_24h(conn)
    return {"items": len(ALL.items), "sessions": len(SESSIONS), "serpapi_calls_24h": used,
            "fashion_model_loaded": _encoder is not None, "llm": agent.MODEL if agent.available() else None,
            "youcam": bool(youcam.YOUCAM_API_KEY)}
