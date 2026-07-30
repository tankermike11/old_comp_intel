"""LLM narration + dimension-score proposals (docs/OLD_CI_Impact_Scoring_Rubric.md;
docs/OLD_CI_System_Build_Roadmap.md, Phase 2).

This module PROPOSES; it never decides. The model is asked for (a) 1-5 dimension
scores per axis with a cited evidence quote, plus category/pillar/confidence/
wedge_direction, and (b) — once score.py has already computed the deterministic
rollup — a narrative "so what" line. Every proposed field is validated against
vocab.py / rubric.yaml before score.py ever sees it: an out-of-range score, an
invalid enum value, or an evidence quote that isn't a literal substring of the
event's own sighting excerpts gets the whole proposal rejected, never coerced
into looking valid (CLAUDE.md guardrail #1 and #2).
"""
import json

from config import get_rubric
from vocab import CATEGORY, CONFIDENCE, PILLAR, WEDGE_DIRECTION

ASSESSMENT_PROPOSAL_SYSTEM_PROMPT = """You are proposing a competitive-impact assessment \
for One Lucky Dog (OLD), a US options-first retail brokerage with crypto and prediction \
markets as additional pillars. OLD's defensible wedge is a content/education flywheel, an \
anti-guru stance, income-as-architecture product design, and transparent active-trader \
pricing. Its audience is active options traders and income-oriented retail traders.

You will be given one clustered competitive development (an "event") and the raw, \
source-cited sighting excerpts it was built from. Propose an assessment as JSON only, \
with exactly these keys:

- category: one of feature_launch, product_launch, pricing_change, acquisition_ma, \
regulatory_filing, partnership, hiring_signal, content_education, platform_infra, other
- pillar: one of options, crypto, prediction, equities_etfs, futures, multi, other — the \
asset-class pillar this development touches
- confidence: one of high, medium, low — how well-sourced/confirmed this development is
- wedge_direction: one of reinforces, validates, dilutes, threatens, neutral — how this \
development interacts with OLD's wedge (content/education, anti-guru, income-as-architecture, \
transparent pricing)
- industry_dimensions: {"novelty": 1-5, "reach": 1-5, "revenue": 1-5, "defensibility": 1-5, \
"regulatory": 1-5} — Industry Impact axis, anchored 1 (low) / 3 (mid) / 5 (high)
- relevance_dimensions: {"pillar": 1-5, "audience": 1-5, "wedge": 1-5, "convergence": 1-5, \
"time_to_impact": 1-5} — Relevance-to-OLD axis, anchored 1 (low) / 3 (mid) / 5 (high)
- dimension_evidence: an object with the same 10 dimension keys, each value a VERBATIM \
quote copied exactly from the provided sighting excerpts supporting that score — never \
paraphrase, and never cite something not present in the excerpts

Score conservatively and only from what the excerpts actually say. wedge scores magnitude \
of relevance to the wedge, not direction — a competitor validating OR threatening the wedge \
both score high on the wedge dimension."""

SO_WHAT_SYSTEM_PROMPT = """You write the "so what" narration for One Lucky Dog (OLD)'s \
competitive intelligence brief. OLD is a US options-first retail brokerage with crypto and \
prediction markets as additional pillars — its name is not related to pets or dogs in any \
way, and the brief is never about animals; every event concerns financial-services \
competitors. OLD's defensible wedge is a content/education flywheel, an anti-guru stance, \
income-as-architecture product design, and transparent active-trader pricing.

You are given an event, its computed (not your own) scores, bucket labels, and action, plus \
the dimension evidence. Write 2-4 sentences: what the development is, why each axis landed \
where it did, the implication for OLD, the wedge direction, and the recommended posture. \
State the action and scores exactly as given — never invent a different number or action. \
Plain prose, no JSON, no headers."""


def _validate_proposal(raw, source_text, rubric):
    if not isinstance(raw, dict):
        raise ValueError("proposal is not a JSON object")

    if raw.get("category") not in CATEGORY:
        raise ValueError(f"invalid category: {raw.get('category')!r}")
    if raw.get("pillar") not in PILLAR:
        raise ValueError(f"invalid pillar: {raw.get('pillar')!r}")
    if raw.get("confidence") not in CONFIDENCE:
        raise ValueError(f"invalid confidence: {raw.get('confidence')!r}")
    if raw.get("wedge_direction") not in WEDGE_DIRECTION:
        raise ValueError(f"invalid wedge_direction: {raw.get('wedge_direction')!r}")

    industry_keys = set(rubric["industry_impact"]["weights"])
    relevance_keys = set(rubric["old_relevance"]["weights"])

    industry_dims = raw.get("industry_dimensions")
    relevance_dims = raw.get("relevance_dimensions")
    if not isinstance(industry_dims, dict) or set(industry_dims) != industry_keys:
        raise ValueError(f"industry_dimensions must have exactly these keys: {sorted(industry_keys)}")
    if not isinstance(relevance_dims, dict) or set(relevance_dims) != relevance_keys:
        raise ValueError(f"relevance_dimensions must have exactly these keys: {sorted(relevance_keys)}")

    for dim, score_val in {**industry_dims, **relevance_dims}.items():
        if not isinstance(score_val, int) or isinstance(score_val, bool) or not (1 <= score_val <= 5):
            raise ValueError(f"dimension {dim!r} score must be an int 1-5, got {score_val!r}")

    evidence = raw.get("dimension_evidence")
    all_dim_keys = industry_keys | relevance_keys
    if not isinstance(evidence, dict) or set(evidence) != all_dim_keys:
        raise ValueError(f"dimension_evidence must have exactly these keys: {sorted(all_dim_keys)}")
    for dim, quote in evidence.items():
        if not quote or quote not in source_text:
            raise ValueError(
                f"dimension_evidence[{dim!r}] is not a literal substring of this event's sighting excerpts — rejected"
            )

    return {
        "category": raw["category"],
        "pillar": raw["pillar"],
        "confidence": raw["confidence"],
        "wedge_direction": raw["wedge_direction"],
        "industry_dimensions": industry_dims,
        "relevance_dimensions": relevance_dims,
        "dimension_evidence": evidence,
    }


def _extract_text(message):
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


def _parse_json_response(text):
    """Models frequently wrap JSON in a ```json ... ``` fence even when told
    "JSON only" — strip one before parsing rather than letting json.loads choke on it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    return json.loads(text)


def propose_assessment(anthropic_client, event, sightings, model="claude-sonnet-5", rubric=None):
    """event: {"title": ...}. sightings: list of {surface, source_url, observed_at, raw_excerpt}.
    Returns a validated proposal dict, or raises ValueError if the model's output fails
    validation — callers must not fall back to a fabricated default on failure.
    """
    rubric = rubric or get_rubric()
    source_text = "\n".join(s["raw_excerpt"] or "" for s in sightings)

    sighting_block = "\n\n".join(
        f"[{s['surface']} — {s['observed_at']} — {s['source_url']}]\n{s['raw_excerpt']}"
        for s in sightings
    )
    user_content = f"Event title: {event['title']}\n\nSighting excerpts:\n\n{sighting_block}"

    message = anthropic_client.messages.create(
        model=model,
        max_tokens=2048,
        system=ASSESSMENT_PROPOSAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = _parse_json_response(_extract_text(message))
    return _validate_proposal(raw, source_text, rubric)


def write_so_what(anthropic_client, event, assessment, model="claude-sonnet-5"):
    """assessment: the dict returned by score.score_event, plus dimension_evidence merged in.
    Returns plain narrative text. Never asked to compute or restate a different score.
    """
    user_content = (
        f"Event: {event['title']}\n"
        f"Industry Impact: {assessment['industry_score']} ({assessment['industry_bucket']})\n"
        f"Relevance to OLD: {assessment['relevance_score']} ({assessment['relevance_bucket']})\n"
        f"Headline score: {assessment['headline_score']}\n"
        f"Wedge direction: {assessment['wedge_direction']}\n"
        f"Convergence flag: {assessment['convergence_flag']}\n"
        f"Action: {assessment['action']}\n"
        f"Dimension evidence: {json.dumps(assessment.get('dimension_evidence', {}))}"
    )
    message = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        system=SO_WHAT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    return _extract_text(message).strip()
