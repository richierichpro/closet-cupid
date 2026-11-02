import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
YOUCAM_API_KEY = os.getenv("YOUCAM_API_KEY", "")
# Hard cap on real SerpAPI calls in any 24 hours. Cached searches are free and don't count.
SERPAPI_DAILY_LIMIT = int(os.getenv("SERPAPI_DAILY_LIMIT", "100"))

# On a server, data lives on a persistent disk (CUPID_DATA). The first boot seeds it with the
# catalogue that ships in the repo; after that the disk keeps every swipe, search and insight.
SHIPPED_DATA = ROOT / "data"
DATA_DIR = Path(os.getenv("CUPID_DATA", SHIPPED_DATA))
if DATA_DIR != SHIPPED_DATA and not (DATA_DIR / "cupid.db").exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SHIPPED_DATA / "images", DATA_DIR / "images", dirs_exist_ok=True)
    for name in ("vibes.npz", "cupid.db"):   # the database last: its presence means the seed finished
        shutil.copy2(SHIPPED_DATA / name, DATA_DIR / name)

# Spending limits for a public link: past these, the feature pauses for the day and the app carries on.
LLM_SESSIONS_PER_DAY = int(os.getenv("LLM_SESSIONS_PER_DAY", "50"))   # sessions with Cupid's Claude mind
TRYONS_PER_SESSION = int(os.getenv("TRYONS_PER_SESSION", "5"))         # YouCam Clothes Try-On
TRYONS_PER_DAY = int(os.getenv("TRYONS_PER_DAY", "40"))
PHOTOS_PER_DAY = int(os.getenv("PHOTOS_PER_DAY", "60"))                # YouCam Skin Tone Analysis

# The built app (npm run build), served by the API so one server is the whole site.
FRONTEND_DIST = Path(os.getenv("CUPID_FRONTEND", ROOT.parent / "frontend" / "dist"))
DB_PATH = Path(os.getenv("CUPID_DB", DATA_DIR / "cupid.db"))
IMAGE_DIR = DATA_DIR / "images"
# The fashion model's reading of each vibe, saved by scripts/retag.py.
VIBE_VECTORS = Path(os.getenv("CUPID_VIBES", DATA_DIR / "vibes.npz"))

# Fashion-specific CLIP-style model: one model gives both the fingerprint
# (embedding) and zero-shot tags.
MODEL_NAME = "hf-hub:Marqo/marqo-fashionSigLIP"
