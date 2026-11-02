"""From Skin Tone Analysis colours to Cupid's first beliefs about which colours flatter you.

YouCam returns the hex colours of skin, hair and eyes; it doesn't say warm/cool. We read
the undertone from the skin's hue (more yellow = warm, more pink = cool) and the contrast
from how far apart skin and hair are in lightness, then use classic colour-analysis
palettes. These are starting hints: Cupid trusts them less as your swipes come in.
"""

import math

# Undertone → colours that tend to flatter it, and ones that tend to wash it out.
PALETTES = {
    "warm": (["olive", "mustard", "orange", "brown", "cream", "green"], ["grey", "pastel"]),
    "cool": (["navy", "blue", "pink", "purple", "maroon", "teal"], ["orange", "mustard"]),
    "neutral": (["teal", "maroon", "navy", "green", "cream", "pink"], []),
}
HIGH_CONTRAST = ["black", "white", "red"]   # strong skin/hair contrast carries bold colour
LOW_CONTRAST = ["beige", "pastel", "grey"]  # soft contrast suits muted colour


def _lab(hex_colour: str) -> tuple[float, float, float]:
    """sRGB hex → CIE Lab (D65)."""
    h = hex_colour.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (x, y, z)]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def read_colouring(colours: dict[str, str]) -> dict | None:
    """Undertone and contrast from Skin Tone Analysis output, or None if there's no skin colour."""
    skin = colours.get("skin_color")
    if not skin:
        return None
    lightness, a, b = _lab(skin)
    hue = math.degrees(math.atan2(b, a))        # skin sits around 40–70°; higher is more yellow
    undertone = "warm" if hue >= 58 else "cool" if hue <= 48 else "neutral"
    hair = colours.get("hair_color")
    contrast = abs(lightness - _lab(hair)[0]) if hair else None
    level = None if contrast is None else "high" if contrast >= 45 else "low" if contrast <= 25 else "medium"
    return {"undertone": undertone, "contrast": level, "skin": skin, "hair": hair, "eyes": colours.get("eye_color")}


def palette(colouring: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Colours to lean towards and away from, each with the reason Cupid gives on a card."""
    good, bad = PALETTES[colouring["undertone"]]
    tone = colouring["undertone"]
    likes = {c: f"{c.capitalize()} flatters your {tone} undertone" for c in good}
    avoid = {c: f"{c.capitalize()} can wash out a {tone} undertone" for c in bad}
    if colouring["contrast"] == "high":
        likes.update({c: f"{c.capitalize()} suits your high-contrast colouring" for c in HIGH_CONTRAST})
    elif colouring["contrast"] == "low":
        likes.update({c: f"{c.capitalize()} suits your soft, low-contrast colouring" for c in LOW_CONTRAST if c not in avoid})
    return likes, avoid
