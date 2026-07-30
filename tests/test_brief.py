import pytest

from db.init_db import connect, create_schema, seed_competitors
from surfaces.brief import generate_brief_markdown, write_brief


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    c.execute(
        "INSERT INTO run (id, type, status, started_at, finished_at) VALUES "
        "('run-0', 'monthly', 'complete', '2026-06-01T00:00:00', '2026-06-01T01:00:00')"
    )
    c.execute(
        "INSERT INTO run (id, type, status, started_at, finished_at) VALUES "
        "('run-1', 'monthly', 'complete', '2026-07-24T00:00:00', '2026-07-24T01:00:00')"
    )

    # A PRIORITIZE + convergence event from run-1
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, pillar, event_date, convergence_flag, created_run_id) "
        "VALUES ('e-priority', 'coinbase', 'Coinbase closes Deribit acquisition', 'acquisition_ma', 'crypto', "
        "'2026-07-24', 1, 'run-1')"
    )
    c.execute(
        "INSERT INTO assessment (id, event_id, rubric_version, industry_score, industry_bucket, "
        "relevance_score, relevance_bucket, headline_score, wedge_direction, action, requires_cco_review, "
        "so_what, dimension_evidence, scored_at) VALUES ('a-1', 'e-priority', 'v1', 92, 'Very High', 88, 'Very High', 92, "
        "'threatens', 'PRIORITIZE', 1, 'A market-defining consolidation.', '{}', '2026-07-24T00:15:00')"
    )
    c.execute("UPDATE event SET current_assessment_id = 'a-1' WHERE id = 'e-priority'")
    c.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, event_id, surface, source_url, observed_at, title, raw_excerpt) "
        "VALUES ('s1', 'coinbase', 'run-1', 'e-priority', 'edgar', 'https://example.test/8k', '2026-07-24', "
        "'Coinbase 8-K', 'Deribit acquisition closed')"
    )

    # A pending (unscored) event from run-1
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES ('e-pending', 'robinhood', 'Robinhood pending signal', 'other', '2026-07-20', 'run-1')"
    )

    # An older scored event from run-0 — must NOT appear in run-1's brief
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES ('e-old', 'webull', 'Old Webull event', 'other', '2026-06-01', 'run-0')"
    )
    c.execute(
        "INSERT INTO assessment (id, event_id, rubric_version, industry_score, industry_bucket, "
        "relevance_score, relevance_bucket, headline_score, wedge_direction, action, requires_cco_review, "
        "so_what, dimension_evidence, scored_at) VALUES ('a-old', 'e-old', 'v1', 10, 'Negligible', 10, 'Negligible', 10, "
        "'neutral', 'LOG_ONLY', 0, 'Old news.', '{}', '2026-06-01T00:15:00')"
    )
    c.execute("UPDATE event SET current_assessment_id = 'a-old' WHERE id = 'e-old'")

    # An event clustered in run-0 (narration failed then) but only successfully
    # scored during run-1's execution window — the retry case pipeline/analyze.py
    # handles. Must show up in run-1's brief (scored_at falls in its window),
    # not run-0's (it had no assessment at run-0's brief time).
    c.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES ('e-retried', 'moomoo', 'Moomoo retried event', 'other', '2026-06-15', 'run-0')"
    )
    c.execute(
        "INSERT INTO assessment (id, event_id, rubric_version, industry_score, industry_bucket, "
        "relevance_score, relevance_bucket, headline_score, wedge_direction, action, requires_cco_review, "
        "so_what, dimension_evidence, scored_at) VALUES ('a-retried', 'e-retried', 'v1', 45, 'Moderate', "
        "48, 'Moderate', 48, 'neutral', 'TRACK', 0, 'Scored on retry.', '{}', '2026-07-24T00:30:00')"
    )
    c.execute("UPDATE event SET current_assessment_id = 'a-retried' WHERE id = 'e-retried'")
    c.commit()
    yield c
    c.close()


def test_brief_includes_priority_event_with_sources_and_so_what(conn):
    md = generate_brief_markdown(conn, run_id="run-1")
    assert "Coinbase closes Deribit acquisition" in md
    assert "Prioritize" in md
    assert "A market-defining consolidation." in md
    assert "https://example.test/8k" in md
    assert "Requires CCO review" in md


def test_brief_flags_convergence_signal(conn):
    md = generate_brief_markdown(conn, run_id="run-1")
    assert "Convergence Signals" in md


def test_brief_lists_pending_review(conn):
    md = generate_brief_markdown(conn, run_id="run-1")
    assert "Pending Review" in md
    assert "Robinhood pending signal" in md


def test_brief_excludes_events_from_other_runs(conn):
    md = generate_brief_markdown(conn, run_id="run-1")
    assert "Old Webull event" not in md


def test_brief_for_older_run_shows_only_that_runs_event(conn):
    md = generate_brief_markdown(conn, run_id="run-0")
    assert "Old Webull event" in md
    assert "Coinbase closes Deribit acquisition" not in md


def test_brief_with_no_runs_does_not_crash(tmp_path):
    empty_conn = connect(tmp_path / "empty.sqlite3")
    create_schema(empty_conn)
    seed_competitors(empty_conn)
    md = generate_brief_markdown(empty_conn)
    assert "No runs recorded yet" in md
    empty_conn.close()


def test_write_brief_creates_file(conn, tmp_path):
    out_path = tmp_path / "out" / "brief.md"
    result_path = write_brief(conn, run_id="run-1", out_path=out_path)
    assert result_path == out_path
    assert out_path.exists()
    assert "Coinbase closes Deribit acquisition" in out_path.read_text(encoding="utf-8")


def test_brief_defaults_to_latest_run(conn):
    md = generate_brief_markdown(conn)
    assert "Coinbase closes Deribit acquisition" in md  # run-1 is latest by started_at


def test_brief_includes_event_retried_and_scored_this_run_even_if_clustered_earlier(conn):
    run1_md = generate_brief_markdown(conn, run_id="run-1")
    assert "Moomoo retried event" in run1_md
    assert "Scored on retry." in run1_md

    # it must NOT double up in run-0's brief — it had no assessment at that point
    run0_md = generate_brief_markdown(conn, run_id="run-0")
    assert "Moomoo retried event" not in run0_md
