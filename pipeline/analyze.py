"""Wires cluster -> narrate -> score -> assessment storage for one run
(docs/OLD_CI_System_Build_Roadmap.md, Phase 2). The single place that turns
freshly-landed sightings into scored events.

Each newly-clustered event is processed independently: a narration failure
(an invalid or ungrounded model proposal, per narrate.py's validation) skips
just that event — logged in the returned summary — rather than aborting the
whole pass or falling back to a fabricated score. Skipped events keep their
placeholder category and no assessment; they surface for human follow-up.
"""
import json
import uuid

from db.store import get_event, get_sightings_for_event, insert_assessment, update_event_after_assessment
from pipeline import cluster, narrate, score


def run_analysis_pass(conn, run_id, anthropic_client, model="claude-sonnet-5", rubric_version="v1"):
    new_event_ids = cluster.cluster_sightings_into_events(conn, run_id)

    scored_events, skipped_events = [], []
    for event_id in new_event_ids:
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
            skipped_events.append({"event_id": event_id, "reason": str(exc)})
            continue

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
        scored_events.append({"event_id": event_id, "action": scored["action"], "headline_score": scored["headline_score"]})

    return {"scored": scored_events, "skipped": skipped_events}
