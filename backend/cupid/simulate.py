"""Fake users with known taste, to check the engine learns before any UI exists.

Each persona has hidden attribute scores. It likes an item with probability
sigmoid(sum of its scores), so even a perfect engine can't be right every
time; `ceiling` reports the best accuracy any guesser could reach.
"""

import math
import random

import numpy as np

from .engine import ROUND_SIZE, Cupid, Pool, Stated
from .item import Item
from .tagging import CATEGORIES, COLOURS, FABRICS, FITS, PATTERNS, VIBES, derive_tags

PERSONAS = {
    "earthy minimalist": {
        "bias": -0.5,
        "taste": {"tone:earthy": 1.5, "tone:neutral": 0.6, "pattern:solid": 1.0, "fit:relaxed": 1.2,
                  "fabric:linen": 1.0, "vibe:minimal": 1.2, "pattern:floral": -1.2, "tone:bright": -1.5,
                  "pattern:sequin": -1.5, "price:2.5k-4k": -1.0, "price:4k+": -2.0},
        "stated": Stated(likes=["tone:earthy", "vibe:minimal"], budget=None),
    },
    "festive ethnic": {
        "bias": -0.8,
        "taste": {"group:ethnic": 2.0, "vibe:festive": 1.5, "vibe:ethnic": 1.0, "pattern:embroidered": 1.2,
                  "tone:deep": 1.0, "fabric:silk": 1.0, "group:western": -1.5, "fit:fitted": -0.8,
                  "price:under 500": -0.8},
        "stated": Stated(likes=["group:ethnic"]),
    },
    "streetwear": {
        "bias": -0.6,
        "taste": {"vibe:streetwear": 1.8, "fit:relaxed": 1.5, "colour:black": 1.0, "category:t-shirt": 1.0,
                  "category:jeans": 0.8, "category:trousers": 0.6, "pattern:graphic": 1.0,
                  "group:ethnic": -2.0, "fit:fitted": -1.0, "price:4k+": -2.0, "price:2.5k-4k": -1.0},
        # Says no black, then keeps liking it: "what you say vs what you do".
        "stated": Stated(likes=["vibe:streetwear"], avoid=["colour:black"]),
    },
    "two tastes": {
        "bias": -0.8,
        "taste": {"vibe:office": 1.5, "vibe:minimal": 1.0, "group:ethnic": 1.0, "pattern:block print": 1.2,
                  "tone:neutral": 1.0, "pattern:floral": -1.2, "vibe:party": -1.5, "tone:bright": -1.0,
                  "fit:fitted": -0.8},
        "stated": Stated(),
    },
}


def synthetic_pool(n: int = 1500, dim: int = 64, seed: int = 0) -> Pool:
    """Random catalogue whose fingerprints reflect its tags, like the real model's do."""
    rng = np.random.default_rng(seed)
    vocab = {"category": list(CATEGORIES), "colour": list(COLOURS), "pattern": list(PATTERNS),
             "fabric": list(FABRICS), "fit": list(FITS), "vibe": VIBES}
    direction = {f"{k}:{v}": rng.normal(size=dim) for k, vals in vocab.items() for v in vals}
    items = []
    for i in range(n):
        raw = {k: vals[rng.integers(len(vals))] for k, vals in vocab.items()}
        if rng.random() < 0.4:
            raw["pattern"] = "solid"
        price = float(math.exp(rng.uniform(math.log(300), math.log(5000))))
        emb = sum(direction[f"{k}:{v}"] for k, v in raw.items()) + rng.normal(size=dim) * 0.8
        items.append(Item(id=f"syn{i}", title=f"{raw['colour']} {raw['fabric']} {raw['category']}",
                          price=round(price), tags=derive_tags(raw, price),
                          emb=(emb / np.linalg.norm(emb)).astype(np.float32)))
    return Pool(items)


def like_probability(persona: dict, item: Item) -> float:
    return 1 / (1 + math.exp(-(persona["bias"] + sum(persona["taste"].get(f, 0.0) for f in item.features))))


def respond(persona: dict, item: Item, rng: random.Random) -> tuple[str, int]:
    p = like_probability(persona, item)
    if rng.random() >= p:
        dwell = rng.randint(3500, 6000) if p > 0.4 else rng.randint(700, 2500)
        return "nope", dwell
    pricey = any(persona["taste"].get(f, 0) < 0 for f in item.features if f.startswith("price:"))
    if pricey and rng.random() < 0.5:
        return "pricey", rng.randint(2000, 5000)
    if p > 0.85 and rng.random() < 0.3:
        return "crush", rng.randint(2000, 5000)
    return "like", rng.randint(1200, 4000)


def ranking_scores(scores: np.ndarray, truth: np.ndarray, top: int = 20) -> dict:
    """How well scores rank items, given each item's true like probability.

    pick_right: shown one item you'd like and one you wouldn't, how often the
    liked one scores higher (50% = coin flip). top_liked: expected like rate of
    the `top` highest-scored items.
    """
    higher = scores[:, None] > scores[None, :]
    ties = scores[:, None] == scores[None, :]
    pair_w = truth[:, None] * (1 - truth[None, :])
    np.fill_diagonal(pair_w, 0)
    pick_right = float(((higher + 0.5 * ties) * pair_w).sum() / pair_w.sum())
    top_liked = float(truth[np.argsort(-scores)[:top]].mean())
    return {"pick_right": pick_right, "top_liked": top_liked}


def held_out(cupid: Cupid, persona: dict, items: list[Item]) -> dict:
    """Score Cupid's guesses on items it never dealt, against the true taste."""
    preds = np.array([pr.p for pr in cupid.predict_many(items)])
    truth = np.array([like_probability(persona, it) for it in items])
    return ranking_scores(preds, truth)


def run_session(persona: dict, pool: Pool, swipes: int = 100, seed: int = 0,
                feed: str = "cupid", holdout_size: int = 300) -> tuple[Cupid, dict]:
    """Simulate one person swiping. feed="random" deals random cards (the baseline).

    Returns Cupid and a fair learning curve: ranking scores on a fixed random
    set of items, checked before the first swipe and after every round, next to
    a random ranking and the best possible one (ranking by true taste).
    """
    rng = random.Random(seed)
    holdout = random.Random(seed + 1000).sample(pool.items, min(holdout_size, len(pool.items)))
    truth = np.array([like_probability(persona, it) for it in holdout])

    cupid = Cupid(stated=persona["stated"], seed=seed)
    seen: set[str] = {it.id for it in holdout}   # never deal the test items
    curve = [held_out(cupid, persona, holdout)]
    for i in range(swipes):
        card = cupid.next_card(pool, seen, slot="random" if feed == "random" else None)
        if card is None:
            break
        item, slot, pred = card
        action, dwell = respond(persona, item, rng)
        cupid.swipe(item, action, dwell, slot, pred)
        seen.add(item.id)
        if (i + 1) % ROUND_SIZE == 0:
            curve.append(held_out(cupid, persona, holdout))
    return cupid, {
        "curve": curve,
        "random_top_liked": float(truth.mean()),
        "best": ranking_scores(truth, truth),
    }


def true_lift(persona: dict, pool: Pool) -> dict[str, float]:
    """For each attribute, how much more the persona likes items with it than items
    with an alternative value (e.g. beige vs other colours). This is the fair
    answer key: "beige" counts for a persona who loves earthy tones."""
    by_feature: dict[str, list[float]] = {}
    by_key: dict[str, list[float]] = {}
    for it in pool.items:
        p = like_probability(persona, it)
        for f in it.features:
            by_feature.setdefault(f, []).append(p)
            by_key.setdefault(f.split(":", 1)[0], []).append(p)
    lift = {}
    for f, ps in by_feature.items():
        rest = by_key[f.split(":", 1)[0]]
        others = (sum(rest) - sum(ps)) / max(len(rest) - len(ps), 1)
        lift[f] = sum(ps) / len(ps) - others
    return lift


def type_precision(persona: dict, cupid: Cupid, lift: dict[str, float]) -> float | None:
    """Share of the "Your type" loves that the persona really does like more than the alternatives."""
    loves = [f"{k}:{v}" for k, vals in cupid.your_type()["loves"].items() for v in vals]
    if not loves:
        return None
    return sum(lift.get(f, 0.0) > 0.03 for f in loves) / len(loves)


def taste_recovered(persona: dict, cupid: Cupid) -> float:
    """Share of the persona's strong likes/dislikes Cupid learned with the right sign."""
    strong = {f: v for f, v in persona["taste"].items() if abs(v) >= 1.0}
    if not strong:
        return 1.0
    return sum((cupid.w.get(f, 0.0) > 0) == (v > 0) and cupid.w.get(f, 0.0) != 0 for f, v in strong.items()) / len(strong)
