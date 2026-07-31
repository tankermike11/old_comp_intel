"""Orchestrator: one monthly collection pass (EDGAR + iOS App Store) end to
end, plus the Phase 2 analysis pass.

Opens a `run` row, calls the EDGAR collector for the in-scope public
competitors (those with an EDGAR filings_path and a resolvable ticker) and
the App Store collector for competitors with a verified iOS app id
(config/app_store_ids.yaml), lands verified sightings into the store, then
runs cluster -> narrate -> score (pipeline/analyze.py) — across BOTH
surfaces' sightings together, since the pipeline is surface-agnostic — to
turn this run's new sightings into scored events, and closes the run.
"""
import argparse
import json
import uuid
from datetime import datetime, timezone

import anthropic

from collectors import app_store, edgar
from collectors.rate_limiter import make_http_client
from config import db_path, get_anthropic_api_key, get_app_store_ids, get_competitors, get_settings
from db.init_db import connect
from db.store import (
    create_run,
    finish_run,
    get_or_create_surface,
    insert_sighting,
    update_surface_last_checked,
)
from pipeline.analyze import run_analysis_pass

QUARTERLY_MIN_DAYS = 80


def in_scope_public_competitors(competitors):
    return [c for c in competitors if c.get("filings_path") == "edgar" and c.get("tickers")]


def should_collect(cadence, last_checked, run_date):
    """Monthly-cadence competitors always run. Quarterly ones (thinkorswim) only
    run on first pass or once >= QUARTERLY_MIN_DAYS have elapsed since last_checked.
    """
    if cadence != "quarterly":
        return True
    if last_checked is None:
        return True
    last = datetime.strptime(last_checked, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (run_date - last).days >= QUARTERLY_MIN_DAYS


def _run_edgar_collection(conn, edgar_client, edgar_limiter, anthropic_client, settings, run_id, run_date, summary):
    for competitor in in_scope_public_competitors(get_competitors()):
        surface = get_or_create_surface(conn, competitor["id"], "edgar", collector="collectors.edgar")
        if not should_collect(competitor["cadence"], surface["last_checked"], run_date):
            summary["competitors"][competitor["id"]] = "skipped (quarterly cadence, not due)"
            continue

        sightings = edgar.collect_for_competitor(
            edgar_client, edgar_limiter, anthropic_client, settings, competitor, run_id,
            last_checked=surface["last_checked"],
        )
        written = sum(1 for s in sightings if insert_sighting(conn, s))
        update_surface_last_checked(conn, surface["id"], run_date.strftime("%Y-%m-%d"))

        summary["competitors"][competitor["id"]] = f"{written} new sighting(s) ({len(sightings)} candidates)"
        summary["total_sightings"] += written


def _run_app_store_collection(conn, app_store_client, app_store_limiter, settings, run_id, run_date, summary):
    for competitor_id, app_id in get_app_store_ids().items():
        surface = get_or_create_surface(conn, competitor_id, "app_store_ios", collector="collectors.app_store")
        sightings = app_store.collect_for_competitor(
            app_store_client, app_store_limiter, settings, competitor_id, app_id, run_id,
        )
        written = sum(1 for s in sightings if insert_sighting(conn, s))
        update_surface_last_checked(conn, surface["id"], run_date.strftime("%Y-%m-%d"))

        summary["competitors"][f"{competitor_id} (app_store_ios)"] = f"{written} new sighting(s) ({len(sightings)} candidates)"
        summary["total_sightings"] += written


def run_monthly_edgar_pass(run_id=None, run_type="monthly"):
    settings = get_settings()
    run_date = datetime.now(timezone.utc)
    run_id = run_id or f"{run_date.strftime('%Y-%m')}-{run_type}-{uuid.uuid4().hex[:8]}"

    conn = connect(db_path())
    anthropic_client = anthropic.Anthropic(
        api_key=get_anthropic_api_key(), http_client=make_http_client()
    )
    edgar_client, edgar_limiter = edgar.build_client_and_limiter(settings)
    app_store_client, app_store_limiter = app_store.build_client_and_limiter(settings)

    create_run(conn, run_id, run_type, sources=json.dumps(["edgar", "app_store_ios"]))

    summary = {"run_id": run_id, "competitors": {}, "total_sightings": 0}
    try:
        _run_edgar_collection(conn, edgar_client, edgar_limiter, anthropic_client, settings, run_id, run_date, summary)
        _run_app_store_collection(conn, app_store_client, app_store_limiter, settings, run_id, run_date, summary)

        analysis = run_analysis_pass(
            conn, run_id, anthropic_client,
            model=settings["analysis"]["model"], rubric_version=settings["analysis"]["rubric_version"],
        )
        summary["events_scored"] = len(analysis["scored"])
        summary["events_skipped"] = analysis["skipped"]

        finish_run(conn, run_id, status="complete")
    except Exception:
        finish_run(conn, run_id, status="failed")
        raise
    finally:
        conn.close()
        edgar_client.close()
        app_store_client.close()

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="monthly", choices=["monthly", "baseline", "convergence_check", "adhoc"])
    args = parser.parse_args()
    result = run_monthly_edgar_pass(run_type=args.type)
    print(json.dumps(result, indent=2))
