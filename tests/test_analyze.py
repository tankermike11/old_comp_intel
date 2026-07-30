import json

import pytest

from db.init_db import connect, create_schema, seed_competitors
from pipeline.analyze import run_analysis_pass
from pipeline.narrate import ASSESSMENT_PROPOSAL_SYSTEM_PROMPT

FAKE_DIMENSION_KEYS = [
    "novelty", "reach", "revenue", "defensibility", "regulatory",
    "pillar", "audience", "wedge", "convergence", "time_to_impact",
]


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.sqlite3")
    create_schema(c)
    seed_competitors(c)
    c.execute("INSERT INTO run (id, type) VALUES ('run-1', 'monthly')")
    c.execute(
        "INSERT INTO sighting (id, competitor_id, run_id, surface, source_url, observed_at, title, raw_excerpt) "
        "VALUES ('s1', 'coinbase', 'run-1', 'edgar', 'https://example.test/8k', '2026-07-24', "
        "'Coinbase expands crypto options access', 'Coinbase expanded access to crypto options via Deribit')"
    )
    c.commit()
    yield c
    c.close()


def _proposal_payload(**overrides):
    payload = {
        "category": "acquisition_ma",
        "pillar": "crypto",
        "confidence": "high",
        "wedge_direction": "neutral",
        "industry_dimensions": {"novelty": 4, "reach": 4, "revenue": 5, "defensibility": 4, "regulatory": 4},
        "relevance_dimensions": {"pillar": 4, "audience": 3, "wedge": 2, "convergence": 5, "time_to_impact": 2},
        "dimension_evidence": {k: "Coinbase expanded access to crypto options via Deribit" for k in FAKE_DIMENSION_KEYS},
    }
    payload.update(overrides)
    return payload


class FakeMessages:
    def __init__(self, proposal_json):
        self.proposal_json = proposal_json

    def create(self, model, max_tokens, system, messages):
        block_cls = type("Block", (), {"type": "text", "text": None})
        block = block_cls()
        block.text = self.proposal_json if system == ASSESSMENT_PROPOSAL_SYSTEM_PROMPT else "So-what narrative text."
        return type("Message", (), {"content": [block]})()


class FakeAnthropicClient:
    def __init__(self, proposal_json):
        self.messages = FakeMessages(proposal_json)


def test_run_analysis_pass_scores_event_and_writes_assessment(conn):
    client = FakeAnthropicClient(json.dumps(_proposal_payload()))
    result = run_analysis_pass(conn, "run-1", client)

    assert len(result["scored"]) == 1
    assert result["skipped"] == []
    assert result["scored"][0]["action"] == "ACT_SOON"  # matches the Coinbase/Deribit golden example
    assert result["scored"][0]["headline_score"] == 80

    event = conn.execute(
        "SELECT category, pillar, confidence, convergence_flag, current_assessment_id FROM event"
    ).fetchone()
    assert event[0] == "acquisition_ma"
    assert event[1] == "crypto"
    assert event[2] == "high"
    assert event[3] == 1
    assert event[4] is not None

    assessment = conn.execute(
        "SELECT industry_score, relevance_score, action, so_what FROM assessment"
    ).fetchone()
    assert assessment[0] == 80
    assert assessment[1] == 54
    assert assessment[2] == "ACT_SOON"
    assert assessment[3] == "So-what narrative text."


def test_run_analysis_pass_skips_event_on_invalid_proposal_without_crashing(conn):
    bad_payload = _proposal_payload(category="not_a_real_category")
    client = FakeAnthropicClient(json.dumps(bad_payload))

    result = run_analysis_pass(conn, "run-1", client)

    assert result["scored"] == []
    assert len(result["skipped"]) == 1
    assert "invalid category" in result["skipped"][0]["reason"]

    # the event still exists (clustering happened) but has no assessment — flagged for human follow-up
    event = conn.execute("SELECT category, current_assessment_id FROM event").fetchone()
    assert event[0] == "other"  # cluster.py's placeholder, never overwritten
    assert event[1] is None
    assert conn.execute("SELECT COUNT(*) FROM assessment").fetchone()[0] == 0


def test_run_analysis_pass_retries_previously_skipped_event_on_a_later_run(conn):
    bad_client = FakeAnthropicClient(json.dumps(_proposal_payload(category="not_a_real_category")))
    first = run_analysis_pass(conn, "run-1", bad_client)
    assert first["scored"] == []
    assert len(first["skipped"]) == 1

    # a later run with no new sightings for it must still retry the earlier skip
    good_client = FakeAnthropicClient(json.dumps(_proposal_payload()))
    second = run_analysis_pass(conn, "run-2", good_client)
    assert second["skipped"] == []
    assert len(second["scored"]) == 1
    assert second["scored"][0]["event_id"] == first["skipped"][0]["event_id"]

    event = conn.execute("SELECT category, current_assessment_id FROM event").fetchone()
    assert event[0] == "acquisition_ma"
    assert event[1] is not None
