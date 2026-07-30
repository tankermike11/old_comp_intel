import pytest

from db import queries
from db.init_db import connect, create_schema, seed_competitors


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    c.execute("INSERT INTO run (id, type) VALUES ('run-1', 'monthly')")
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, pillar, event_date, convergence_flag, created_run_id) "
        "VALUES ('e-scored', 'coinbase', 'Coinbase closes Deribit acquisition', 'acquisition_ma', 'crypto', "
        "'2026-07-24', 1, 'run-1')"
    )
    c.execute(
        "INSERT INTO assessment (id, event_id, rubric_version, industry_score, industry_bucket, "
        "relevance_score, relevance_bucket, headline_score, wedge_direction, action, requires_cco_review, so_what, dimension_evidence) "
        "VALUES ('a-1', 'e-scored', 'v1', 80, 'Very High', 54, 'Moderate', 80, 'neutral', 'ACT_SOON', 0, "
        "'So what narrative.', '{}')"
    )
    c.execute("UPDATE event SET current_assessment_id = 'a-1' WHERE id = 'e-scored'")
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES ('e-unscored', 'robinhood', 'Robinhood pending event', 'other', '2026-07-20', 'run-1')"
    )
    c.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, event_id, surface, source_url, observed_at, title, raw_excerpt) "
        "VALUES ('s1', 'coinbase', 'run-1', 'e-scored', 'edgar', 'https://example.test/8k', '2026-07-24', "
        "'Coinbase 8-K', 'Coinbase expanded access to crypto options via Deribit')"
    )
    c.commit()
    yield c
    c.close()


def test_list_competitors_returns_all_twelve(conn):
    competitors = queries.list_competitors(conn)
    assert len(competitors) == 12
    assert all("name" in c and "pillars" in c for c in competitors)


def test_list_current_events_only_returns_scored_events(conn):
    events = queries.list_current_events(conn)
    assert len(events) == 1
    assert events[0]["id"] == "e-scored"
    assert events[0]["headline_score"] == 80
    assert events[0]["action"] == "ACT_SOON"
    assert events[0]["competitor_name"] == "Coinbase"


def test_list_current_events_filters_by_competitor(conn):
    assert len(queries.list_current_events(conn, competitor_id="coinbase")) == 1
    assert len(queries.list_current_events(conn, competitor_id="robinhood")) == 0


def test_list_current_events_convergence_only(conn):
    events = queries.list_current_events(conn, convergence_only=True)
    assert len(events) == 1
    assert events[0]["id"] == "e-scored"


def test_list_unscored_events_surfaces_pending_event(conn):
    unscored = queries.list_unscored_events(conn)
    assert len(unscored) == 1
    assert unscored[0]["id"] == "e-unscored"


def test_sightings_for_event(conn):
    sightings = queries.sightings_for_event(conn, "e-scored")
    assert len(sightings) == 1
    assert sightings[0]["source_url"] == "https://example.test/8k"


def test_latest_run(conn):
    run = queries.latest_run(conn)
    assert run["id"] == "run-1"


def test_get_run_by_id(conn):
    assert queries.get_run(conn, "run-1")["id"] == "run-1"
    assert queries.get_run(conn, "does-not-exist") is None


def test_list_current_events_includes_created_run_id(conn):
    events = queries.list_current_events(conn)
    assert events[0]["created_run_id"] == "run-1"
