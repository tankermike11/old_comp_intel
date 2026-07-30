import sqlite3

import pytest

from db.init_db import connect, create_schema, seed_competitors


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    yield c
    c.close()


def test_seeds_all_twelve_competitors(conn):
    rows = conn.execute("SELECT id FROM competitor").fetchall()
    assert len(rows) == 12
    ids = {r[0] for r in rows}
    assert {"robinhood", "coinbase", "tastytrade", "thinkorswim", "crypto_com"} <= ids


def test_sighting_requires_source_url(conn):
    conn.execute("INSERT INTO run (id, type) VALUES ('r1', 'adhoc')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sighting (id, competitor_id, run_id, surface, source_url, observed_at) "
            "VALUES ('s1', 'coinbase', 'r1', 'edgar', NULL, '2026-01-01')"
        )


def test_sighting_content_hash_unique_per_competitor_and_surface(conn):
    conn.execute("INSERT INTO run (id, type) VALUES ('r1', 'adhoc')")
    conn.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, surface, source_url, observed_at, content_hash) "
        "VALUES ('s1', 'coinbase', 'r1', 'edgar', 'https://x', '2026-01-01', 'hash1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sighting (id, competitor_id, run_id, surface, source_url, observed_at, content_hash) "
            "VALUES ('s2', 'coinbase', 'r1', 'edgar', 'https://y', '2026-01-01', 'hash1')"
        )


def test_event_requires_no_sighting_by_construction(conn):
    # An event can exist with zero sightings at the schema layer (no reverse FK
    # enforces cardinality), but every sighting that references an event must
    # point at a real row — enforced by the FK below.
    conn.execute("INSERT INTO run (id, type) VALUES ('r1', 'adhoc')")
    conn.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date) "
        "VALUES ('e1', 'coinbase', 'Test event', 'feature_launch', '2026-01-01')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sighting (id, competitor_id, run_id, event_id, surface, source_url, observed_at) "
            "VALUES ('s1', 'coinbase', 'r1', 'does-not-exist', 'edgar', 'https://x', '2026-01-01')"
        )
