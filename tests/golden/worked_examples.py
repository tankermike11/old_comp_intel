"""Golden calibration set — the two worked examples from docs/OLD_CI_Impact_Scoring_Rubric.md.
Frozen human-scored anchors. If a rerun changes these without a rubric_version bump, that's drift.
"""

EXAMPLE_1_COINBASE_DERIBIT = {
    "name": "Coinbase closes Deribit acquisition (crypto options), Aug 2025",
    "industry_dimensions": {
        "novelty": 4, "reach": 4, "revenue": 5, "defensibility": 4, "regulatory": 4,
    },
    "relevance_dimensions": {
        "pillar": 4, "audience": 3, "wedge": 2, "convergence": 5, "time_to_impact": 2,
    },
    "wedge_direction": "neutral",
    "confidence": "high",
    "expected": {
        "industry_score": 80,
        "industry_bucket": "Very High",
        "relevance_score": 54,
        "relevance_bucket": "Moderate",
        "headline_score": 80,
        "convergence_flag": True,
        "action": "ACT_SOON",
        "requires_cco_review": False,
    },
}

EXAMPLE_2_TASTYTRADE_EDUCATION = {
    "name": "tastytrade launches free options-income education series (illustrative)",
    "industry_dimensions": {
        "novelty": 2, "reach": 2, "revenue": 2, "defensibility": 2, "regulatory": 1,
    },
    "relevance_dimensions": {
        "pillar": 5, "audience": 5, "wedge": 5, "convergence": 1, "time_to_impact": 5,
    },
    "wedge_direction": "threatens",
    "confidence": "high",
    "expected": {
        "industry_score": 20,
        "industry_bucket": "Low",
        "relevance_score": 85,
        "relevance_bucket": "Very High",
        "headline_score": 85,
        "convergence_flag": False,
        # Base matrix cell is WEDGE_WATCH; wedge_direction=threatens with wedge>=4
        # escalates one industry tier within the High-relevance column -> COUNTER_POSITION.
        "action": "COUNTER_POSITION",
        "requires_cco_review": False,
    },
}

GOLDEN_SET = [EXAMPLE_1_COINBASE_DERIBIT, EXAMPLE_2_TASTYTRADE_EDUCATION]
