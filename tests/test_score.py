import pytest

from pipeline import score
from tests.golden.worked_examples import GOLDEN_SET


@pytest.mark.parametrize("case", GOLDEN_SET, ids=[c["name"] for c in GOLDEN_SET])
def test_golden_examples_reproduce_exactly(case):
    result = score.score_event(
        industry_dimensions=case["industry_dimensions"],
        relevance_dimensions=case["relevance_dimensions"],
        wedge_direction=case["wedge_direction"],
        confidence=case["confidence"],
    )
    expected = case["expected"]
    assert result["industry_score"] == expected["industry_score"]
    assert result["industry_bucket"] == expected["industry_bucket"]
    assert result["relevance_score"] == expected["relevance_score"]
    assert result["relevance_bucket"] == expected["relevance_bucket"]
    assert result["headline_score"] == expected["headline_score"]
    assert result["convergence_flag"] == expected["convergence_flag"]
    assert result["action"] == expected["action"]
    assert result["requires_cco_review"] == expected["requires_cco_review"]


def test_compute_axis_score_matches_hand_math():
    rubric = score.get_rubric()
    raw = score.compute_axis_score(
        {"novelty": 4, "reach": 4, "revenue": 5, "defensibility": 4, "regulatory": 4},
        rubric["industry_impact"]["weights"],
    )
    assert raw == 80


def test_bucket_boundaries():
    assert score.bucket_for_score(80) == "Very High"
    assert score.bucket_for_score(60) == "High"
    assert score.bucket_for_score(59) == "Moderate"
    assert score.bucket_for_score(40) == "Moderate"
    assert score.bucket_for_score(39) == "Low"
    assert score.bucket_for_score(20) == "Low"
    assert score.bucket_for_score(19) == "Negligible"
    assert score.bucket_for_score(0) == "Negligible"


def test_tier_boundaries():
    assert score.tier_for_score(60) == "High"
    assert score.tier_for_score(59) == "Moderate"
    assert score.tier_for_score(40) == "Moderate"
    assert score.tier_for_score(39) == "Low"


def test_headline_is_max_not_average():
    assert score.headline_score(80, 20) == 80
    assert score.headline_score(20, 85) == 85


def test_convergence_five_floors_action_at_act_soon():
    # Industry Low / Relevance Low would normally be LOG_ONLY; convergence=5 must floor it at ACT_SOON.
    result = score.score_event(
        industry_dimensions={"novelty": 1, "reach": 1, "revenue": 1, "defensibility": 1, "regulatory": 1},
        relevance_dimensions={"pillar": 1, "audience": 1, "wedge": 1, "convergence": 5, "time_to_impact": 1},
        wedge_direction="neutral",
        confidence="high",
    )
    assert result["convergence_flag"] is True
    assert result["action"] == "ACT_SOON"


def test_convergence_floor_does_not_downgrade_a_higher_action():
    # Industry High / Relevance High -> PRIORITIZE already outranks the ACT_SOON floor.
    result = score.score_event(
        industry_dimensions={"novelty": 5, "reach": 5, "revenue": 5, "defensibility": 5, "regulatory": 5},
        relevance_dimensions={"pillar": 5, "audience": 5, "wedge": 5, "convergence": 5, "time_to_impact": 5},
        wedge_direction="neutral",
        confidence="high",
    )
    assert result["action"] == "PRIORITIZE"
    assert result["requires_cco_review"] is True


def test_low_confidence_caps_action_at_act_soon():
    result = score.score_event(
        industry_dimensions={"novelty": 5, "reach": 5, "revenue": 5, "defensibility": 5, "regulatory": 5},
        relevance_dimensions={"pillar": 5, "audience": 5, "wedge": 5, "convergence": 1, "time_to_impact": 5},
        wedge_direction="neutral",
        confidence="low",
    )
    assert result["action"] == "ACT_SOON"


def test_prioritize_always_requires_cco_review():
    result = score.score_event(
        industry_dimensions={"novelty": 5, "reach": 5, "revenue": 5, "defensibility": 5, "regulatory": 5},
        relevance_dimensions={"pillar": 5, "audience": 5, "wedge": 5, "convergence": 1, "time_to_impact": 5},
        wedge_direction="neutral",
        confidence="high",
    )
    assert result["action"] == "PRIORITIZE"
    assert result["requires_cco_review"] is True


def test_score_event_never_calls_llm():
    # Engine computes, model narrates: score.py must have zero references to the anthropic SDK.
    import inspect

    source = inspect.getsource(score)
    assert "anthropic" not in source.lower()
