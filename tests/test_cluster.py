import pytest

from db.init_db import connect, create_schema, seed_competitors
from pipeline import cluster


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    c.execute("INSERT INTO run (id, type) VALUES ('run-1', 'monthly')")
    c.commit()
    yield c
    c.close()


def _insert_sighting(conn, sighting_id, competitor_id, title, excerpt, observed_at, surface="edgar"):
    conn.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, surface, source_url, observed_at, title, raw_excerpt) "
        "VALUES (?, ?, 'run-1', ?, 'https://example.test/doc', ?, ?, ?)",
        (sighting_id, competitor_id, surface, observed_at, title, excerpt),
    )
    conn.commit()


def test_jaccard_similarity_basic():
    a = cluster._tokenize("Coinbase expands crypto options access")
    b = cluster._tokenize("Coinbase expands access to crypto options")
    assert cluster.jaccard_similarity(a, b) > 0.7


def test_jaccard_similarity_dissimilar_text():
    a = cluster._tokenize("Coinbase expands crypto options access")
    b = cluster._tokenize("Webull ships new charting analytics tool")
    assert cluster.jaccard_similarity(a, b) < 0.2


def test_group_by_similarity_merges_near_duplicates_keeps_distinct_apart():
    sightings = [
        {"title": "Coinbase expands crypto options access", "raw_excerpt": "via the Deribit platform"},
        {"title": "Coinbase expands access to crypto options", "raw_excerpt": "on the Deribit platform"},
        {"title": "Coinbase launches new staking rewards program", "raw_excerpt": "unrelated staking feature"},
    ]
    clusters = cluster.group_by_similarity(sightings)
    assert len(clusters) == 2
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_cluster_sightings_into_events_creates_one_event_per_cluster(conn):
    _insert_sighting(conn, "s1", "coinbase", "Coinbase expands crypto options access", "via Deribit", "2026-07-01", "edgar")
    _insert_sighting(conn, "s2", "coinbase", "Coinbase expands access to crypto options", "on Deribit", "2026-07-02", "edgar")
    _insert_sighting(conn, "s3", "coinbase", "Coinbase launches staking rewards program", "unrelated", "2026-07-03", "edgar")
    _insert_sighting(conn, "s4", "robinhood", "Robinhood ships prediction market contracts", "new contracts", "2026-07-01", "edgar")

    event_ids = cluster.cluster_sightings_into_events(conn, "run-1")
    assert len(event_ids) == 3  # 2 coinbase events (one 2-sighting, one 1-sighting) + 1 robinhood event

    rows = conn.execute("SELECT id, event_id FROM sighting ORDER BY id").fetchall()
    event_by_sighting = dict(rows)
    assert event_by_sighting["s1"] == event_by_sighting["s2"]
    assert event_by_sighting["s1"] != event_by_sighting["s3"]
    assert event_by_sighting["s4"] not in (event_by_sighting["s1"], event_by_sighting["s3"])

    events = conn.execute("SELECT id, competitor_id, category, event_date, created_run_id FROM event").fetchall()
    assert len(events) == 3
    for _, _, category, _, created_run_id in events:
        assert category == "other"
        assert created_run_id == "run-1"


def test_cluster_uses_earliest_observed_at_as_event_date(conn):
    _insert_sighting(conn, "s1", "coinbase", "Coinbase expands crypto options access", "via Deribit", "2026-07-05")
    _insert_sighting(conn, "s2", "coinbase", "Coinbase expands access to crypto options", "on Deribit", "2026-07-01")

    cluster.cluster_sightings_into_events(conn, "run-1")
    event_date = conn.execute("SELECT event_date FROM event").fetchone()[0]
    assert event_date == "2026-07-01"


def test_cluster_never_touches_already_clustered_sightings(conn):
    _insert_sighting(conn, "s1", "coinbase", "Coinbase expands crypto options access", "via Deribit", "2026-07-01")
    conn.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date) "
        "VALUES ('existing-event', 'coinbase', 'Pre-existing event', 'other', '2026-06-01')"
    )
    conn.execute("UPDATE sighting SET event_id = 'existing-event' WHERE id = 's1'")
    conn.commit()

    event_ids = cluster.cluster_sightings_into_events(conn, "run-1")
    assert event_ids == []
    assert conn.execute("SELECT event_id FROM sighting WHERE id = 's1'").fetchone()[0] == "existing-event"
