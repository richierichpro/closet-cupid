"""Cupid's self-learning style engine.

What Cupid remembers about a person:
  - a score for every attribute value (colour:olive, fit:relaxed, price:1k-1.5k, ...)
  - every swiped item's fingerprint, so it can say "looks like something you loved"
  - what they told it (stated likes and dealbreakers), trusted less as swipes pile up

The match % is a logistic model over those three. After each swipe the scores
move in proportion to the surprise (what happened minus what Cupid guessed), so
confident-and-wrong guesses teach the most.
"""

import math
import random
from dataclasses import dataclass, field

import numpy as np

from .item import Item

ROUND_SIZE = 12          # short rounds: the payoff comes quickly
WARMUP = 5               # first cards: mostly your vibes, plus other style families
WARMUP_OWN = (0, 1, 3)   # warm-up cards drawn from the vibes you picked
LR = 0.5                 # attribute learning rate, shrinks as an attribute is seen more
BIAS_LR = 0.1
DECAY = 0.995            # per swipe, so recent taste outweighs old taste
KNN_TAU = 0.05           # how sharply look-alike strength falls off with distance
KNN_PRIOR = 0.3          # keeps the look-alike score near 0 until there's memory
GAMMA_INIT = 1.5         # starting weight of the look-alike score (learned after)
LONG_LOOK_MS = 4000
FAST_MS = 600
NEAR_DUP_SIM = 0.93      # "very similar" for flags and to avoid repeats in a deck
LOOKALIKE_MIN = 0.80     # "clearly similar": most dresses have a few neighbours between this and NEAR_DUP_SIM
RECENT_WINDOW = 10
EARLY_REFRESH_NOPES = 6
FLAG_MIN = 0.25
TOLD = 1.0               # a pick in Cupid's this-or-that: the shopper's own word, and it doesn't fade
# Evidence = score vs alternatives × √(times seen). In simulation, 1.5 made
# "Your type" 88% right (~3 attributes); 1.0 keeps flags ~77% right.
TYPE_MIN_EVIDENCE = 1.5
FLAG_MIN_EVIDENCE = 1.0
FLAG_HUNCH_EVIDENCE = 0.6   # below the flag bar: shown as "Cupid's hunch", worded as unsure
GOOD_RATING, GOOD_RATING_MIN_REVIEWS = 4.2, 100
LOW_RATING, LOW_RATING_MIN_REVIEWS = 3.5, 20
BIG_DISCOUNT = 0.4
TYPE_MAX = 4
# "random" is the control group Cupid is measured against on the board; 15% keeps
# enough of them in a short demo for the comparison to mean something.
SLOT_SHARES = [("best", 0.55), ("test", 0.2), ("wild", 0.1), ("random", 0.15)]
SHORTLIST = 20           # candidates the LLM chooses from when it plans the next cards

# "crush" is a super like confirmed after trying it on ("love it on me"); "noton" is a super
# like that didn't survive the try-on ("not on me"): the style appealed, it doesn't work on you.
ACTIONS = ("nope", "like", "crush", "pricey", "noton")
NEGATIVE = ("nope", "noton")


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Stated:
    likes: list[str] = field(default_factory=list)          # features, e.g. "tone:earthy"
    avoid: list[str] = field(default_factory=list)          # soft dislikes; swipes can overrule
    dealbreakers: list[str] = field(default_factory=list)   # never shown, e.g. "category:crop top"
    budget: float | None = None                             # hard price ceiling
    reasons: dict[str, str] = field(default_factory=dict)   # why a like/avoid was stated, shown on cards


@dataclass
class Prediction:
    p: float
    # (feature, learned score, stated-preference score) for each attribute on the item
    contributions: list[tuple[str, float, float]]
    knn: float                  # -1..1: looks like things you loved (+) or swiped no on (-)
    nearest_liked: str | None
    similar_liked: int          # liked items that are near-duplicates of this one


@dataclass
class Swipe:
    n: int
    round: int
    item_id: str
    action: str
    dwell_ms: int
    p_before: float
    slot: str

    @property
    def liked(self) -> bool:
        return self.action not in NEGATIVE

    @property
    def correct(self) -> bool:
        return (self.p_before >= 0.5) == self.liked


class Pool:
    """The items a session can draw from, with fingerprints stacked once."""

    def __init__(self, items: list[Item]):
        self.items = items
        self.embs = np.stack([it.emb for it in items]) if items else np.zeros((0, 0), np.float32)
        self.by_id = {it.id: it for it in items}


class Cupid:
    def __init__(self, stated: Stated | None = None, seed: int | None = None):
        self.stated = stated or Stated()
        self.w: dict[str, float] = {}
        self.exposure: dict[str, float] = {}
        self.bias = 0.0
        self.gamma = GAMMA_INIT
        self.mem_ids: list[str] = []
        self.mem_embs: list[np.ndarray] = []
        self.mem_y: list[float] = []      # +1 liked, -1 noped
        self.mem_w: list[float] = []      # signal strength
        self.mem_t: list[int] = []        # swipe number, for recency
        self.mem_feats: list[list[str]] = []
        self.n = 0
        # What Cupid's LLM mind currently believes (feature → weight), rewritten after each
        # swipe by agent.learn. Unlike stated preferences these don't fade: they are the
        # agent's up-to-date reading of the evidence.
        self.beliefs: dict[str, float] = {}
        # Answers to Cupid's end-of-round this-or-that: the side they picked up, the other down.
        self.told: dict[str, float] = {}
        self.log: list[Swipe] = []
        self.rng = random.Random(seed)
        self._undo = None

    # ---------- guessing ----------

    @property
    def trust(self) -> float:
        """How much stated preferences count: fully at first, fading with swipes."""
        return 1.0 / (1.0 + self.n / 10)

    def _prior(self, f: str) -> float:
        return 1.0 if f in self.stated.likes else -1.0 if f in self.stated.avoid else 0.0

    def _knn(self, embs: np.ndarray):
        count = len(embs)
        if not self.mem_ids:
            return np.zeros(count), [None] * count, np.zeros(count, int)
        sims = embs @ np.stack(self.mem_embs).T
        y = np.array(self.mem_y)
        strength = np.array(self.mem_w) * DECAY ** (self.n - np.array(self.mem_t))
        k = np.exp((sims - 1) / KNN_TAU) * strength
        score = (k @ y) / (k.sum(axis=1) + KNN_PRIOR)
        liked = y > 0
        if not liked.any():
            return score, [None] * count, np.zeros(count, int)
        liked_sims = np.where(liked, sims, -np.inf)
        nearest = [self.mem_ids[j] for j in liked_sims.argmax(axis=1)]
        return score, nearest, (liked_sims >= NEAR_DUP_SIM).sum(axis=1)

    def predict_many(self, items: list[Item], embs: np.ndarray | None = None) -> list[Prediction]:
        if not items:
            return []
        embs = embs if embs is not None else np.stack([it.emb for it in items])
        knn, nearest, similar = self._knn(embs)
        trust, out = self.trust, []
        for i, it in enumerate(items):
            contribs = [(f, self.w.get(f, 0.0), trust * self._prior(f) + self.beliefs.get(f, 0.0) + self.told.get(f, 0.0)) for f in it.features]
            logit = self.bias + sum(l + s for _, l, s in contribs) + self.gamma * knn[i]
            out.append(Prediction(sigmoid(logit), contribs, float(knn[i]), nearest[i], int(similar[i])))
        return out

    def predict(self, item: Item) -> Prediction:
        return self.predict_many([item])[0]

    # ---------- learning ----------

    def swipe(self, item: Item, action: str, dwell_ms: int = 1500, slot: str = "best",
              pred: Prediction | None = None) -> Swipe:
        """Learn from one swipe. Pass the prediction shown on the card so it's scored as-is."""
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        pred = pred or self.predict(item)
        self._undo = self._snapshot()

        # A try-on verdict is the strongest signal there is: it's about you, not a product photo.
        strength = 2.0 if action in ("crush", "noton") else 1.0
        if action == "nope" and dwell_ms >= LONG_LOOK_MS:
            strength = 0.5      # a long look before nope means they were tempted
        if dwell_ms < FAST_MS:
            strength *= 0.5     # swiping without really looking
        liked = action not in NEGATIVE
        surprise = (1.0 if liked else 0.0) - pred.p

        for f in self.w:
            self.w[f] *= DECAY
        for f in item.features:
            err = surprise
            if action == "pricey" and f.startswith("price:"):
                err = -pred.p   # loved the style, not at this price
            seen = self.exposure.get(f, 0.0)
            self.w[f] = self.w.get(f, 0.0) + LR / math.sqrt(1 + seen) * strength * err
            self.exposure[f] = seen + strength
        self.bias += BIAS_LR * strength * surprise
        self.gamma = max(0.0, self.gamma + LR * strength * surprise * pred.knn)

        self.mem_ids.append(item.id)
        self.mem_embs.append(item.emb)
        self.mem_y.append(1.0 if liked else -1.0)
        self.mem_w.append(strength)
        self.mem_t.append(self.n)
        self.mem_feats.append(item.features)

        record = Swipe(self.n, self.n // ROUND_SIZE, item.id, action, dwell_ms, pred.p, slot)
        self.log.append(record)
        self.n += 1
        return record

    def _snapshot(self):
        return (dict(self.w), dict(self.exposure), self.bias, self.gamma, len(self.mem_ids), self.n)

    def rewind(self) -> str | None:
        """Undo the last swipe ("wait, go back"). Returns the item id to show again."""
        if not self._undo:
            return None
        self.w, self.exposure, self.bias, self.gamma, m, self.n = self._undo
        for lst in (self.mem_ids, self.mem_embs, self.mem_y, self.mem_w, self.mem_t, self.mem_feats):
            del lst[m:]
        item_id = self.log.pop().item_id
        self._undo = None
        return item_id

    # ---------- choosing the next card ----------

    def allowed(self, item: Item) -> bool:
        if self.stated.budget and item.price and item.price > self.stated.budget:
            return False
        return not any(f in self.stated.dealbreakers for f in item.features)

    def unsure_about(self, item: Item, k: int = 2) -> list[str]:
        """The attributes on this card Cupid knows least about: what a test card is testing."""
        ev = self.explainable()
        candidates = [f for f in item.features if f.split(":", 1)[0] not in ("group", "tone", "price", "category")]
        candidates.sort(key=lambda f: (self.exposure.get(f, 0.0), abs(ev.get(f, 0.0))))
        return [_LABELS.get(f.split(":", 1)[0], lambda v: v)(f.split(":", 1)[1]).lower() for f in candidates[:k]]

    def _uncertainty(self, item: Item) -> float:
        if not item.features:
            return 1.0
        return sum(1 / math.sqrt(1 + self.exposure.get(f, 0.0)) for f in item.features) / len(item.features)

    def _open(self, pool: Pool, seen: set[str]) -> list[int]:
        """Pool positions still to show, skipping near-copies of recent cards so the deck doesn't repeat itself."""
        idx = [i for i, it in enumerate(pool.items) if it.id not in seen and self.allowed(it)]
        recent = [pool.by_id[s.item_id].emb for s in self.log[-RECENT_WINDOW:] if s.item_id in pool.by_id]
        if idx and recent:
            fresh = (pool.embs[idx] @ np.stack(recent).T).max(axis=1) < NEAR_DUP_SIM
            idx = [i for i, ok in zip(idx, fresh) if ok] or idx
        return idx

    def lookalikes(self, pool: Pool, seen: set[str], item: Item, k: int = 1) -> list[Item]:
        """Unseen dresses that look like this one: clearly similar to it, but not near-copies of it or each other."""
        idx = self._open(pool, seen)
        if not idx:
            return []
        sims = pool.embs[idx] @ item.emb
        out: list[Item] = []
        for j in np.argsort(-sims):
            if sims[j] >= NEAR_DUP_SIM:
                continue
            if sims[j] < LOOKALIKE_MIN or len(out) == k:
                break
            it = pool.items[idx[j]]
            if all(it.emb @ o.emb < NEAR_DUP_SIM for o in out):
                out.append(it)
        return out

    def shortlist(self, pool: Pool, seen: set[str], k: int = SHORTLIST, must: set[str] = frozenset()):
        """Candidates for Cupid's LLM to choose from: the best bets, the cards with the most to learn,
        and a few at random so it can surprise. Items in `must` (fresh from its own search) go first."""
        idx = self._open(pool, seen)
        if not idx:
            return []
        items = [pool.items[i] for i in idx]
        preds = self.predict_many(items, pool.embs[idx])
        order = list(range(len(items)))
        chosen = [j for j in order if items[j].id in must][:k // 4]

        def add(ranked, n):
            for j in ranked:
                if n <= 0 or len(chosen) >= k:
                    return
                if j not in chosen:
                    chosen.append(j)
                    n -= 1

        add(sorted(order, key=lambda j: -preds[j].p), k // 2)
        add(sorted(order, key=lambda j: -4 * preds[j].p * (1 - preds[j].p) * self._uncertainty(items[j])), k // 4)
        add(self.rng.sample(order, len(order)), k)
        return [(items[j], preds[j]) for j in chosen]

    def next_card(self, pool: Pool, seen: set[str], slot: str | None = None):
        """Pick the next card. Returns (item, slot, prediction) or None if the pool is used up."""
        idx = self._open(pool, seen)
        if not idx:
            return None

        items = [pool.items[i] for i in idx]
        preds = self.predict_many(items, pool.embs[idx])

        if slot is None:
            if self.n < WARMUP:
                slot = "warmup"
            else:
                r, slot = self.rng.random(), "best"
                for name, share in SLOT_SHARES:
                    if r < share:
                        slot = name
                        break
                    r -= share

        if slot == "warmup":
            # Mostly the vibes you picked, taking turns; the rest explore other style families,
            # so Cupid can still find out you love something you didn't ask for.
            mine = [f.split(":", 1)[1] for f in self.stated.likes if f.startswith("vibe:")]
            shown = [pool.by_id[s.item_id].tags.get("vibe") for s in self.log
                     if s.slot == "warmup" and s.item_id in pool.by_id]
            if mine and self.n in WARMUP_OWN:
                want = min(mine, key=shown.count)
                choices = [j for j, it in enumerate(items) if it.tags.get("vibe") == want]
            else:
                choices = [j for j, it in enumerate(items) if it.tags.get("vibe") not in set(shown) | set(mine)]
            j = max(choices or range(len(items)), key=lambda j: preds[j].p)
        elif slot == "test":
            # Most to learn: Cupid is on the fence and hasn't seen these attributes much.
            j = max(range(len(items)), key=lambda j: 4 * preds[j].p * (1 - preds[j].p) * self._uncertainty(items[j]))
        elif slot == "wild":
            # Best item from the style family Cupid knows least about.
            vibes = {it.tags.get("vibe") for it in items if it.tags.get("vibe")}
            if vibes:
                least = min(vibes, key=lambda v: self.exposure.get(f"vibe:{v}", 0.0))
                pick = [j for j, it in enumerate(items) if it.tags.get("vibe") == least]
                j = max(pick, key=lambda j: preds[j].p)
            else:
                j = self.rng.randrange(len(items))
        elif slot == "random":
            j = self.rng.randrange(len(items))   # the baseline Cupid is measured against
        else:
            j = max(range(len(items)), key=lambda j: preds[j].p)
        return items[j], slot, preds[j]

    def should_refresh_early(self) -> bool:
        """A run of nopes means Cupid is reading this person wrong: go shopping again."""
        tail = self.log[-EARLY_REFRESH_NOPES:]
        return len(tail) == EARLY_REFRESH_NOPES and not any(s.liked for s in tail)

    # ---------- explaining ----------

    def relative(self) -> dict[str, float]:
        """Each attribute's score compared with its alternatives (other fits, other colours...).

        Cupid mostly deals cards it expects you to like, so attributes that turn
        up on many cards soak up some general "likes most things" signal. Raw
        scores are right for guessing; for explaining taste, "relaxed" should
        only count if it beats the other fits.
        """
        totals: dict[str, list[float]] = {}
        for f, score in self.w.items():
            seen = self.exposure.get(f, 0.0)
            t = totals.setdefault(f.split(":", 1)[0], [0.0, 0.0])
            t[0] += score * seen
            t[1] += seen
        return {f: s - totals[f.split(":", 1)[0]][0] / max(totals[f.split(":", 1)[0]][1], 1e-9)
                for f, s in self.w.items()}

    def evidence(self) -> dict[str, float]:
        """Relative score weighted by how often Cupid has seen the attribute."""
        return {f: r * math.sqrt(self.exposure.get(f, 0.0)) for f, r in self.relative().items()}

    def explainable(self) -> dict[str, float]:
        """Evidence, minus any claim the person's own swipes visibly contradict.

        The model can blame "kurta" for nopes that were really about price.
        Telling someone who liked 17 of 18 kurtas they're "not feeling kurtas"
        is wrong in a way they can see, so a claim must agree with the plain
        like rate: a like-claim needs an above-usual like rate, and vice versa.
        """
        counts: dict[str, list[int]] = {}
        for feats, y in zip(self.mem_feats, self.mem_y):
            for f in feats:
                c = counts.setdefault(f, [0, 0])
                c[0] += y > 0
                c[1] += 1
        usual = sum(y > 0 for y in self.mem_y) / len(self.mem_y) if self.mem_y else 0.5
        out = {}
        for f, e in self.evidence().items():
            likes, n = counts.get(f, (0, 0))
            if n >= 3 and ((e > 0 and likes / n < usual) or (e < 0 and likes / n > usual)):
                e = 0.0
            out[f] = e
        return out

    def flags(self, item: Item, pred: Prediction, pool: Pool | None = None) -> tuple[list[str], list[str]]:
        """Green and red flags: the parts of the guess pulling up and pulling down."""
        green, red, hunch_green, hunch_red = [], [], [], []
        rel, ev = self.relative(), self.explainable()
        # Learned flags need evidence: solid evidence gives a flag, some evidence
        # gives a "hunch". Stated preferences always count.
        scored = []
        for f, _, stated in pred.contributions:
            e = abs(ev.get(f, 0.0))
            learned = rel.get(f, 0.0) if e >= FLAG_HUNCH_EVIDENCE else 0.0
            scored.append((f, learned, stated, e < FLAG_MIN_EVIDENCE))
        scored.sort(key=lambda c: c[1] + c[2], reverse=True)
        for f, learned, stated, unsure in scored:
            total = learned + stated
            if abs(total) < FLAG_MIN:
                continue
            from_stated = abs(stated) > abs(learned)
            hunch = unsure and not from_stated
            text = (self.stated.reasons[f] if from_stated and f in self.stated.reasons
                    else _describe(f, item, total > 0, from_stated, hunch))
            if hunch:
                (hunch_green if total > 0 else hunch_red).append(text)
            else:
                (green if total > 0 else red).append(text)

        if (pred.knn > 0.3 and pred.nearest_liked and pred.nearest_liked != item.id
                and pool and pred.nearest_liked in pool.by_id):
            green.insert(0, f"Similar to the {_short(pool.by_id[pred.nearest_liked].title)} you liked")
        if pred.knn < -0.3:
            red.insert(0, "Similar to pieces you passed on")
        if pred.similar_liked >= 2:
            red.insert(0, f"You've already liked {pred.similar_liked} very similar pieces")
        if item.n_stores > 1:
            green.append(f"Lowest price of {item.n_stores} listings")
        green += _social_proof(item)
        if item.rating and item.reviews and item.reviews >= LOW_RATING_MIN_REVIEWS and item.rating < LOW_RATING:
            red.append(f"Rated {item.rating:.1f} by {_count(item.reviews)} buyers. They aren't thrilled")
        title = item.title.lower()
        if "dry clean" in title:
            red.append("Dry clean only")
        if "sheer" in title:
            red.append("Sheer fabric")
        green += hunch_green
        red += hunch_red

        # Always show a real con if one exists, even a small one: all-green reads like an ad.
        if not red and scored and scored[-1][1] + scored[-1][2] < 0:
            f, learned, stated, unsure = scored[-1]
            from_stated = abs(stated) > abs(learned)
            red.append(_describe(f, item, False, from_stated, unsure and not from_stated))
        return green[:3], red[:3]

    def your_type(self) -> dict:
        """The Style DNA: only the likes and dislikes Cupid has solid evidence for."""
        ranked = sorted(self.explainable().items(), key=lambda kv: kv[1], reverse=True)
        loves = [f for f, e in ranked if e >= TYPE_MIN_EVIDENCE][:TYPE_MAX]
        if len(loves) < 2:   # never leave the reveal empty-handed; flag-level evidence is ~77% right
            loves = [f for f, e in ranked if e >= FLAG_MIN_EVIDENCE][:2]
        avoids = [f for f, e in reversed(ranked) if e <= -TYPE_MIN_EVIDENCE][:TYPE_MAX]

        def group(fs):
            out: dict[str, list[str]] = {}
            for f in fs:
                key, value = f.split(":", 1)
                out.setdefault(key, []).append(value)
            return out

        summary = ", ".join(_LABELS.get(f.split(":", 1)[0], lambda v: v)(f.split(":", 1)[1]).lower() for f in loves)
        return {"loves": group(loves), "avoids": group(avoids), "summary": summary}

    def favourite(self, key: str) -> str | None:
        """The value of an attribute Cupid has real, uncontradicted evidence you like."""
        best = max(((f, e) for f, e in self.explainable().items() if f.startswith(key + ":")),
                   key=lambda fe: fe[1], default=None)
        return best[0].split(":", 1)[1] if best and best[1] >= FLAG_HUNCH_EVIDENCE else None

    def write_query(self, category: str | None = None) -> str:
        """Cupid's own search, built from what it has learned.

        Anchored on the liked item that best matches what Cupid has evidence
        for, keeping only that item's attributes with real evidence behind them,
        so the words describe one real look instead of a mash-up of flukes.
        """
        cat_feature = f"category:{category}" if category else None
        liked = [feats for feats, y in zip(self.mem_feats, self.mem_y)
                 if y > 0 and (cat_feature is None or cat_feature in feats)]
        if not liked:
            return f"women {category or 'outfit'}" + (f" under {int(self.stated.budget)}" if self.stated.budget else "")
        ev = self.explainable()
        anchor = dict(f.split(":", 1) for f in max(liked, key=lambda fs: sum(ev.get(f, 0.0) for f in fs)))

        def keep(key):
            value = anchor.get(key)
            return value if value and ev.get(f"{key}:{value}", 0.0) >= FLAG_HUNCH_EVIDENCE else None

        pattern = keep("pattern")
        parts = ["women", keep("colour"), keep("fabric"), keep("fit"),
                 pattern if pattern != "solid" else None, category or anchor.get("category")]
        query = " ".join(p for p in parts if p)
        if self.stated.budget:
            query += f" under {int(self.stated.budget)}"
        return query


def compatibility(a: Cupid, b: Cupid) -> int:
    """0-100 style match between two people, from their learned scores and liked looks."""
    keys = sorted(set(a.w) | set(b.w))
    if not keys:
        return 50
    va = np.tanh(np.array([a.w.get(k, 0.0) for k in keys]))
    vb = np.tanh(np.array([b.w.get(k, 0.0) for k in keys]))
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    taste = float(va @ vb / denom) if denom else 0.0

    def liked_centroid(c: Cupid):
        liked = [e for e, y in zip(c.mem_embs, c.mem_y) if y > 0]
        if not liked:
            return None
        m = np.mean(liked, axis=0)
        return m / np.linalg.norm(m)

    ca, cb = liked_centroid(a), liked_centroid(b)
    looks = float(ca @ cb) if ca is not None and cb is not None else taste
    score = 0.6 * taste + 0.4 * looks          # both in -1..1
    return int(round(50 + 50 * max(-1.0, min(1.0, score))))


_LABELS = {
    "colour": lambda v: v.capitalize(),
    "tone": lambda v: f"{v.capitalize()} tones",
    "pattern": lambda v: "Solid colours" if v == "solid" else f"{v.capitalize()} prints",
    "fabric": lambda v: v.capitalize(),
    "fit": lambda v: f"{v.capitalize()} fit",
    "category": lambda v: v.capitalize() if v.endswith("s") else f"{v.capitalize()}s",
    "group": lambda v: f"{v.capitalize()} wear",
    "sleeve": lambda v: v.capitalize(),
    "neck": lambda v: v.capitalize() if "neck" in v else f"{v.capitalize()} neck",
    "length": lambda v: f"{v.capitalize()} length" if v in ("mini", "midi", "maxi") else v.capitalize(),
    "silhouette": lambda v: v.capitalize(),
    "vibe": lambda v: f"{v.capitalize()} vibe",
    "price": lambda v: "Under $25" if v == "under 25" else "$150+" if v == "150+" else f"${v}",
}


def _describe(f: str, item: Item, positive: bool, from_stated: bool, hunch: bool = False) -> str:
    key, value = f.split(":", 1)
    if key == "price":
        price = f"${item.price:,.0f}" if item.price else value
        if hunch:
            return f"{price} may suit your budget" if positive else f"{price} may be above your range"
        return f"{price} is in your usual range" if positive else f"{price} is above what you usually pick"
    label = _LABELS.get(key, lambda v: v)(value).lower()
    if hunch:
        return f"Early sign you like {label}" if positive else f"Early sign you pass on {label}"
    if from_stated:
        return f"Matches your pick: {label}" if positive else f"You asked to avoid {label}"
    return f"You keep liking {label}" if positive else f"You usually pass on {label}"


def _count(n: int) -> str:
    return f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else str(n)


def _social_proof(item: Item) -> list[str]:
    """Green flags from what other buyers did: facts about the item, not your taste."""
    out = []
    if item.rating and item.reviews and item.reviews >= GOOD_RATING_MIN_REVIEWS and item.rating >= GOOD_RATING:
        out.append(f"Rated {item.rating:.1f} from {_count(item.reviews)} reviews")
    if item.bought:
        out.append(item.bought)
    if item.price and item.old_price and item.old_price > item.price and 1 - item.price / item.old_price >= BIG_DISCOUNT:
        out.append(f"{round(100 * (1 - item.price / item.old_price))}% off (was ${item.old_price:,.0f})")
    return out


def _short(title: str, words: int = 4) -> str:
    return " ".join(title.split()[:words]).lower()
