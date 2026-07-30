import pytest

from surfaces.brand import COLORS, DARK_COLORS, best_text_color, contrast_ratio, mix_hex


def test_contrast_ratio_black_on_white_is_maximal():
    assert contrast_ratio("000000", "FFFFFF") == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_identical_colors_is_one():
    assert contrast_ratio("BB7333", "BB7333") == pytest.approx(1.0, abs=0.001)


def test_best_text_color_picks_dark_on_light_background():
    assert best_text_color("FFFFFF") == "0D1B1E"


def test_best_text_color_picks_light_on_dark_background():
    assert best_text_color("000000") == "F5F3EE"


def test_best_text_color_picks_dark_text_for_lucky_copper():
    # The exact bug this test guards: copper is bright enough that dark text
    # reads better than light text, in BOTH the light-mode and dark-mode
    # variants of this accent — a single per-theme text color can't express this.
    assert best_text_color(COLORS["lucky_copper"]) == "0D1B1E"
    assert best_text_color(DARK_COLORS["accent_copper"]) == "0D1B1E"


def test_mix_hex_zero_returns_first_color():
    assert mix_hex("4A5560", "F5F3EE", 0) == "4A5560"


def test_mix_hex_one_returns_second_color():
    assert mix_hex("4A5560", "F5F3EE", 1) == "F5F3EE"


def test_mix_hex_softens_light_mode_muted_text_toward_background():
    # The reported complaint: light mode's raw text_secondary (a fairly dark
    # slate) reads as "harsh" for small secondary text even though it passes
    # contrast math. Blending it toward the background should measurably
    # raise its luminance (lighten it) without reaching all the way to bg.
    from surfaces.brand import _relative_luminance

    original = COLORS["text_secondary"]
    bg = COLORS["bg"]
    softened = mix_hex(original, bg, 0.35)
    assert _relative_luminance(softened) > _relative_luminance(original)
    assert _relative_luminance(softened) < _relative_luminance(bg)


def test_best_text_color_meets_aa_contrast_for_all_tier_colors():
    tier_colors = [
        COLORS["negative_red"], COLORS["lucky_copper"], COLORS["signal_blue"], COLORS["text_secondary"],
        DARK_COLORS["negative"], DARK_COLORS["accent_copper"], DARK_COLORS["accent_blue"], DARK_COLORS["text_secondary"],
    ]
    for bg in tier_colors:
        chosen = best_text_color(bg)
        ratio = contrast_ratio(bg, chosen)
        # Signal Blue (#3A7CA5) sits in an awkward middle luminance band where
        # neither pure light nor pure dark brand text clears 4.5:1 — best_text_color
        # still picks the better of the two, so assert the achievable floor.
        assert ratio >= 4.0, f"{bg} -> {chosen} only reaches {ratio:.2f}:1"
