import json

import pytest

import run as run_module
from db.init_db import connect, init_db
from pipeline.narrate import ASSESSMENT_PROPOSAL_SYSTEM_PROMPT

FAKE_DIMENSION_KEYS = [
    "novelty", "reach", "revenue", "defensibility", "regulatory",
    "pillar", "audience", "wedge", "convergence", "time_to_impact",
]


def _fake_proposal_json():
    return json.dumps({
        "category": "feature_launch",
        "pillar": "options",
        "confidence": "medium",
        "wedge_direction": "neutral",
        "industry_dimensions": {"novelty": 2, "reach": 2, "revenue": 2, "defensibility": 2, "regulatory": 1},
        "relevance_dimensions": {"pillar": 3, "audience": 3, "wedge": 2, "convergence": 1, "time_to_impact": 3},
        "dimension_evidence": {k: "Fake excerpt text" for k in FAKE_DIMENSION_KEYS},
    })


class FakeMessages:
    def create(self, model, max_tokens, system, messages):
        block_cls = type("Block", (), {"type": "text", "text": None})
        text = _fake_proposal_json() if system == ASSESSMENT_PROPOSAL_SYSTEM_PROMPT else "Fake so-what narrative."
        block = block_cls()
        block.text = text
        return type("Message", (), {"content": [block]})()


class FakeAnthropic:
    def __init__(self, api_key, **kwargs):
        self.api_key = api_key
        self.messages = FakeMessages()


@pytest.fixture()
def fake_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.sqlite3"
    init_db(path=db_file)
    monkeypatch.setattr(run_module, "db_path", lambda: db_file)
    return db_file


def _fake_collect_for_competitor(client, limiter, anthropic_client, settings, competitor, run_id, last_checked=None):
    return [
        {
            "id": f"sighting-{competitor['id']}-1",
            "competitor_id": competitor["id"],
            "run_id": run_id,
            "event_id": None,
            "surface": "edgar",
            "source_url": f"https://example.test/{competitor['id']}/doc.htm",
            "observed_at": "2026-07-01",
            "title": "Fake sighting",
            "raw_excerpt": "Fake excerpt text",
            "content_hash": f"hash-{competitor['id']}",
            "embedding": None,
        }
    ]


def _fake_app_store_collect(client, limiter, settings, competitor_id, app_id, run_id):
    return []  # keep the App Store side a no-op for these EDGAR-focused orchestrator tests


def test_monthly_pass_lands_sightings_and_closes_run(fake_db, monkeypatch):
    monkeypatch.setattr(run_module.edgar, "collect_for_competitor", _fake_collect_for_competitor)
    monkeypatch.setattr(run_module.app_store, "collect_for_competitor", _fake_app_store_collect)
    monkeypatch.setattr(run_module, "get_anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(run_module.anthropic, "Anthropic", FakeAnthropic)

    summary = run_module.run_monthly_edgar_pass(run_type="monthly")

    conn = connect(fake_db)
    run_row = conn.execute("SELECT status FROM run WHERE id = ?", (summary["run_id"],)).fetchone()
    assert run_row[0] == "complete"

    sightings = conn.execute("SELECT competitor_id, source_url FROM sighting").fetchall()
    assert summary["total_sightings"] == len(sightings)
    assert summary["total_sightings"] > 0
    conn.close()


def test_rerun_is_idempotent_no_duplicate_sightings(fake_db, monkeypatch):
    monkeypatch.setattr(run_module.edgar, "collect_for_competitor", _fake_collect_for_competitor)
    monkeypatch.setattr(run_module.app_store, "collect_for_competitor", _fake_app_store_collect)
    monkeypatch.setattr(run_module, "get_anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(run_module.anthropic, "Anthropic", FakeAnthropic)

    run_module.run_monthly_edgar_pass(run_type="monthly")
    conn = connect(fake_db)
    first_count = conn.execute("SELECT COUNT(*) FROM sighting").fetchone()[0]
    conn.close()

    run_module.run_monthly_edgar_pass(run_type="monthly")
    conn = connect(fake_db)
    second_count = conn.execute("SELECT COUNT(*) FROM sighting").fetchone()[0]
    run_count = conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    conn.close()

    assert second_count == first_count  # content_hash dedupe -> re-run is a no-op on sightings
    assert run_count == 2  # but each execution still stamps its own run row


def _fake_app_store_collect_one(client, limiter, settings, competitor_id, app_id, run_id):
    return [
        {
            "id": f"sighting-{competitor_id}-appstore",
            "competitor_id": competitor_id,
            "run_id": run_id,
            "event_id": None,
            "surface": "app_store_ios",
            "source_url": f"https://apps.apple.com/us/app/id{app_id}",
            "observed_at": "2026-07-01",
            "title": "Fake app release notes",
            "raw_excerpt": "Fake release notes text",
            "content_hash": f"appstore-hash-{competitor_id}",
            "embedding": None,
        }
    ]


def test_monthly_pass_lands_app_store_sightings_too(fake_db, monkeypatch):
    monkeypatch.setattr(run_module.edgar, "collect_for_competitor", _fake_collect_for_competitor)
    monkeypatch.setattr(run_module.app_store, "collect_for_competitor", _fake_app_store_collect_one)
    monkeypatch.setattr(run_module, "get_anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(run_module.anthropic, "Anthropic", FakeAnthropic)

    summary = run_module.run_monthly_edgar_pass(run_type="monthly")

    conn = connect(fake_db)
    app_store_sightings = conn.execute(
        "SELECT competitor_id FROM sighting WHERE surface = 'app_store_ios'"
    ).fetchall()
    conn.close()
    assert len(app_store_sightings) == len(run_module.get_app_store_ids())
    assert summary["total_sightings"] >= len(app_store_sightings)


def test_quarterly_competitor_skipped_when_not_due(fake_db, monkeypatch):
    calls = []

    def counting_collect(client, limiter, anthropic_client, settings, competitor, run_id, last_checked=None):
        calls.append(competitor["id"])
        return _fake_collect_for_competitor(client, limiter, anthropic_client, settings, competitor, run_id, last_checked)

    monkeypatch.setattr(run_module.edgar, "collect_for_competitor", counting_collect)
    monkeypatch.setattr(run_module.app_store, "collect_for_competitor", _fake_app_store_collect)
    monkeypatch.setattr(run_module, "get_anthropic_api_key", lambda: "test-key")
    monkeypatch.setattr(run_module.anthropic, "Anthropic", FakeAnthropic)

    run_module.run_monthly_edgar_pass(run_type="monthly")
    assert "thinkorswim" in calls  # first pass: last_checked is None, always runs

    calls.clear()
    run_module.run_monthly_edgar_pass(run_type="monthly")
    assert "thinkorswim" not in calls  # second pass, same day: quarterly cadence, not due yet
    assert "robinhood" in calls  # monthly cadence always runs
