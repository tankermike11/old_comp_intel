"""One Lucky Dog brand constants, transcribed from `OLD - Branding Guidelines.pdf`
(v1.0, root of repo). Kept in one place so the brief and deck generators share
exact hex values and type choices instead of hardcoding them inline.

Deck guidance (guidelines, p.5): light mode is the default for PowerPoint decks
— strong Sora headers, clear structure via dividers/whitespace, data presented
simply and confidently, consistent branding. python-pptx can only *request*
Sora/Inter/IBM Plex Mono — if a viewer's machine doesn't have them installed,
PowerPoint substitutes a fallback font, same as any other generated deck.
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
