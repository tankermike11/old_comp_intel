"""Deterministic rubric rollup (docs/OLD_CI_Impact_Scoring_Rubric.md).

Engine computes, model narrates: this module is pure functions over dimension
scores it is handed. It never calls an LLM and never emits narration — that is
narrate.py's job. Weights, buckets, the action matrix, and overrides all come
from config/rubric.yaml; no magic numbers here.
"""
from config import get_rubric as _get_rubric


def get_rubric():
    return _get_rubric()


def compute_axis_score(dimension_scores, weights):
    """dimension_scores/weights: {dim_name: value}. Returns an int 0-100."""
    raw = sum(dimension_scores[dim] * weight for dim, weight in weights.items())
    return round((raw - 1) / 4 * 100)


def bucket_for_score(score_0_100, rubric=None):
    rubric = rubric or get_rubric()
    for b in rubric["buckets"]:
        if b["min"] <= score_0_100 <= b["max"]:
            return b["label"]
    raise ValueError(f"score {score_0_100} out of bucket range")


def tier_for_score(score_0_100, rubric=None):
    rubric = rubric or get_rubric()
    tiers = rubric["matrix_tiers"]
    if score_0_100 >= tiers["high_min"]:
        return "High"
    if score_0_100 >= tiers["moderate_min"]:
        return "Moderate"
    return "Low"


def headline_score(industry_score, relevance_score):
    return max(industry_score, relevance_score)


def action_for_tiers(industry_tier, relevance_tier, rubric=None):
    rubric = rubric or get_rubric()
    return rubric["action_matrix"][industry_tier][relevance_tier]


def _step_industry_tier_up(industry_tier, rubric):
    order = rubric["industry_tier_order"]
    idx = order.index(industry_tier)
    return order[min(idx + 1, len(order) - 1)]


def _severity_rank(action, rubric):
    return rubric["action_severity_order"].index(action)


def score_event(industry_dimensions, relevance_dimensions, wedge_direction, confidence, rubric=None):
    """Roll up one event's dimension scores into the full assessment object.

    industry_dimensions: {novelty, reach, revenue, defensibility, regulatory} 1-5
    relevance_dimensions: {pillar, audience, wedge, convergence, time_to_impact} 1-5
    wedge_direction: reinforces | validates | dilutes | threatens | neutral
    confidence: high | medium | low
    """
    rubric = rubric or get_rubric()

    industry_score = compute_axis_score(industry_dimensions, rubric["industry_impact"]["weights"])
    relevance_score = compute_axis_score(relevance_dimensions, rubric["old_relevance"]["weights"])
    industry_bucket = bucket_for_score(industry_score, rubric)
    relevance_bucket = bucket_for_score(relevance_score, rubric)

    industry_tier = tier_for_score(industry_score, rubric)
    relevance_tier = tier_for_score(relevance_score, rubric)
    action = action_for_tiers(industry_tier, relevance_tier, rubric)

    overrides = rubric["overrides"]

    # Wedge-threat escalation: one industry tier up, same relevance column.
    wedge_cfg = overrides["wedge_threatens_escalation"]
    if (
        wedge_direction == wedge_cfg["wedge_direction"]
        and relevance_dimensions["wedge"] >= wedge_cfg["wedge_dimension_threshold"]
    ):
        escalated_tier = _step_industry_tier_up(industry_tier, rubric)
        action = action_for_tiers(escalated_tier, relevance_tier, rubric)

    # Convergence pillar-add: floor at ACT_SOON (never downgrades a higher action).
    convergence_cfg = overrides["convergence_pillar_add"]
    convergence_flag = relevance_dimensions["convergence"] >= convergence_cfg["convergence_dimension_threshold"]
    if convergence_flag:
        floor_action = convergence_cfg["floor_action"]
        if _severity_rank(action, rubric) < _severity_rank(floor_action, rubric):
            action = floor_action

    # Low confidence: cap at ACT_SOON pending primary-source confirmation.
    cap_cfg = overrides["low_confidence_action_cap"]
    if confidence == cap_cfg["confidence"]:
        cap_action = cap_cfg["cap_action"]
        if _severity_rank(action, rubric) > _severity_rank(cap_action, rubric):
            action = cap_action

    requires_cco_review = action == "PRIORITIZE" and overrides["prioritize_requires_cco_review"]

    return {
        "industry_score": industry_score,
        "industry_bucket": industry_bucket,
        "relevance_score": relevance_score,
        "relevance_bucket": relevance_bucket,
        "headline_score": headline_score(industry_score, relevance_score),
        "wedge_direction": wedge_direction,
        "convergence_flag": convergence_flag,
        "action": action,
        "requires_cco_review": requires_cco_review,
    }
