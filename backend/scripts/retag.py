"""Re-tag the whole catalogue after changing the vocabulary in cupid/tagging.py.

Uses saved titles and fingerprints only: no SerpAPI calls, no image downloads.
Also saves the model's reading of each vibe, so the API can rank dresses by vibe
without loading the model.

    uv run python scripts/retag.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from cupid import catalogue, db  # noqa: E402
from cupid.config import VIBE_VECTORS  # noqa: E402
from cupid.tagging import VIBE_PROMPTS, VIBES  # noqa: E402
from cupid.vision import FashionEncoder  # noqa: E402

if __name__ == "__main__":
    conn = db.connect()
    encoder = FashionEncoder()
    np.savez(VIBE_VECTORS, vibes=np.array(VIBES), vectors=encoder.encode_texts([VIBE_PROMPTS[v] for v in VIBES]))
    changed = catalogue.retag(conn, encoder)
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"Re-tagged {total} items; {changed} changed.")
