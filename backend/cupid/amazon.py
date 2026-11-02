"""SerpAPI Amazon Search (US): what the shopper asked for, nothing else.

A shopper's answer to "what are you looking for?" becomes one search. Later,
Cupid narrows it with Amazon's own filters (colour, material, fit, pattern,
size), whose codes come from the filters section of that first response.
"""

import re
from dataclasses import dataclass

import httpx

from .config import SERPAPI_KEY
from .tagging import COLOURS, FABRICS, FITS, LENGTHS, NECKS, PATTERNS, SILHOUETTES, SLEEVES, _match

SEARCH_URL = "https://serpapi.com/search.json"
DOMAIN = "amazon.com"
NO_RESULTS = "hasn't returned any results"

# What Cupid shops for. The app is dresses-only: a dress is a single, full-body
# garment, which is what try-on renders best. "allows" is what may appear in the
# deck (Cupid's categories), whatever the search returns.
LOOKING_FOR = {
    "dresses": {"label": "Dresses", "hint": "Mini to maxi", "k": "women dress", "node": "dress",
                "allows": {"dress", "maxi dress"}},
}

# Cupid's category → the answers it belongs to, for typed searches ("black linen dress").
ANSWER_FOR_CATEGORY = {c: a for a, v in LOOKING_FOR.items() for c in v["allows"]}


# Amazon filter group → Cupid attribute, and the vocab used to read the value.
# Group names vary by category ("fit_type" for some, "fit" for others).
FILTER_GROUPS = {"colour": ("colour", COLOURS), "color": ("colour", COLOURS), "material": ("fabric", FABRICS),
                 "fit_type": ("fit", FITS), "fit": ("fit", FITS), "pattern": ("pattern", PATTERNS),
                 "sleeve_length_description": ("sleeve", SLEEVES), "neckline": ("neck", NECKS),
                 "neck_style": ("neck", NECKS), "item_length_description": ("length", LENGTHS),
                 "apparel_silhouette": ("silhouette", SILHOUETTES)}
# Every Cupid attribute that has an Amazon filter, i.e. what Cupid can shop with.
SHOPPABLE = list(dict.fromkeys(k for k, _ in FILTER_GROUPS.values()))
SIZE_GROUPS = ("women_s_size", "women_s_general_size")
COLOUR_GROUPS = ("colour", "color")

# The filters shoppers set themselves, in this order: (label, Amazon group names it appears under).
# Brand, rating, discount, delivery, seller and similar groups aren't about the clothes, so they're left out.
FILTER_MENU = [
    ("Size", SIZE_GROUPS),
    ("Colour", ("colour", "color")),
    ("Length", ("item_length_description",)),
    ("Sleeve", ("sleeve_length_description",)),
    ("Neckline", ("neckline", "neck_style")),
    ("Fit", ("fit_type", "fit")),
    ("Silhouette", ("apparel_silhouette",)),
    ("Material", ("material",)),
    ("Pattern", ("pattern",)),
    ("Occasion", ("lifestyle", "occasion")),
    ("Details", ("embellishment_feature",)),
]

# Amazon's colour filter matches any colour variant, but the photo shows one. These are the
# visible colours each choice accepts, so asking for Black never deals a pink photo.
COLOUR_FAMILIES = {
    "black": {"black"}, "white": {"white", "cream"}, "off-white": {"white", "cream"}, "beige": {"beige", "cream"},
    "browns": {"brown", "beige", "mustard"}, "greys": {"grey"}, "silver": {"grey"},
    "reds": {"red", "maroon"}, "maroon": {"maroon"}, "pinks": {"pink", "pastel"}, "oranges": {"orange"},
    "yellows": {"yellow", "mustard"}, "gold": {"yellow", "mustard"}, "greens": {"green", "olive", "teal"},
    "blues": {"blue", "navy", "teal"}, "navy": {"navy"}, "turquoise": {"teal"}, "purples": {"purple", "pastel"},
    "multicolour": {"multicolour"}, "multi-coloured": {"multicolour"},
}

_NOT_WOMENS = re.compile(r"\b(men|mens|men's|boys?|girls?|kids?|baby|infants?)\b")
# Never outfits, whatever was asked for: nightwear, lingerie, costumes and unstitched fabric.
_NOT_OUTFITS = re.compile(r"\b(night ?dress(es)?|night ?gowns?|night ?suits?|night ?wear|nighty|nighties|nightie|"
                          r"py?jamas?|pajamas?|sleep ?wear|sleep ?shirts?|lounge ?wear|lounge|lingerie|babydoll|"
                          r"chemise|robes?|dress materials?|unstitched|costumes?|cosplay)\b")


class SerpError(RuntimeError):
    pass


@dataclass(frozen=True)
class AmazonSearch:
    k: str
    rh: str = ""                                  # Amazon refinement codes, comma-joined
    tags: tuple[tuple[str, str], ...] = ()        # Cupid attributes those codes guarantee
    label: str = ""                               # how it reads on screen
    page: int = 1

    def key(self) -> str:
        return f"{DOMAIN}|{self.k}|{self.rh}|{self.page}"


# "What's it for?" goes into the search itself: a date-night dress isn't a college dress.
OCCASION_WORDS = {
    "date": "date night",
    "wedding": "wedding guest",
    "work": "work",
    "party": "cocktail party",
    "everyday": "casual",
}


def with_occasion(k: str, occasion: str) -> str:
    """"women dress" + wedding → "women wedding guest dress"."""
    words = OCCASION_WORDS.get(occasion, "")
    if not words:
        return k
    rest = k[len("women "):] if k.lower().startswith("women ") else k
    return f"women {words} {rest}"


def answer_search(answer: str, occasion: str, label: str | None = None) -> AmazonSearch:
    return AmazonSearch(k=with_occasion(LOOKING_FOR[answer]["k"], occasion), label=label or LOOKING_FOR[answer]["label"])


def run(search: AmazonSearch, client: httpx.Client | None = None) -> dict:
    if not SERPAPI_KEY:
        raise SerpError("SERPAPI_KEY is not set. Add it to backend/.env.")
    params = {"engine": "amazon", "k": search.k, "amazon_domain": DOMAIN, "api_key": SERPAPI_KEY}
    if search.rh:
        params["rh"] = search.rh
    if search.page > 1:
        params["page"] = search.page
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.get(SEARCH_URL, params=params)
    except httpx.HTTPError as e:
        # httpx errors include the request URL, which contains the key.
        raise SerpError(f"Request for {search.k!r} failed: {type(e).__name__}") from None
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    error = data.get("error")
    if error and NO_RESULTS in error:
        return {"organic_results": [], "filters": {}}
    if error or resp.status_code != 200:
        raise SerpError(f"SerpAPI error for {search.k!r} (HTTP {resp.status_code}): {error or 'no details'}")
    return data


def _big_image(url: str) -> str:
    """Amazon serves any size from the same URL: ask for 900px instead of the 320px thumbnail."""
    return re.sub(r"\._AC_[A-Z]{2}\d+_\.", "._AC_UL900_.", url)


def parse_results(data: dict) -> list[dict]:
    offers = []
    for r in data.get("organic_results") or []:
        title = (r.get("title") or "").strip()
        if not title or not r.get("thumbnail") or not r.get("asin") or r.get("sponsored"):
            continue
        t = title.lower()
        if (_NOT_WOMENS.search(t) and "women" not in t) or _NOT_OUTFITS.search(t):
            continue
        bought = r.get("bought_last_month")
        offers.append({
            "id": r["asin"],
            "title": title,
            "price": r.get("extracted_price"),
            "price_text": r.get("price"),
            "old_price": r.get("extracted_old_price"),
            "brand": r.get("brand") or "",
            "rating": r.get("rating"),
            "reviews": r.get("reviews"),
            "bought": bought.replace(" in past month", " last month") if bought else None,
            "store": "Amazon.in",
            "link": r.get("link_clean") or r.get("link") or "",
            "thumbnail_url": _big_image(r["thumbnail"]),
        })
    return offers


def parse_filters(data: dict) -> dict[str, list[tuple[str, str]]]:
    """Each filter group's options as (name, rh code)."""
    return {group: [(o["name"], o["rh"]) for o in opts if o.get("name") and o.get("rh")]
            for group, opts in (data.get("filters") or {}).items()}


def to_vocab(group: str, name: str) -> tuple[str, str] | None:
    """Amazon's filter option → Cupid's (attribute, value), e.g. ("colour", "Greys") → ("colour", "grey")."""
    if group not in FILTER_GROUPS:
        return None
    key, vocab = FILTER_GROUPS[group]
    n = name.lower()
    value = _match(n, vocab) or (_match(n[:-1], vocab) if n.endswith("s") else None)
    return (key, value) if value else None


def option_for(filters: dict, key: str, value: str) -> tuple[str, str] | None:
    """The Amazon filter option (group, rh) that means Cupid's attribute value, if this search offers one."""
    for group, (k, _) in FILTER_GROUPS.items():
        if k != key:
            continue
        for name, rh in filters.get(group, []):
            if to_vocab(group, name) == (key, value):
                return name, rh
    return None


def category_node(filters: dict, hint: str | None) -> str | None:
    """The women's category refinement matching the answer, e.g. "Women's Kurtas & Kurtis"."""
    if not hint:
        return None
    for name, rh in filters.get("category", []):
        n = name.lower()
        if "women" in n and hint in n:
            return rh
    return None


def filter_menu(filters: dict) -> list[dict]:
    """The filters a shopper can set for this search, as Amazon offers them."""
    menu = []
    for label, groups in FILTER_MENU:
        group = next((g for g in groups if filters.get(g)), None)
        if group:
            menu.append({"group": group, "label": label,
                         "options": [{"name": name, "rh": rh, "label": name} for name, rh in filters[group]]})
    return menu


def combine_rh(codes: list[str]) -> str:
    """Amazon refinements: different filters joined with ",", several values of one filter with "|".

    ["p_x:1", "p_x:2", "n:9"] → "p_x:1|2,n:9"
    """
    by_key: dict[str, list[str]] = {}
    for code in codes:
        key, value = code.split(":", 1)
        values = by_key.setdefault(key, [])
        if value not in values:
            values.append(value)
    return ",".join(f"{key}:{'|'.join(values)}" for key, values in by_key.items())


def split_rh(rh: str) -> list[str]:
    """The reverse of combine_rh: "p_x:1|2,n:9" → ["p_x:1", "p_x:2", "n:9"]."""
    codes = []
    for part in filter(None, rh.split(",")):
        key, values = part.split(":", 1)
        codes += [f"{key}:{v}" for v in values.split("|")]
    return codes


def visible_colours(names: list[str]) -> set[str]:
    """Cupid colours a photo may show when the shopper picked these Amazon colours."""
    out: set[str] = set()
    for name in names:
        family = COLOUR_FAMILIES.get(name.lower())
        if family is None:
            mapped = to_vocab("colour", name)
            family = {mapped[1]} if mapped else set()
        out |= family
    return out
