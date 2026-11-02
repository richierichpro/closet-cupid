# Closet Cupid 💘

**You might not find your perfect date, but with Closet Cupid you can find your perfect dress.**

Closet Cupid is a dating-app-style way to shop for dresses. You swipe right on dresses you like and left on the rest. A self-learning AI stylist, Cupid, learns your taste from every swipe. It tries dresses on *you* with YouCam's virtual try-on, and it keeps getting sharper until it finds the one.

Built for the **YouCam API Skin AI & eCommerce VTO Hackathon** (Perfect Corp).

---

## The demo, step by step

**1. Tell Cupid about yourself.** Pick the occasion (wedding guest, date night, work…) and a couple of vibes (romantic, minimal, boho, edgy…), and add a selfie.
- **YouCam Skin Tone Analysis** reads your undertone from the photo.
- Cupid uses it to judge which colours suit you.

**2. Swipe.**
- ← pass, → like, ↑ **super like** (Cupid tries it on you).
- The first cards are drawn from the vibes you picked, chosen by a fashion vision model (Marqo-FashionSigLIP).
- Every card has a short label saying why Cupid is showing it: *Best bet*, *Testing long sleeves*, *Something new*.

**3. Super like = try it on.** **YouCam Clothes Virtual Try-On** renders you wearing the dress. Cupid (Claude) looks at the try-on and gives green and red flags about how it looks on you. Then you decide: *Love it on me* or *Not on me*.

**4. "Like the one you loved."** Like a dress and the next card is its closest look-alike, matched by image similarity.
- Like that one too, and Cupid leans in.
- Pass on it, and Cupid backs off.

**5. Cupid learns, live.** After every swipe, Claude rewrites its profile of you: what you like, what you avoid, and how sure it is. Then it:
- **chooses your next cards** from a shortlist, labelling each one with why it was picked
- **runs experiments** on your taste ("Is it the fitted cut, not the sleeves, that you pass on?") and confirms or rejects them from your swipes
- **goes shopping for you**, writing its own product search from real store filters to find dresses that weren't in your deck

**6. End of each round (12 swipes):**
- **Here's what I learned:** Cupid's one-line read on your taste.
- **This or that:** two real dresses that look alike except for the one thing Cupid can't work out (sleeveless vs long sleeve, fit-and-flare vs bodycon). One tap teaches it more than ten swipes.
- **Cupid went on dates for you:**
  - It picks 4 dresses you haven't seen and tries each one on your photo with **YouCam Try-On**, in parallel.
  - Claude judges each try-on: ✓ *Works on you* or ✕ *Not on you*, with the reason.
  - The dresses that pass open your next round, shown on you.

**7. Matches.**
- **Liked:** everything you swiped right on.
- **Tried on you:** every try-on, both your super likes and Cupid's dates, with its verdict.

**8. The board** (`/board`), a live analytics screen for a laptop or projector:
- **Shopper tab:**
  - how Cupid learned you: its turning points, its experiments, the searches it ran and why
  - how accurate it was from the first round to the last, measured against a random control group
- **Brand tab:** insights only possible with try-on and skin AI:
  - dresses shoppers love on the model but reject on themselves
  - colour preference by skin undertone
  - why shoppers pass

---

## How YouCam is used

| YouCam API | Where | What it does in the app |
|---|---|---|
| **Skin Tone Analysis** | Onboarding selfie | Undertone and contrast, which feed Cupid's colour judgement and the brand board's undertone insights |
| **Clothes Virtual Try-On** (`cloth-v4`) | Super like, and Cupid's dates | Renders the shopper wearing the dress. Claude then judges the try-on image itself, not just the product photo |

Try-ons are the core loop, not a gimmick. A super like is confirmed or rejected *on you*. Cupid's dates use try-ons to filter what it recommends. Each verdict is fed back into what Cupid learns.

## How the self-learning works

Each dress gets a match score from four layers:

1. **Attribute learning:** an online logistic model over style attributes (colour, silhouette, neckline, sleeve, length, pattern, fabric, vibe, price). It updates on every swipe, with recent swipes counting more.
2. **Look-alike memory:** the dresses you liked and passed on, compared by Marqo-FashionSigLIP image embeddings (k-nearest neighbours).
3. **Claude's beliefs:** the LLM's written profile of you, rewritten after every swipe, turned into attribute weights.
4. **What you told it:** your onboarding vibes, plus your this-or-that answers, which don't fade.

**Choosing cards:**
- Most cards are chosen by Claude from the engine's shortlist: best bets, tests for its open experiments, and surprises.
- About 15% are **random control cards**, so Cupid's like rate can be measured honestly against chance.

**Testing:**
- `scripts/simulate.py` runs simulated shoppers with known taste and scores Cupid on dresses it never dealt.
- `pytest` covers the engine, search and budgets.

## Tech

- **Backend:** Python 3.12, FastAPI, SQLite, NumPy
- **Frontend:** React 19, TypeScript, Vite, framer-motion; glassmorphism UI
- **AI:**
  - Claude (`claude-haiku-5-5`) for the stylist agent, with structured outputs
  - Marqo-FashionSigLIP (Hugging Face, open_clip) for image embeddings and zero-shot style tags
  - YouCam Skin Tone Analysis and Clothes Try-On
- **Products:** live search through SerpAPI (US store), with every result cached and a hard daily cap on API calls

**Cost:** Claude is about $0.001 per swipe, so roughly 3–4 cents for a whole shopping session.

## Run it

```bash
# API
cd backend
uv sync --extra vision
cp .env.example .env     # add SERPAPI_KEY, ANTHROPIC_API_KEY, YOUCAM_API_KEY
uv run uvicorn cupid.api:app --port 8000

# App (second terminal)
cd frontend
npm install
npm run dev
```

- **Phone app:** http://localhost:5173. From a phone on the same Wi-Fi, use the Network address Vite prints.
- **Board:** http://localhost:5173/board
- **Keyboard:** ← pass, → like, ↑ super like, ↓ love it but too pricey, Backspace undo.

The product catalogue, photos and try-on images live in `backend/data/` and aren't in the repo. Searches fill the catalogue as shoppers use the app. After building it, run `uv run python scripts/retag.py` to tag the catalogue's vibes.

See [backend/README.md](backend/README.md) for the pipeline and code map.
