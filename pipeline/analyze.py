"""Wires cluster -> narrate -> score -> assessment storage for one run
(docs/OLD_CI_System_Build_Roadmap.md, Phase 2). The single place that turns
freshly-landed sightings into scored events.

Each event is processed independently: a narration failure (an invalid or
ungrounded model proposal, per narrate.py's validation) skips just that event
— logged in the returned summary — rather than aborting the whole pass or
falling back to a fabricated score. Skipped events keep their placeholder
category and no assessment; they surface for human follow-up.

Every run also retries any event clustered in a PRIOR run that never got a
current assessment (narration failed validation last time, or a transient
error). Without this, cluster.py's "only newly-clustered sightings" scope
means a once-skipped event would never be revisited — a real gap, not
hypothetical: live model output varies run to run (e.g. wrapping JSON in a
markdown fence one time and not another), so a retry on the next pass is a
legitimate second chance, not wasted work.
"""
import json
import uuid

from db.queries import list_unscored_events
from db.store import get_event, get_sightings_for_event, insert_assessment, update_event_after_assessment
from pipeline import cluster, narrate, score


def _process_event(conn, event_id, anthropic_client, model, rubric_version):
    """Returns (result_dict, ok). ok=False means result_dict is a {event_id, reason} skip entry."""
    event = get_event(conn, event_id)
    sightings = get_sightings_for_event(conn, event_id)
    try:
        proposal = narrate.propose_assessment(anthropic_client, event, sightings, model=model)
        scored = score.score_event(
            proposal["industry_dimensions"], proposal["relevance_dimensions"],
            proposal["wedge_direction"], proposal["confidence"],
        )
        so_what = narrate.write_so_what(
            anthropic_client, event,
            {**scored, "dimension_evidence": proposal["dimension_evidence"]},
            model=model,
        )
    except (ValueError, KeyError) as exc:
        return {"event_id": event_id, "reason": str(exc)}, False

    assessment_id = str(uuid.uuid4())
    insert_assessment(
        conn, assessment_id, event_id, rubric_version, model,
        {
            **scored,
            "industry_dimensions": proposal["industry_dimensions"],
            "relevance_dimensions": proposal["relevance_dimensions"],
            "dimension_evidence": json.dumps(proposal["dimension_evidence"]),
            "so_what": so_what,
        },
    )
    update_event_after_assessment(
        conn, event_id, proposal["category"], proposal["pillar"], proposal["confidence"],
        scored["convergence_flag"], assessment_id,
    )
    return {"event_id": event_id, "action": scored["action"], "headline_score": scored["headline_score"]}, True


def run_analysis_pass(conn, run_id, anthropic_client, model="claude-sonnet-5", rubric_version="v1"):
    new_event_ids = cluster.cluster_sightings_into_events(conn, run_id)
    retry_event_ids = [ev["id"] for ev in list_unscored_events(conn) if ev["id"] not in new_event_ids]

    scored_events, skipped_events = [], []
    for event_id in new_event_ids + retry_event_ids:
        result, ok = _process_event(conn, event_id, anthropic_client, model, rubric_version)
        (scored_events if ok else skipped_events).append(result)

    return {"scored": scored_events, "skipped": skipped_events}
