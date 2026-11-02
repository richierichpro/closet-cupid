# Closet Cupid backend

The catalogue pipeline and Cupid's self-learning style engine.

## Setup

```bash
cd backend
uv sync --extra vision          # Python 3.12 + deps (torch, open_clip for the vision model)
cp .env.example .env            # then add your SerpAPI, Claude and YouCam keys
```

The first run downloads Marqo-FashionSigLIP (~4 minutes); after that it loads in seconds.

## The catalogue

There's no upfront catalogue. Amazon (SerpAPI Amazon Search on amazon.com) is
searched for what each shopper says they're looking for, and every search is
cached in `data/cupid.db`, so the same answer never costs twice. Photos are
saved to `data/images/`.

```bash
uv run python scripts/prefetch.py                 # which answers are cached
uv run python scripts/prefetch.py dresses         # cache some before a demo (asks first)
uv run python scripts/retag.py                    # re-tag vibes with the fashion model
```

For every product the pipeline: downloads the 900px photo → makes its
fingerprint (embedding) → tags it (Amazon's filters first, then title
keywords, then the vision model) → merges duplicate listings → saves it.

**SerpAPI budget:** every real call is logged, and none are made past
`SERPAPI_DAILY_LIMIT` (default 100 per 24 hours, set in `.env`).

The previous Google Shopping catalogue is kept in `data/google_shopping_backup/`.

## Check that Cupid learns

```bash
uv run python scripts/simulate.py           # fake users on a synthetic catalogue
uv run python scripts/simulate.py --real    # fake users on the real catalogue
uv run pytest -q
```

The simulator scores Cupid on items it never dealt, against each fake user's
known taste, so the numbers can't be inflated by Cupid picking easy cards.

## Run the API

```bash
uv run uvicorn cupid.api:app --port 8000
```

The frontend (`../frontend`, `npm run dev`) proxies `/api` and `/images` here.

## Code map

| File | What it does |
|---|---|
| `cupid/amazon.py` | SerpAPI Amazon Search (amazon.com): searches, parsing, Amazon filters ↔ Cupid's attributes |
| `cupid/tagging.py` | Attribute vocabulary and title keyword tagging |
| `cupid/vision.py` | Fingerprints and zero-shot tags from the vision model |
| `cupid/catalogue.py` | Search → photos → fingerprints → tags → de-duplicate → save |
| `cupid/engine.py` | Match %, learning from swipes, card choice, flags, Your type, Cupid's own searches, compatibility |
| `cupid/metrics.py` | Cupid's report card: accuracy by round, Cupid vs random cards, calibration |
| `cupid/simulate.py` | Fake users with known taste (testing only; never used by the app) |
| `cupid/agent.py` | Cupid's LLM mind (Claude): learns a profile after each swipe, plans the next cards and experiments, writes its own searches, judges try-ons, asks this-or-that questions |
| `cupid/youcam.py` | YouCam APIs: Skin Tone Analysis and Clothes Virtual Try-On (cloth-v4) |
| `cupid/api.py` | Sessions, swipes, look-alikes, Cupid's dates, round payoffs, matches, live board and brand analytics |
