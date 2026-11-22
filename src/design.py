"""Shared visual tokens: presentation choices never change metric arithmetic.

Keeping named colors and geometry in one module lets charts and HTML cards use
the same visual vocabulary. The bevel belongs to the panel, not the data marks:
perspective on bars would make their measured lengths harder to compare.
"""

COLORS = {
    "paper": "#F7F6F3", "surface": "#FFFFFF", "ink": "#171717",
    "muted": "#625D54", "border": "#DDD8CE", "orange": "#FF512B",
    "purple": "#913EF4", "cyan": "#02BFCF", "green": "#12804C",
    "loaded": "#257252", "duplicate": "#9A650D", "invalid": "#BA3F2D",
    "outcome": "#376E87", "informational": "#77756F",
}
GEOMETRY = {"card_accent_px": 8, "radius_px": 6, "control_height_px": 44,
            "chart_height_px": 360, "content_width_px": 1440}
FONT_FAMILY = "Arial, Helvetica, sans-serif"
SLOGAN = "Make every metric meaningful."
PRODUCT_CATEGORY = "Operational Decision Intelligence"
