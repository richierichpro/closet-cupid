import json
import sqlite3
import time

import numpy as np

from .config import DATA_DIR, DB_PATH
from .item import Item
from .tagging import derive_tags

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    query       TEXT PRIMARY KEY,
    fetched_at  REAL NOT NULL,
    n_results   INTEGER NOT NULL,
    raw         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    price         REAL,
    price_text    TEXT,
    old_price     REAL,
    brand         TEXT,
    rating        REAL,
    reviews       INTEGER,
    bought        TEXT,
    store         TEXT,
    link          TEXT,
    thumbnail_url TEXT,
    image_path    TEXT,
    tags          TEXT NOT NULL,
    tag_conf      TEXT NOT NULL,
    filter_tags   TEXT NOT NULL DEFAULT '{}',  -- attributes guaranteed by the Amazon filters that found it
    source_query  TEXT,
    n_stores      INTEGER NOT NULL DEFAULT 1,
    embedding     BLOB NOT NULL,
    created_at    REAL NOT NULL
);
-- Every real SerpAPI call, for the daily budget.
CREATE TABLE IF NOT EXISTS api_calls (
    ts     REAL NOT NULL,
    query  TEXT NOT NULL
);
-- Every swipe from every session: feeds the brand view of the analytics board.
CREATE TABLE IF NOT EXISTS swipes (
    session   TEXT NOT NULL,
    item_id   TEXT NOT NULL,
    action    TEXT NOT NULL,
    dwell_ms  INTEGER NOT NULL,
    p_before  REAL NOT NULL,
    slot      TEXT NOT NULL,
    ts        REAL NOT NULL
);
-- One row per shopper: what YouCam read from their photo and what Cupid's LLM concluded
-- about them. Pooled in the brand view, never shown individually.
CREATE TABLE IF NOT EXISTS shoppers (
    session    TEXT PRIMARY KEY,
    occasion   TEXT,
    undertone  TEXT,
    has_photo  INTEGER NOT NULL DEFAULT 0,
    profile    TEXT,
    updated    REAL NOT NULL
);
-- Listings merged into an existing item (same product, another seller).
CREATE TABLE IF NOT EXISTS aliases (
    id       TEXT PRIMARY KEY,
    item_id  TEXT NOT NULL REFERENCES items(id)
);
"""


def connect(path=DB_PATH) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # The API shares one connection across request threads, guarded by its own lock.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_search(conn, query: str) -> dict | None:
    row = conn.execute("SELECT raw FROM searches WHERE query = ?", (query,)).fetchone()
    return json.loads(row["raw"]) if row else None


def save_search(conn, query: str, raw: dict, n_results: int):
    conn.execute(
        "INSERT OR REPLACE INTO searches (query, fetched_at, n_results, raw) VALUES (?, ?, ?, ?)",
        (query, time.time(), n_results, json.dumps(raw)),
    )
    conn.commit()


def calls_last_24h(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM api_calls WHERE ts > ?", (time.time() - 86400,)).fetchone()[0]


def record_call(conn, query: str):
    conn.execute("INSERT INTO api_calls (ts, query) VALUES (?, ?)", (time.time(), query))
    conn.commit()


def record_swipe(conn, session: str, s):
    conn.execute(
        "INSERT INTO swipes (session, item_id, action, dwell_ms, p_before, slot, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session, s.item_id, s.action, s.dwell_ms, s.p_before, s.slot, time.time()),
    )
    conn.commit()


def delete_last_swipe(conn, session: str):
    conn.execute("DELETE FROM swipes WHERE rowid = (SELECT MAX(rowid) FROM swipes WHERE session = ?)", (session,))
    conn.commit()


def all_swipes(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM swipes").fetchall()


def save_shopper(conn, session: str, occasion: str, undertone: str | None, has_photo: bool):
    conn.execute(
        "INSERT OR REPLACE INTO shoppers (session, occasion, undertone, has_photo, updated) VALUES (?, ?, ?, ?, ?)",
        (session, occasion, undertone, int(has_photo), time.time()),
    )
    conn.commit()


def save_profile(conn, session: str, profile: dict):
    conn.execute("UPDATE shoppers SET profile = ?, updated = ? WHERE session = ?", (json.dumps(profile), time.time(), session))
    conn.commit()


def all_shoppers(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM shoppers").fetchall()


def item_exists(conn, item_id: str) -> bool:
    """True if this offer is already an item, or was merged into one."""
    return conn.execute(
        "SELECT 1 FROM items WHERE id = ? UNION SELECT 1 FROM aliases WHERE id = ?", (item_id, item_id)
    ).fetchone() is not None


def insert_item(conn, row: dict, emb: np.ndarray):
    conn.execute(
        """INSERT INTO items (id, title, price, price_text, old_price, brand, rating, reviews, bought, store, link,
                              thumbnail_url, image_path, tags, tag_conf, filter_tags, source_query, n_stores,
                              embedding, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (row["id"], row["title"], row["price"], row["price_text"], row.get("old_price"), row.get("brand"),
         row.get("rating"), row.get("reviews"), row.get("bought"), row["store"], row["link"],
         row["thumbnail_url"], row["image_path"], json.dumps(row["tags"]), json.dumps(row["tag_conf"]),
         json.dumps(row.get("filter_tags", {})), row["source_query"], emb.astype(np.float32).tobytes(), time.time()),
    )


def add_filter_tags(conn, item_id: str, found: dict[str, str]):
    """An item turned up again under more Amazon filters: those attributes are now certain."""
    row = conn.execute("SELECT tags, tag_conf, filter_tags, price FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row or not found:
        return
    filt = {**json.loads(row["filter_tags"]), **found}
    tags = derive_tags({**json.loads(row["tags"]), **filt}, row["price"])
    conf = {**json.loads(row["tag_conf"]), **{k: 1.0 for k in filt}}
    conn.execute("UPDATE items SET tags = ?, tag_conf = ?, filter_tags = ? WHERE id = ?",
                 (json.dumps(tags), json.dumps(conf), json.dumps(filt), item_id))


def record_duplicate(conn, keeper_id: str, dup: dict):
    """Count another listing of the same item, and keep the cheaper one."""
    conn.execute("INSERT OR IGNORE INTO aliases (id, item_id) VALUES (?, ?)", (dup["id"], keeper_id))
    keeper = conn.execute("SELECT price FROM items WHERE id = ?", (keeper_id,)).fetchone()
    if dup["price"] is not None and (keeper["price"] is None or dup["price"] < keeper["price"]):
        conn.execute(
            "UPDATE items SET price = ?, price_text = ?, old_price = ?, store = ?, link = ?, n_stores = n_stores + 1 "
            "WHERE id = ?",
            (dup["price"], dup["price_text"], dup.get("old_price"), dup["store"], dup["link"], keeper_id),
        )
    else:
        conn.execute("UPDATE items SET n_stores = n_stores + 1 WHERE id = ?", (keeper_id,))


def all_embeddings(conn) -> tuple[list[str], np.ndarray]:
    rows = conn.execute("SELECT id, embedding FROM items").fetchall()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)
    return [r["id"] for r in rows], np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])


def resolve_ids(conn, offer_ids: list[str]) -> list[str]:
    """Item ids for a list of offer ids, following merges into other items."""
    out = []
    for oid in offer_ids:
        row = conn.execute(
            "SELECT id FROM items WHERE id = ? UNION SELECT item_id FROM aliases WHERE id = ?", (oid, oid)
        ).fetchone()
        if row and row[0] not in out:
            out.append(row[0])
    return out


def load_items(conn, ids: list[str] | None = None) -> list[Item]:
    if ids is None:
        rows = conn.execute("SELECT * FROM items").fetchall()
    else:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT * FROM items WHERE id IN ({marks})", ids).fetchall() if ids else []
    return [
        Item(
            id=r["id"], title=r["title"], price=r["price"], tags=json.loads(r["tags"]),
            emb=np.frombuffer(r["embedding"], dtype=np.float32).copy(),
            store=r["store"] or "", link=r["link"] or "", image=r["image_path"] or "", n_stores=r["n_stores"],
            brand=r["brand"] or "", old_price=r["old_price"], rating=r["rating"], reviews=r["reviews"],
            bought=r["bought"],
        )
        for r in rows
    ]
