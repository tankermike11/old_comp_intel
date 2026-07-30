import json

import pytest

from pipeline import narrate
from pipeline.score import get_rubric


class FakeMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text
        self.last_call = None

    def create(self, model, max_tokens, system, messages):
        self.last_call = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
        return FakeMessage(self._response_text)


class FakeAnthropicClient:
    def __init__(self, response_text):
        self.messages = FakeMessages(response_text)


EVENT = {"title": "Coinbase closes Deribit acquisition"}
SIGHTINGS = [
    {
        "surface": "edgar",
        "source_url": "https://example.test/8k",
        "observed_at": "2026-07-24",
        "raw_excerpt": "Coinbase has expanded access to crypto options trading via the Deribit platform for eligible US customers.",
    },
    {
        "surface": "edgar",
        "source_url": "https://example.test/ex99",
        "observed_at": "2026-07-24",
        "raw_excerpt": "This acquisition is gated on completion of CFTC DCM/DCO licensing requirements.",
    },
]


def _valid_proposal_json():
    return json.dumps({
        "category": "acquisition_ma",
        "pillar": "crypto",
        "confidence": "high",
        "wedge_direction": "neutral",
        "industry_dimensions": {"novelty": 4, "reach": 4, "revenue": 5, "defensibility": 4, "regulatory": 4},
        "relevance_dimensions": {"pillar": 4, "audience": 3, "wedge": 2, "convergence": 5, "time_to_impact": 2},
        "dimension_evidence": {
            "novelty": "Coinbase has expanded access to crypto options trading via the Deribit platform",
            "reach": "for eligible US customers",
            "revenue": "Coinbase has expanded access to crypto options trading",
            "defensibility": "via the Deribit platform",
            "regulatory": "gated on completion of CFTC DCM/DCO licensing requirements",
            "pillar": "crypto options trading via the Deribit platform",
            "audience": "eligible US customers",
            "wedge": "Coinbase has expanded access",
            "convergence": "Coinbase has expanded access to crypto options trading via the Deribit platform",
            "time_to_impact": "gated on completion of CFTC DCM/DCO licensing requirements",
        },
    })


def test_propose_assessment_accepts_valid_grounded_proposal():
    client = FakeAnthropicClient(_valid_proposal_json())
    result = narrate.propose_assessment(client, EVENT, SIGHTINGS)
    assert result["category"] == "acquisition_ma"
    assert result["pillar"] == "crypto"
    assert result["industry_dimensions"]["revenue"] == 5
    assert result["relevance_dimensions"]["convergence"] == 5


def test_propose_assessment_rejects_invalid_category():
    payload = json.loads(_valid_proposal_json())
    payload["category"] = "not_a_real_category"
    client = FakeAnthropicClient(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid category"):
        narrate.propose_assessment(client, EVENT, SIGHTINGS)


def test_propose_assessment_rejects_out_of_range_dimension_score():
    payload = json.loads(_valid_proposal_json())
    payload["industry_dimensions"]["novelty"] = 6
    client = FakeAnthropicClient(json.dumps(payload))
    with pytest.raises(ValueError, match="1-5"):
        narrate.propose_assessment(client, EVENT, SIGHTINGS)


def test_propose_assessment_rejects_missing_dimension_key():
    payload = json.loads(_valid_proposal_json())
    del payload["industry_dimensions"]["regulatory"]
    client = FakeAnthropicClient(json.dumps(payload))
    with pytest.raises(ValueError, match="industry_dimensions must have exactly these keys"):
        narrate.propose_assessment(client, EVENT, SIGHTINGS)


def test_propose_assessment_rejects_hallucinated_evidence():
    payload = json.loads(_valid_proposal_json())
    payload["dimension_evidence"]["novelty"] = "Coinbase announced it will acquire the entire NASDAQ exchange."
    client = FakeAnthropicClient(json.dumps(payload))
    with pytest.raises(ValueError, match="not a literal substring"):
        narrate.propose_assessment(client, EVENT, SIGHTINGS)


def test_propose_assessment_rejects_invalid_wedge_direction():
    payload = json.loads(_valid_proposal_json())
    payload["wedge_direction"] = "sideways"
    client = FakeAnthropicClient(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid wedge_direction"):
        narrate.propose_assessment(client, EVENT, SIGHTINGS)


def test_write_so_what_returns_text_and_never_calls_score_logic():
    assessment = {
        "industry_score": 80, "industry_bucket": "Very High",
        "relevance_score": 54, "relevance_bucket": "Moderate",
        "headline_score": 80, "wedge_direction": "neutral",
        "convergence_flag": True, "action": "ACT_SOON",
        "dimension_evidence": {"novelty": "some quote"},
    }
    client = FakeAnthropicClient("A market-defining consolidation. Action: ACT_SOON.")
    so_what = narrate.write_so_what(client, EVENT, assessment)
    assert "ACT_SOON" in so_what
    # the prompt sent to the model must state the computed action, not ask it to invent one
    assert "ACT_SOON" in client.messages.last_call["messages"][0]["content"]
    assert "80" in client.messages.last_call["messages"][0]["content"]
