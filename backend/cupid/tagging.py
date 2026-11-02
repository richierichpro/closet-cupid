"""Attribute vocabulary, title keyword tagging, and feature names.

Every item ends up with one value per attribute (colour, pattern, category,
fabric, fit, vibe, price band). The engine scores each value, so these lists
are the "attributes" Cupid learns about.
"""

import re

# value -> keywords that mean it in a product title
COLOURS = {
    "black": ["black", "jet black"],
    "white": ["white", "off white", "off-white", "ivory"],
    "cream": ["cream"],
    "beige": ["beige", "nude", "khaki", "sand", "taupe"],
    "brown": ["brown", "coffee", "chocolate", "tan", "rust", "camel"],
    "olive": ["olive", "sage"],
    "green": ["green", "emerald", "mint", "bottle green"],
    "mustard": ["mustard", "ochre"],
    "yellow": ["yellow", "lemon", "gold", "golden"],
    "orange": ["orange", "peach", "coral"],
    "red": ["red", "cherry"],
    "maroon": ["maroon", "wine", "burgundy"],
    "pink": ["pink", "fuchsia", "magenta", "rani"],
    "pastel": ["pastel", "lavender", "lilac", "mauve", "powder blue", "baby pink"],
    "purple": ["purple", "violet", "plum"],
    "blue": ["blue", "cobalt", "royal blue", "sky blue"],
    "navy": ["navy", "indigo"],
    "teal": ["teal", "turquoise", "aqua"],
    "grey": ["grey", "gray", "charcoal", "silver"],
    "multicolour": ["multicolour", "multicolor", "multi-colour", "multi color"],
}

# A second, coarser layer so one swipe on "olive" also teaches "earthy".
COLOUR_TONE = {
    "black": "neutral", "white": "neutral", "cream": "neutral", "grey": "neutral",
    "beige": "earthy", "brown": "earthy", "olive": "earthy", "mustard": "earthy",
    "maroon": "deep", "navy": "deep", "teal": "deep", "purple": "deep",
    "green": "bright", "yellow": "bright", "orange": "bright", "red": "bright",
    "pink": "bright", "blue": "bright", "multicolour": "bright",
    "pastel": "pastel",
}

PATTERNS = {
    "solid": ["solid", "plain"],
    "floral": ["floral", "flower"],
    "stripes": ["stripe", "striped"],
    "checks": ["check", "checked", "checkered", "plaid", "gingham", "houndstooth"],
    "polka": ["polka"],
    "geometric": ["geometric", "abstract"],
    "animal": ["leopard", "animal print", "zebra"],
    "embroidered": ["embroidered", "embroidery", "chikankari", "chikan", "thread work"],
    "sequin": ["sequin", "sequinned", "sequined", "embellished", "mirror work"],
    "block print": ["block print", "bagru", "ajrakh", "dabu"],
    "graphic": ["graphic", "slogan", "printed tee"],
    "tie-dye": ["tie dye", "tie-dye", "bandhani", "leheriya"],
}

CATEGORIES = {
    "kurta set": ["kurta set", "kurta with pant", "kurta with palazzo", "kurta with trouser", "kurta with dupatta",
                  "kurta with skirt", "kurta pant", "kurta palazzo", "suit set"],
    "kurta": ["kurta", "kurti", "tunic"],
    "saree": ["saree", "sari"],
    "lehenga": ["lehenga", "lehnga", "ghagra"],
    "anarkali": ["anarkali"],
    "co-ord set": ["co-ord", "coord", "co ord", "two piece set", "2 piece set"],
    "maxi dress": ["maxi dress", "maxi"],
    # "Shirt dress" starts at the same word as "shirt"; listed first, the dress wins the tie.
    "dress": ["dress", "gown", "shirt dress", "t-shirt dress", "tshirt dress", "sweater dress", "tank dress",
              "blazer dress", "hoodie dress", "jumper dress", "tee dress", "slip dress", "sundress"],
    "jumpsuit": ["jumpsuit", "playsuit", "romper"],
    "crop top": ["crop top", "cropped top"],
    "t-shirt": ["t-shirt", "tshirt", "tee"],
    "shirt": ["shirt"],
    "top": ["top", "blouse", "camisole"],
    "jeans": ["jeans", "denim pant"],
    "trousers": ["trouser", "pants", "palazzo", "culottes", "cargo"],
    "skirt": ["skirt"],
    "shorts": ["shorts"],
    "blazer": ["blazer"],
    "jacket": ["jacket", "shacket", "overshirt"],
    "sweater": ["sweater", "cardigan", "pullover", "sweatshirt", "hoodie"],
    # Shoes and bags: the category is the type.
    "sneakers": ["sneakers", "sneaker", "sports shoes", "running shoes", "trainers", "casual shoes"],
    "boots": ["boots", "boot", "chelsea"],
    "heels": ["heels", "heel", "stiletto", "stilettos", "pumps", "wedges", "wedge", "platform"],
    "sandals": ["sandals", "sandal", "slides", "slippers", "flip flops", "flip-flops", "chappal", "chappals"],
    "flats": ["flats", "ballerina", "ballet", "loafers", "loafer", "mules", "jutti", "juttis", "mojari", "kolhapuri"],
    "backpack": ["backpack"],
    "tote": ["tote"],
    "sling bag": ["sling", "crossbody", "cross body", "cross-body"],
    "clutch": ["clutch", "potli", "wristlet"],
    "handbag": ["handbag", "hand bag", "shoulder bag", "satchel", "hobo", "purse", "bag"],
}

ETHNIC_CATEGORIES = {"kurta set", "kurta", "saree", "lehenga", "anarkali"}
SHOE_CATEGORIES = {"sneakers", "boots", "heels", "sandals", "flats"}
BAG_CATEGORIES = {"backpack", "tote", "sling bag", "clutch", "handbag"}

FABRICS = {
    "linen": ["linen"],
    "cotton": ["cotton", "mulmul", "khadi"],
    "silk": ["silk", "chanderi", "banarasi", "tussar"],
    "satin": ["satin"],
    "denim": ["denim"],
    "chiffon": ["chiffon", "georgette", "organza", "net"],
    "rayon": ["rayon", "viscose", "modal"],
    "knit": ["knit", "knitted", "crochet", "ribbed", "wool"],
    "velvet": ["velvet"],
    "crepe": ["crepe"],
    "polyester": ["polyester", "lycra", "spandex"],
}

FITS = {
    "relaxed": ["oversized", "relaxed", "loose", "boxy", "baggy", "boyfriend", "mom fit"],
    "fitted": ["slim", "skinny", "bodycon", "fitted", "tight", "body con", "athletic"],
    "straight": ["straight"],
    "flared": ["a-line", "a line", "flared", "flare", "anarkali", "umbrella", "skater", "flowy"],
    "wide": ["wide leg", "wide-leg", "palazzo", "culottes", "flared pant"],
}

# The shape details Amazon filters on and titles usually mention.
SLEEVES = {
    "sleeveless": ["sleeveless", "strappy", "spaghetti", "tube"],
    "short sleeve": ["short sleeve", "short sleeves", "half sleeve", "half sleeves", "cap sleeve"],
    "3/4 sleeve": ["3/4 sleeve", "3/4 sleeves", "3/4th sleeve", "three quarter"],
    "long sleeve": ["long sleeve", "long sleeves", "full sleeve", "full sleeves", "bracelet sleeve"],
}
NECKS = {
    "v-neck": ["v-neck", "v neck"],
    "round neck": ["round neck", "crew neck", "jewel neck"],
    "halter": ["halter"],
    "square neck": ["square neck"],
    "sweetheart": ["sweetheart"],
    "off-shoulder": ["off shoulder", "off-shoulder", "one shoulder", "one-shoulder", "asymmetric neck"],
    "high neck": ["high neck", "mock neck", "turtle neck"],
    "collared": ["collared", "collar", "notch neck"],
    "boat neck": ["boat neck"],
    "cowl": ["cowl"],
}
LENGTHS = {
    "mini": ["mini", "above the knee", "mid-thigh", "mid thigh"],
    "knee length": ["knee length", "knee-length"],
    "midi": ["midi", "below the knee", "calf length", "mid-calf", "mid calf"],
    "maxi": ["maxi", "ankle length", "ankle-length", "floor length", "floor-length", "gown"],
}
SILHOUETTES = {
    "a-line": ["a-line", "a line"],
    "bodycon": ["bodycon", "body con"],
    "fit & flare": ["fit & flare", "fit and flare", "fit-and-flare", "skater"],
    "wrap": ["wrap"],
    "mermaid": ["mermaid", "fish cut", "fishcut"],
    "sheath": ["sheath"],
    "shift": ["shift"],
}

# Style families: used for the warm-up deck and wildcards. Tagged by the
# vision model only, since titles rarely say "boho".
VIBES = ["minimal", "boho", "romantic", "glam", "classic", "edgy", "casual", "y2k"]

PRICE_BANDS = [(25, "under 25"), (40, "25-40"), (60, "40-60"), (90, "60-90"), (150, "90-150")]  # US dollars

# What each vibe looks like, in words the vision model can match against a photo.
# "a minimal style outfit" was too vague: it almost never won, so minimal decks came up empty.
VIBE_PROMPTS = {
    "minimal": "a minimalist dress with clean lines, a solid colour and no embellishment",
    "boho": "a bohemian boho dress, flowy, with a floral or paisley print, tiers or ruffles",
    "romantic": "a romantic feminine dress with lace, ruffles or soft florals",
    "glam": "a glamorous evening dress with sequins, sparkle, satin or a dramatic slit",
    "classic": "a classic, timeless, elegant tailored dress",
    "edgy": "an edgy dress in black, with leather, cutouts, chains or a grunge look",
    "casual": "a casual everyday dress, like a t-shirt dress or a simple knit",
    "y2k": "a y2k 2000s style dress, a bodycon mini in a bold trendy colour",
}

# Prompts for zero-shot tagging with the vision model, per attribute.
ZERO_SHOT_PROMPTS = {
    "colour": lambda v: f"a {v} coloured piece of clothing",
    "pattern": lambda v: "plain solid colour clothing" if v == "solid" else f"clothing with a {v} pattern",
    "category": lambda v: f"a photo of a women's {v}",
    "vibe": lambda v: VIBE_PROMPTS[v],
}
ZERO_SHOT_VALUES = {
    "colour": list(COLOURS),
    "pattern": list(PATTERNS),
    "category": list(CATEGORIES),
    "vibe": VIBES,
}

# Attributes used as engine features, in display order.
FEATURE_KEYS = ["category", "group", "colour", "tone", "pattern", "fabric", "fit",
                "sleeve", "neck", "length", "silhouette", "vibe", "price"]


def price_band(price: float | None) -> str | None:
    if price is None:
        return None
    for ceiling, label in PRICE_BANDS:
        if price < ceiling:
            return label
    return "150+"


def _match(title: str, vocab: dict[str, list[str]]) -> str | None:
    """Return the vocab value whose keyword appears earliest in the title.

    Ties go to the value listed first, which is why specific values
    ("kurta set", "maxi dress") come before general ones in the vocab.
    """
    best, best_pos = None, len(title) + 1
    for value, keywords in vocab.items():
        for kw in keywords:
            m = re.search(rf"\b{re.escape(kw)}\b", title)
            if m and m.start() < best_pos:
                best, best_pos = value, m.start()
    return best


def tags_from_title(title: str) -> dict[str, str]:
    t = title.lower()
    tags = {}
    for key, vocab in (("colour", COLOURS), ("pattern", PATTERNS), ("category", CATEGORIES),
                       ("fabric", FABRICS), ("fit", FITS), ("sleeve", SLEEVES), ("neck", NECKS),
                       ("length", LENGTHS), ("silhouette", SILHOUETTES)):
        value = _match(t, vocab)
        if value:
            tags[key] = value
    # "Shirt kurta", "kurta top": the ethnic word says what the garment is.
    # Shoes and bags are named for what they go with ("potli bag for lehenga"), so the
    # ethnic override below only applies to clothes.
    accessory = tags.get("category") in SHOE_CATEGORIES | BAG_CATEGORIES
    ethnic = _match(t, {c: CATEGORIES[c] for c in CATEGORIES if c in ETHNIC_CATEGORIES})
    if ethnic and not accessory:
        tags["category"] = ethnic
    return tags


def derive_tags(tags: dict[str, str], price: float | None) -> dict[str, str]:
    """Add the coarse attributes that follow from the fine ones."""
    out = dict(tags)
    if "colour" in out:
        out["tone"] = COLOUR_TONE[out["colour"]]
    if "category" in out:
        c = out["category"]
        out["group"] = ("shoes" if c in SHOE_CATEGORIES else "bags" if c in BAG_CATEGORIES
                        else "ethnic" if c in ETHNIC_CATEGORIES else "western")
    band = price_band(price)
    if band:
        out["price"] = band
    return out


def features(tags: dict[str, str]) -> list[str]:
    return [f"{key}:{tags[key]}" for key in FEATURE_KEYS if tags.get(key)]
