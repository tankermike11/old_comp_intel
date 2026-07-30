import re

import pytest

from db.init_db import connect, create_schema, seed_competitors
from surfaces.brand import contrast_ratio
from surfaces.site import write_site


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    c.execute("INSERT INTO run (id, type, status) VALUES ('run-1', 'monthly', 'complete')")
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, pillar, event_date, convergence_flag, created_run_id) "
        "VALUES ('e-priority', 'coinbase', 'Coinbase closes Deribit acquisition', 'acquisition_ma', 'crypto', "
        "'2026-07-24', 1, 'run-1')"
    )
    c.execute(
        "INSERT INTO assessment (id, event_id, rubric_version, industry_score, industry_bucket, "
        "relevance_score, relevance_bucket, headline_score, wedge_direction, action, requires_cco_review, "
        "so_what, dimension_evidence) VALUES ('a-1', 'e-priority', 'v1', 92, 'Very High', 88, 'Very High', 92, "
        "'threatens', 'PRIORITIZE', 1, 'A market-defining consolidation.', '{\"novelty\": \"Deribit acquisition closed\"}')"
    )
    c.execute("UPDATE event SET current_assessment_id = 'a-1' WHERE id = 'e-priority'")
    c.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, event_id, surface, source_url, observed_at, title, raw_excerpt) "
        "VALUES ('s1', 'coinbase', 'run-1', 'e-priority', 'edgar', 'https://example.test/8k', '2026-07-24', "
        "'Coinbase 8-K', 'Deribit acquisition closed')"
    )
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES ('e-pending', 'robinhood', 'Robinhood pending signal', 'other', '2026-07-20', 'run-1')"
    )
    c.commit()
    yield c
    c.close()


def test_write_site_creates_expected_files(conn, tmp_path):
    out_dir = tmp_path / "dist"
    write_site(conn, out_dir=out_dir)

    assert (out_dir / "index.html").exists()
    assert (out_dir / "convergence.html").exists()
    assert (out_dir / "competitors.html").exists()
    assert (out_dir / "assets" / "style.css").exists()
    assert (out_dir / "competitors" / "coinbase.html").exists()
    assert (out_dir / "competitors" / "robinhood.html").exists()
    assert len(list((out_dir / "competitors").glob("*.html"))) == 12


def test_index_page_shows_scored_event_and_pending_review(conn, tmp_path):
    out_dir = tmp_path / "dist"
    write_site(conn, out_dir=out_dir)
    index_html = (out_dir / "index.html").read_text(encoding="utf-8")

    assert "Coinbase closes Deribit acquisition" in index_html
    assert "Prioritize" in index_html
    assert "92" in index_html
    assert "Robinhood pending signal" in index_html  # pending-review section
    assert "CCO review required" in index_html
    assert "Convergence" in index_html


def test_convergence_page_only_shows_convergence_flagged_events(conn, tmp_path):
    out_dir = tmp_path / "dist"
    write_site(conn, out_dir=out_dir)
    convergence_html = (out_dir / "convergence.html").read_text(encoding="utf-8")
    assert "Coinbase closes Deribit acquisition" in convergence_html


def test_competitor_profile_page_shows_its_events_and_source_link(conn, tmp_path):
    out_dir = tmp_path / "dist"
    write_site(conn, out_dir=out_dir)
    profile_html = (out_dir / "competitors" / "coinbase.html").read_text(encoding="utf-8")
    assert "Coinbase closes Deribit acquisition" in profile_html
    assert "https://example.test/8k" in profile_html
    assert "A market-defining consolidation." in profile_html


def test_html_escapes_untrusted_text_fields(conn, tmp_path):
    conn.execute(
        "UPDATE event SET title = ? WHERE id = 'e-priority'",
        ('<script>alert("xss")</script>',),
    )
    conn.commit()
    out_dir = tmp_path / "dist"
    write_site(conn, out_dir=out_dir)
    index_html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "<script>alert" not in index_html
    assert "&lt;script&gt;" in index_html


def test_site_generator_never_writes_to_the_db(conn, tmp_path):
    before = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    write_site(conn, out_dir=tmp_path / "dist")
    after = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    assert before == after


def _extract_theme_block(css, selector_pattern):
    match = re.search(rf"{selector_pattern}\s*{{([^}}]*)}}", css)
    assert match, f"no block matching {selector_pattern!r} found in generated CSS"
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]+)", match.group(1)))


def test_link_and_moderate_bucket_text_meet_aa_contrast_both_themes(conn, tmp_path):
    # Regression test for the reported bug: --accent/--accent-warm used directly
    # as small text (links, the "Moderate" bucket label, the convergence pill)
    # must clear 4.5:1 against both backgrounds they can appear on, in both themes.
    write_site(conn, out_dir=tmp_path / "dist")
    css = (tmp_path / "dist" / "assets" / "style.css").read_text(encoding="utf-8")

    dark_default = _extract_theme_block(css, r":root")
    light_media = _extract_theme_block(css, r"@media \(prefers-color-scheme: light\)\s*{\s*:root")

    for theme_name, tokens, backgrounds in [
        ("dark", dark_default, [dark_default["--bg"], dark_default["--surface"]]),
        ("light", light_media, [light_media["--bg"], light_media["--surface"]]),
    ]:
        for bg in backgrounds:
            assert contrast_ratio(tokens["--accent-text"], bg) >= 4.5, (
                f"{theme_name} --accent-text fails AA against {bg}"
            )
            assert contrast_ratio(tokens["--accent-warm-text"], bg) >= 4.5, (
                f"{theme_name} --accent-warm-text fails AA against {bg}"
            )

    assert "color: var(--accent-text)" in css
    assert ".bucket-notable { color: var(--accent-warm-text); }" in css
    assert ".badge-convergence { color: var(--accent-warm-text);" in css
