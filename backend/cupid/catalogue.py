"""Turn Amazon searches into tagged, fingerprinted, de-duplicated items."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
import numpy as np
from PIL import Image

from . import amazon, db
from .amazon import AmazonSearch, SerpError
from .config import IMAGE_DIR, SERPAPI_DAILY_LIMIT
from .tagging import derive_tags, tags_from_title

# Fingerprints this close are the same product listed twice.
DUPLICATE_SIM = 0.97
# Below this confidence a zero-shot tag is a guess, so it's dropped.
MIN_TAG_CONF = {"colour": 0.30, "pattern": 0.35, "category": 0.30, "vibe": 0.20}
BATCH = 32
IMAGE_MAX = (720, 960)


class BudgetError(SerpError):
    pass


@dataclass
class IngestReport:
    searches_run: int = 0
    searches_cached: int = 0
    offers_seen: int = 0
    already_known: int = 0
    image_failures: int = 0
    duplicates: int = 0
    added: int = 0
    item_ids: list[str] = field(default_factory=list)   # every item these searches returned, in order


def _fetch_image(url: str, client: httpx.Client) -> Image.Image | None:
    try:
        resp = client.get(url)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _merge_tags(filter_tags: dict, title_tags: dict, vision_tags: dict) -> tuple[dict, dict]:
    """Amazon's filters are certain, title keywords next, and vision fills the gaps."""
    tags = {**title_tags, **filter_tags}
    conf = {k: 1.0 for k in tags}
    for key, (value, p) in vision_tags.items():
        if key not in tags and p >= MIN_TAG_CONF[key]:
            tags[key], conf[key] = value, round(p, 3)
    return tags, conf


def retag(conn, encoder) -> int:
    """Re-tag every item from its saved filters, title and fingerprint, after a vocabulary change.

    Needs no SerpAPI calls or image downloads. Returns how many items changed.
    """
    rows = conn.execute("SELECT id, title, price, tags, filter_tags, embedding FROM items").fetchall()
    if not rows:
        return 0
    embs = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    changed = 0
    for r, vtags in zip(rows, encoder.zero_shot(embs)):
        tags, conf = _merge_tags(json.loads(r["filter_tags"]), tags_from_title(r["title"]), vtags)
        tags = derive_tags(tags, r["price"])
        if tags != json.loads(r["tags"]):
            changed += 1
        conn.execute("UPDATE items SET tags = ?, tag_conf = ? WHERE id = ?", (json.dumps(tags), json.dumps(conf), r["id"]))
    conn.commit()
    return changed


def search(conn, s: AmazonSearch, refresh: bool = False) -> tuple[list[dict], dict, bool]:
    """Offers for a search, from the cache unless refresh is set. Returns (offers, raw response, was_cached)."""
    raw = None if refresh else db.get_search(conn, s.key())
    cached = raw is not None
    if raw is None:
        used = db.calls_last_24h(conn)
        if used >= SERPAPI_DAILY_LIMIT:
            raise BudgetError(f"Daily SerpAPI budget reached ({used}/{SERPAPI_DAILY_LIMIT}); skipped {s.label or s.k!r}")
        db.record_call(conn, s.key())   # counted before the call, so failed calls count too
        raw = amazon.run(s)
        db.save_search(conn, s.key(), raw, len(raw.get("organic_results") or []))
    return amazon.parse_results(raw), raw, cached


def ingest(conn, searches: list[AmazonSearch], encoder, refresh: bool = False, log=print) -> IngestReport:
    report = IngestReport()
    pending: dict[str, dict] = {}
    returned: list[str] = []
    for s in searches:
        try:
            offers, _, cached = search(conn, s, refresh)
        except BudgetError as e:
            log(f"  ! {e}. Stopping; the rest stay unsearched.")
            break
        except SerpError as e:
            log(f"  ! {e}")
            continue
        report.searches_cached += cached
        report.searches_run += not cached
        report.offers_seen += len(offers)
        found = dict(s.tags)
        for o in offers:
            returned.append(o["id"])
            if o["id"] in pending:
                pending[o["id"]]["filter_tags"].update(found)
                continue
            if db.item_exists(conn, o["id"]):
                report.already_known += 1
                db.add_filter_tags(conn, o["id"], found)
                continue
            o["source_query"] = s.key()
            o["filter_tags"] = found
            pending[o["id"]] = o
        conn.commit()
        log(f"  {'cached' if cached else 'fetched'}: {s.label or s.k} → {len(offers)} items")

    offers = list(pending.values())
    if offers:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=20, follow_redirects=True) as client, ThreadPoolExecutor(8) as pool:
            images = list(pool.map(lambda o: _fetch_image(o["thumbnail_url"], client), offers))
        _add(conn, offers, images, encoder, report, log)

    report.item_ids = db.resolve_ids(conn, list(dict.fromkeys(returned)))
    return report


def _add(conn, offers: list[dict], images: list, encoder, report: IngestReport, log):
    known_ids, known = db.all_embeddings(conn)
    for start in range(0, len(offers), BATCH):
        chunk = [(o, img) for o, img in zip(offers[start:start + BATCH], images[start:start + BATCH]) if img]
        report.image_failures += min(BATCH, len(offers) - start) - len(chunk)
        if not chunk:
            continue
        embs = encoder.encode_images([img for _, img in chunk])
        vision = encoder.zero_shot(embs)
        sims_known = embs @ known.T if len(known_ids) else None
        added_ids, added_embs = [], []

        for i, ((offer, img), emb, vtags) in enumerate(zip(chunk, embs, vision)):
            best_id, best = None, -1.0
            if sims_known is not None:
                j = int(sims_known[i].argmax())
                best_id, best = known_ids[j], sims_known[i, j]
            if added_embs:
                s = np.stack(added_embs) @ emb
                k = int(s.argmax())
                if s[k] > best:
                    best_id, best = added_ids[k], s[k]
            if best >= DUPLICATE_SIM:
                db.record_duplicate(conn, best_id, offer)
                report.duplicates += 1
                continue

            tags, conf = _merge_tags(offer["filter_tags"], tags_from_title(offer["title"]), vtags)
            offer["tags"] = derive_tags(tags, offer["price"])
            offer["tag_conf"] = conf
            path = IMAGE_DIR / f"{offer['id']}.jpg"
            img.thumbnail(IMAGE_MAX)
            img.save(path, "JPEG", quality=86)
            offer["image_path"] = path.name
            db.insert_item(conn, offer, emb)
            added_ids.append(offer["id"])
            added_embs.append(emb)
            report.added += 1
        conn.commit()
        if added_ids:
            known_ids += added_ids
            known = np.vstack([known, np.stack(added_embs)]) if len(known) else np.stack(added_embs)
        log(f"  processed {min(start + BATCH, len(offers))}/{len(offers)}")
