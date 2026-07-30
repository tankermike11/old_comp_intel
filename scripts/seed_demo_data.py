"""Dev-only utility: seed a handful of realistic scored events so the internal
site (surfaces/site.py) has something to render without a live Anthropic API
key. NOT part of the production pipeline — run.py's cluster -> narrate -> score
path is the real one. Scores here are computed for real by pipeline.score
(same engine, same rubric.yaml) from hand-entered dimension inputs matching
the rubric's worked examples; only the LLM narration/evidence-citation step is
skipped, since that requires a live API call.

Usage: python -m scripts.seed_demo_data [--reset]
"""
import argparse
import json
import uuid

from config import db_path
from db.init_db import connect, init_db
from db.store import create_run, finish_run, insert_assessment, insert_sighting, update_event_after_assessment
from pipeline.score import score_event


def _insert_event(conn, event_id, competitor_id, title, event_date, run_id):
    conn.execute(
        "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
        "VALUES (?, ?, ?, 'other', ?, ?)",
        (event_id, competitor_id, title, event_date, run_id),
    )
    conn.commit()


def _score_and_store(conn, event_id, industry_dims, relevance_dims, wedge_direction, confidence,
                      category, pillar, so_what, dimension_evidence):
    scored = score_event(industry_dims, relevance_dims, wedge_direction, confidence)
    assessment_id = str(uuid.uuid4())
    insert_assessment(
        conn, assessment_id, event_id, "v1", "demo-seed",
        {
            **scored,
            "industry_dimensions": industry_dims,
            "relevance_dimensions": relevance_dims,
            "dimension_evidence": json.dumps(dimension_evidence),
            "so_what": so_what,
        },
    )
    update_event_after_assessment(conn, event_id, category, pillar, confidence, scored["convergence_flag"], assessment_id)
    return scored


def seed(conn):
    run_id = "demo-seed-run"
    create_run(conn, run_id, "adhoc", sources=json.dumps(["demo"]))

    # 1. Coinbase / Deribit — golden example 1 (ACT_SOON, convergence alert)
    e1 = "demo-event-coinbase-deribit"
    _insert_event(conn, e1, "coinbase", "Coinbase closes Deribit acquisition (crypto options)", "2025-08-15", run_id)
    insert_sighting(conn, {
        "id": str(uuid.uuid4()), "competitor_id": "coinbase", "run_id": run_id, "event_id": e1,
        "surface": "edgar", "source_url": "https://www.sec.gov/Archives/edgar/data/1679788/000167978826000011/q425shareholderletter.htm",
        "observed_at": "2026-02-12", "title": "Coinbase Q4 2025 shareholder letter",
        "raw_excerpt": "Derivatives, notably Deribit, continued to be an area of strong performance for us.",
        "content_hash": "demo-hash-1", "embedding": None,
    })
    _score_and_store(
        conn, e1,
        {"novelty": 4, "reach": 4, "revenue": 5, "defensibility": 4, "regulatory": 4},
        {"pillar": 4, "audience": 3, "wedge": 2, "convergence": 5, "time_to_impact": 2},
        "neutral", "high", "acquisition_ma", "crypto",
        "A market-defining consolidation converging toward our options core from the crypto side, "
        "but US-gated, so relevance is moderate-and-rising. The CFTC DCM/DCO licensing milestone is "
        "the trigger to watch — the day it clears, this re-scores toward PRIORITIZE.",
        {"revenue": "Derivatives, notably Deribit, continued to be an area of strong performance for us."},
    )

    # 2. tastytrade education series — golden example 2 (WEDGE_WATCH -> escalated to COUNTER_POSITION)
    e2 = "demo-event-tastytrade-education"
    _insert_event(conn, e2, "tastytrade", "tastytrade launches free options-income education series", "2026-06-01", run_id)
    insert_sighting(conn, {
        "id": str(uuid.uuid4()), "competitor_id": "tastytrade", "run_id": run_id, "event_id": e2,
        "surface": "press_blog", "source_url": "https://www.tastylive.com/",
        "observed_at": "2026-06-01", "title": "tastylive new education series",
        "raw_excerpt": "A new free series focused entirely on trading options for income.",
        "content_hash": "demo-hash-2", "embedding": None,
    })
    _score_and_store(
        conn, e2,
        {"novelty": 2, "reach": 2, "revenue": 2, "defensibility": 2, "regulatory": 1},
        {"pillar": 5, "audience": 5, "wedge": 5, "convergence": 1, "time_to_impact": 5},
        "threatens", "high", "content_education", "options",
        "Market-negligible, and a single blended score would have averaged this to a forgettable "
        "~52 'Moderate.' The two-axis split surfaces it correctly: our closest analog is contesting "
        "the precise ground our strategy is built on, with our precise audience.",
        {"wedge": "A new free series focused entirely on trading options for income."},
    )

    # 3. Robinhood 10-Q — prediction-markets roadmap signal (real fixture text)
    e3 = "demo-event-robinhood-prediction"
    _insert_event(conn, e3, "robinhood", "Robinhood signals accelerated prediction-markets roadmap", "2026-04-29", run_id)
    insert_sighting(conn, {
        "id": str(uuid.uuid4()), "competitor_id": "robinhood", "run_id": run_id, "event_id": e3,
        "surface": "edgar", "source_url": "https://www.sec.gov/Archives/edgar/data/1783879/000178387926000062/hood-20260331.htm",
        "observed_at": "2026-04-29", "title": "Robinhood Q1 2026 10-Q",
        "raw_excerpt": "our plans to accelerate delivery of futures and derivative product offerings, including prediction markets;",
        "content_hash": "demo-hash-3", "embedding": None,
    })
    _score_and_store(
        conn, e3,
        {"novelty": 3, "reach": 4, "revenue": 3, "defensibility": 2, "regulatory": 3},
        {"pillar": 2, "audience": 3, "wedge": 1, "convergence": 4, "time_to_impact": 4},
        "neutral", "medium", "regulatory_filing", "prediction",
        "Robinhood continues doubling down on prediction markets as a growth line, a moderate "
        "convergence signal from the scale aggressor already spanning all three pillars.",
        {"convergence": "our plans to accelerate delivery of futures and derivative product offerings, including prediction markets;"},
    )

    # 4. Webull — a routine, low-signal event (LOG_ONLY territory)
    e4 = "demo-event-webull-ui"
    _insert_event(conn, e4, "webull", "Webull ships minor charting UI refresh", "2026-05-10", run_id)
    insert_sighting(conn, {
        "id": str(uuid.uuid4()), "competitor_id": "webull", "run_id": run_id, "event_id": e4,
        "surface": "app_store_ios", "source_url": "https://apps.apple.com/us/app/webull/id1170622119",
        "observed_at": "2026-05-10", "title": "Webull iOS release notes",
        "raw_excerpt": "Minor bug fixes and performance improvements to the charting module.",
        "content_hash": "demo-hash-4", "embedding": None,
    })
    _score_and_store(
        conn, e4,
        {"novelty": 1, "reach": 2, "revenue": 1, "defensibility": 1, "regulatory": 1},
        {"pillar": 2, "audience": 2, "wedge": 1, "convergence": 1, "time_to_impact": 5},
        "neutral", "high", "feature_launch", "options",
        "Routine maintenance release with no strategic signal — logged for completeness only.",
        {"novelty": "Minor bug fixes and performance improvements to the charting module."},
    )

    finish_run(conn, run_id, status="complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    path = init_db(reset=args.reset) if args.reset else db_path()
    connection = connect(path)
    try:
        seed(connection)
    finally:
        connection.close()
    print(f"Seeded demo data into {path}")
