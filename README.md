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
- **This or that:** two real dresses that look alike except for the one thing Cupid can't work out (sleeveless vs long sleeve, fit-and-flare vs bodycon). One tap teaches it more than ten swipes. Tap **Neither** if both are wrong.

**7. Matches.**
- **Liked:** everything you swiped right on.
- **Tried on you:** every dress you tried on, with Cupid's verdict on how it looks on you.

**8. Insights** (tap **Insights** in the app, or open `/board`):
- **How Cupid's mind changed:** a heatmap of what Cupid believed after every swipe. You can watch beliefs appear, flip and firm up, with your this-or-that answers marked.
- **How Cupid learned you:** the swipes that changed its mind, its experiments, and the searches it ran and why.
- **Does it learn?** Its accuracy from the first round to the last, measured against a random control group.
- Each shopper gets their own insights link, saved so it still works later.

---

## How YouCam is used

| YouCam API | Where | What it does in the app |
|---|---|---|
| **Skin Tone Analysis** | Onboarding selfie | Undertone and contrast, which feed Cupid's colour judgement |
| **Clothes Virtual Try-On** (`cloth-v4`) | Super like | Renders the shopper wearing the dress. Claude then judges the try-on image itself, not just the product photo |

Try-ons are part of how Cupid learns, not a gimmick. A super like is confirmed or rejected *on you*, and that verdict teaches Cupid something a swipe can't: the style appealed, but it doesn't work on you.

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

The dress catalogue ships with the code in `backend/data/`: about 2,000 dresses with photos, tags and fashion-model fingerprints, so the app works straight after cloning. Shoppers' photos and try-on images are never committed. New searches add dresses to the catalogue as shoppers use the app.

See [backend/README.md](backend/README.md) for the pipeline and code map.
