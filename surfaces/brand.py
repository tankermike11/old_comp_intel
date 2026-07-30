"""One Lucky Dog brand constants, transcribed from `OLD - Branding Guidelines.pdf`
(v1.0, root of repo). Kept in one place so the brief, deck, and site generators
share exact hex values and type choices instead of hardcoding them inline.

Guidelines p.4 gives an explicit mode-per-surface rule: "Use light mode for
decks, proposals, and educational content. Use dark mode for product, charts,
and dense trading workflows." So:
  - deck.py / brief.py -> light mode always (they ARE the deck/proposal case).
  - site.py -> the internal site is exactly "product... dense workflows", so
    it defaults to DARK_COLORS, while still respecting the viewer's OS/toggle
    preference the normal way (light/dark are both real, designed palettes
    below, not an afterthought inversion of one another).

python-pptx (deck.py) can only *request* Sora/Inter/IBM Plex Mono — if a
viewer's machine doesn't have them installed, PowerPoint substitutes a
fallback font, same as any other generated deck.
"""

COLORS = {
    "kennel_black": "0D1B1E",
    "lucky_copper": "BB7333",
    "signal_blue": "3A7CA5",
    "bone": "F5F3EE",
    "deep_teal": "0F4D4A",
    "ledger_green": "2F8F63",
    "negative_red": "C24443",
    # Light-mode UI (guidelines p.4) — decks/briefs use light mode per deck guidance.
    "bg": "F5F3EE",
    "surface": "FFFFFF",
    "text_primary": "0D1B1E",
    "text_secondary": "4A5560",
}

# Dark-mode UI (guidelines p.4's "Dark Mode UI" swatch set) — the site's default,
# per the mode-per-surface rule above. Distinct hex values, not an inversion.
DARK_COLORS = {
    "bg": "101114",
    "surface": "161A1E",
    "text_primary": "F5F3EE",
    "text_secondary": "BFC7CC",
    "accent_copper": "C9782E",
    "accent_blue": "63A4D1",
    "positive": "49A579",
    "negative": "D9685D",
}

FONT_HEADLINE = "Sora"       # headlines and key statements
FONT_BODY = "Inter"         # body copy, labels, presentation content
FONT_MONO = "IBM Plex Mono"  # trading data, metrics, technical callouts

TAGLINE_PRIMARY = "TRUSTED. EXPERIENCED. UNAPOLOGETIC."
TAGLINE_ALT = "LUCK FAVORS PREPARATION."

PUBLIC_BRAND = "ONE LUCKY DOG"
SHORTHAND = "OLD"

# Four-tier severity mapping onto the brand's limited accent palette (guidelines
# p.4 core palette has 6 usable colors total) — kept to a small, consistent set
# rather than inventing arbitrary extra colors per action.
ACTION_TIER_COLOR = {
    "PRIORITIZE": COLORS["negative_red"],
    "ACT_SOON": COLORS["lucky_copper"],
    "COUNTER_POSITION": COLORS["lucky_copper"],
    "WEDGE_WATCH": COLORS["lucky_copper"],
    "MONITOR": COLORS["signal_blue"],
    "TRACK": COLORS["signal_blue"],
    "NOTE": COLORS["text_secondary"],
    "LOG": COLORS["text_secondary"],
    "LOG_ONLY": COLORS["text_secondary"],
}

ACTION_LABELS = {
    "PRIORITIZE": "Prioritize",
    "ACT_SOON": "Act Soon",
    "COUNTER_POSITION": "Counter-Position",
    "WEDGE_WATCH": "Wedge Watch",
    "MONITOR": "Monitor",
    "TRACK": "Track",
    "NOTE": "Note",
    "LOG": "Log",
    "LOG_ONLY": "Log Only",
}

# Display order: most urgent first. Sections/slides with no events are skipped.
ACTION_ORDER = [
    "PRIORITIZE", "ACT_SOON", "COUNTER_POSITION", "WEDGE_WATCH",
    "MONITOR", "TRACK", "NOTE", "LOG", "LOG_ONLY",
]


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(hex_color):
    """WCAG relative luminance, used to pick legible text over an arbitrary
    brand-color background instead of assuming one text color per theme —
    some brand accents (lucky_copper especially) are bright enough that dark
    text reads far better than light text even in an otherwise-dark theme.
    """
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(hex_a, hex_b):
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def best_text_color(bg_hex, light_hex="F5F3EE", dark_hex="0D1B1E"):
    """Whichever of a light/dark text color contrasts better against bg_hex."""
    return light_hex if contrast_ratio(bg_hex, light_hex) >= contrast_ratio(bg_hex, dark_hex) else dark_hex
