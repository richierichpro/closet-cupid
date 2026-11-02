import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
YOUCAM_API_KEY = os.getenv("YOUCAM_API_KEY", "")
# Hard cap on real SerpAPI calls in any 24 hours. Cached searches are free and don't count.
SERPAPI_DAILY_LIMIT = int(os.getenv("SERPAPI_DAILY_LIMIT", "100"))

DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("CUPID_DB", DATA_DIR / "cupid.db"))
IMAGE_DIR = DATA_DIR / "images"
# The fashion model's reading of each vibe, saved by scripts/retag.py.
VIBE_VECTORS = Path(os.getenv("CUPID_VIBES", DATA_DIR / "vibes.npz"))

# Fashion-specific CLIP-style model: one model gives both the fingerprint
# (embedding) and zero-shot tags.
MODEL_NAME = "hf-hub:Marqo/marqo-fashionSigLIP"
