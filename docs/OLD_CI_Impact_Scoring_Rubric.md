# One Lucky Dog — Competitive Impact Scoring Rubric (v1)

*Working document and build spec. This is the engine that turns a competitor move into a comparable, non-drifting score plus a recommended action. It's the "engine computes, AI narrates" boundary: the weighted math below produces the numbers; the model only explains them and writes the "so what." Designed to be implemented directly in Claude Code as a scoring function + a narration prompt + the output schema at the end.*

---

## Design principles (why it's built this way)

1. **Two axes, never one blended score.** Every move is scored on **Industry Impact** (how big is this in the market) *and* **Relevance to OLD** (how much does it matter to *us*). These are independent. A move can be market-huge but irrelevant to us, or market-trivial but a direct strike on our wedge. Blending them into one number destroys exactly the signal you most need — so we keep them separate and let the *combination* drive the action.
2. **Anchored scales prevent drift.** Each dimension is scored 1–5 against explicit behavioral anchors. "High" means the same thing in March and September because the anchor, not a vibe, defines it. This is the single most important anti-drift mechanism.
3. **The engine scores; the model narrates.** The model's job is to (a) assign each dimension a 1–5 *with an evidence citation*, and (b) write the narrative. The *rollup math is deterministic code*, not a model guess. No free-floating "this feels like a High."
4. **Source-or-it-didn't-happen.** No dimension is scored without a primary-source citation. Confidence is tracked separately so a rumor-based score is visibly different from an 8-K-based one.

---

## The two axes and their dimensions

Each dimension is scored **1–5**. Weighted within its axis (weights sum to 100%), rolled up, and normalized to a **0–100** score.

### Axis A — Industry Impact

| Dimension | Weight | 1 (low) | 3 (mid) | 5 (high) |
|---|---|---|---|---|
| **Novelty / differentiation** | 25% | Pure parity; copies something already common | Meaningful improvement on an existing capability | Genuinely new primitive or first-of-kind in the US market |
| **Addressable reach** | 20% | Niche sub-segment or small user base | A significant trader segment | Mass-market; touches the bulk of retail traders |
| **Revenue-model implication** | 20% | No monetization change | Modest pressure or a new secondary revenue line | Reshapes a primary revenue pool (major pricing pressure, large new stream, PFOF/NIM/subscription shift) |
| **Defensibility / moat** | 15% | Trivially replicable (UI, marketing) | Replicable with real engineering/integration effort | Durable edge — proprietary infra, exclusive partnership, network effect, hard-won data |
| **Regulatory moat / durability** | 20% | No regulatory barrier to replicate | Requires meaningful compliance work but achievable | Gated by a scarce/slow license (e.g., CFTC DCM/DCO) few can obtain |

### Axis B — Relevance to OLD

| Dimension | Weight | 1 (low) | 3 (mid) | 5 (high) |
|---|---|---|---|---|
| **Pillar overlap** | 25% | Outside OLD's footprint entirely | Hits an adjacent pillar (crypto or prediction) | Direct hit on the options core |
| **Audience overlap** | 20% | Different audience than our personas | Partial overlap with our target personas | Squarely our target (active options traders, Career Hedger, etc.) |
| **Wedge interaction** | 25% | Neutral; no bearing on our differentiation | Touches our wedge indirectly (adjacent to education, pricing transparency, income framing) | Directly reinforces *or threatens* our core differentiation (anti-guru free education, income-as-architecture, transparent active-trader pricing) |
| **Convergence signal** | 15% | No pillar movement | Telegraphs eventual pillar movement (hiring, hints) | Concrete pillar-addition — added/acquired one of the other two pillars |
| **Time-to-impact** | 15% | Distant or regulatory-gated, no clear timeline | Announced, launching within ~6–12 months | Live in-market now |

> **Wedge interaction scores magnitude, not direction.** A competitor *validating* our wedge and one *threatening* it are both highly relevant, so both score high here. The **direction** (reinforces / validates / dilutes / threatens / neutral) is captured separately in the narration and can escalate the action (see overrides).

---

## The math (deterministic — this is the code)

For each axis:

```
raw = Σ (dimension_score × dimension_weight)          # ranges 1–5
score_0_100 = (raw − 1) / 4 × 100                      # maps 1→0, 5→100
```

Bucket each axis score:

| Score | Bucket |
|---|---|
| 80–100 | Very High |
| 60–79 | High |
| 40–59 | Moderate |
| 20–39 | Low |
| 0–19 | Negligible |

For sorting/headlines in the brief, use `headline = max(industry_0_100, old_relevance_0_100)` — never the average (averaging re-buries the split).

---

## The action matrix

Posture is driven by the **combination** of the two axis buckets (collapsing to High ≥60 / Moderate 40–59 / Low <60→<40 for the grid). Rows = Industry Impact, columns = Relevance to OLD.

| | **OLD: Low** | **OLD: Moderate** | **OLD: High** |
|---|---|---|---|
| **Industry: High** | **MONITOR** — big move, not our fight today; watch for drift toward us | **ACT SOON** — significant and brushing our space; assign an owner | **PRIORITIZE** — direct threat or must-close gap; CCO + product, roadmap candidate |
| **Industry: Moderate** | **NOTE** — log, low priority | **TRACK** — standard digest item | **COUNTER-POSITION** — market-modest but hits our differentiation; protect/sharpen the wedge |
| **Industry: Low** | **LOG ONLY** | **LOG** | **WEDGE WATCH** — market-negligible but pokes our exact positioning; the sleeper-strategic quadrant |

**The right column is the point of the whole two-axis design.** COUNTER-POSITION and WEDGE WATCH are moves a single blended score would have averaged into "moderate" and ignored — they're low-market-noise strikes on your differentiation, and for a company whose whole bet is *being different*, they're often the most important things to catch.

### Overrides (applied after the matrix)

- **Convergence pillar-add** (Axis B convergence = 5): action is floored at **ACT SOON** regardless of totals, *and* it fires the always-on convergence alert.
- **Wedge = "threatens"** direction with wedge-interaction ≥ 4: escalate one action level (e.g., COUNTER-POSITION → PRIORITIZE).
- **PRIORITIZE** always requires **CCO adjudication** before it's marked confirmed.
- **Low confidence** (rumor/unconfirmed): cap displayed action at **ACT SOON** until a primary source confirms; flag for verification.

---

## Worked examples (also serve as calibration anchors + code test cases)

### Example 1 — Coinbase closes Deribit acquisition (crypto options), Aug 2025

**Axis A — Industry Impact**

| Dim | Score | Rationale |
|---|---|---|
| Novelty | 4 | Consolidates the #1 crypto-options venue; major, not brand-new-primitive |
| Reach | 4 | Huge user base; crypto-options still a subset of retail |
| Revenue implication | 5 | Options is high-margin; reshapes their derivatives revenue pool |
| Defensibility | 4 | Owning the leading options venue is hard to replicate |
| Regulatory moat | 4 | US requires CFTC DCM/DCO; a real, in-progress barrier |

raw = 4(.25)+4(.20)+5(.20)+4(.15)+4(.20) = **4.2** → **80 → Very High**

**Axis B — Relevance to OLD**

| Dim | Score | Rationale |
|---|---|---|
| Pillar overlap | 4 | Crypto pillar, but it's crypto *options* — brushes the options DNA |
| Audience overlap | 3 | Crypto-derivatives traders partially overlap our active-trader base |
| Wedge interaction | 2 | Little bearing on our content/anti-guru/income wedge |
| Convergence signal | 5 | Crypto exchange acquiring an options venue = textbook convergence into our core |
| Time-to-impact | 2 | US availability gated on CFTC licensing; not live for US yet |

raw = 4(.25)+3(.20)+2(.25)+5(.15)+2(.15) = **3.15** → **54 → Moderate**

**Result:** Very High Industry / Moderate OLD → **ACT SOON**, and convergence=5 **fires the alert**.
**So what:** A market-defining consolidation converging toward our options core from the crypto side, but US-gated, so relevance is *moderate-and-rising*. **The CFTC DCM/DCO licensing milestone is the trigger to watch** — the day it clears, Axis B time-to-impact and pillar-overlap jump and this re-scores toward PRIORITIZE. (Confirms why we flagged that milestone as a priority one-time ingest.)

### Example 2 — tastytrade launches a free options-*income* education series (illustrative)

**Axis A — Industry Impact**

| Dim | Score | Rationale |
|---|---|---|
| Novelty | 2 | A content series, not a market primitive |
| Reach | 2 | Meaningful audience, not mass-market |
| Revenue implication | 2 | Indirect funnel, no direct monetization change |
| Defensibility | 2 | Content is replicable; brand/talent is a soft moat |
| Regulatory moat | 1 | None |

raw = 1.8 → **20 → Low**

**Axis B — Relevance to OLD**

| Dim | Score | Rationale |
|---|---|---|
| Pillar overlap | 5 | Options core, income framing |
| Audience overlap | 5 | Exactly the Career Hedger / active options trader |
| Wedge interaction | 5 | Presses directly on our anti-guru free-education + income-as-architecture wedge |
| Convergence signal | 1 | No pillar movement |
| Time-to-impact | 5 | Live now |

raw = 4.4 → **85 → High**

**Result:** Low Industry / High OLD → **WEDGE WATCH**. Wedge direction = *threatens* (a direct competitor pressing our exact differentiation) with wedge-interaction = 5 → **override escalates toward COUNTER-POSITION/PRIORITIZE**, and it goes into the wedge review.
**So what:** Market-negligible, and a single blended score would have averaged this to a forgettable ~52 "Moderate." The two-axis split surfaces it correctly: our closest analog is contesting the precise ground our strategy is built on, with our precise audience. This is a positioning signal, not a feature signal — exactly what we must not miss.

*(These two examples become the first entries in the golden calibration set below.)*

---

## Keeping it honest over time (anti-drift operations)

The rubric only stays trustworthy if it's maintained. Build these in from the start:

1. **Golden calibration set.** Freeze ~10 human-scored events (start with the two above). Re-score them every rubric/model change; if a golden event's score moves without a rubric change, you have drift — investigate before trusting new scores.
2. **Self-consistency sampling.** Have the model score each event 2–3 times; if dimension scores disagree by more than one level, flag for human review rather than averaging silently.
3. **CCO adjudication in the loop.** Every PRIORITIZE (and every escalated wedge-threat) is human-confirmed before it's "confirmed." Ties to the 48-hour CCO review SLA.
4. **Quarterly recalibration.** Review weights, bucket thresholds, and anchors once a quarter — the market shifts, and the rubric should be a living instrument, not frozen.

---

## Machine-readable output (drops into the event store)

The scorer emits one object per event, matching the store schema from the build roadmap:

```json
{
  "event_id": "string",
  "competitor": "string",
  "date": "YYYY-MM-DD",
  "surface": "edgar | app_store | pricing_page | cftc | press | social | careers",
  "source_url": "string (required — no source, no event)",
  "confidence": "high | medium | low",
  "summary": "one-line factual description, grounded in source",

  "industry_impact": {
    "dimensions": { "novelty": 1-5, "reach": 1-5, "revenue": 1-5, "defensibility": 1-5, "regulatory": 1-5 },
    "score_0_100": 0-100,
    "bucket": "Very High | High | Moderate | Low | Negligible"
  },
  "old_relevance": {
    "dimensions": { "pillar": 1-5, "audience": 1-5, "wedge": 1-5, "convergence": 1-5, "time_to_impact": 1-5 },
    "score_0_100": 0-100,
    "bucket": "Very High | High | Moderate | Low | Negligible"
  },

  "headline_score": 0-100,
  "wedge_direction": "reinforces | validates | dilutes | threatens | neutral",
  "convergence_flag": true,
  "action": "PRIORITIZE | ACT_SOON | COUNTER_POSITION | MONITOR | TRACK | WEDGE_WATCH | NOTE | LOG | LOG_ONLY",
  "requires_cco_review": true,
  "so_what": "narration: what it is, why each axis scored as it did, the implication for OLD, the wedge direction, and the recommended posture",
  "dimension_evidence": { "novelty": "source-cited justification", "...": "..." }
}
```

---

## Flagged decisions (tune before locking)

1. **Weights.** Defaults above are a starting position — Novelty and Wedge Interaction are weighted highest deliberately. Tune against the golden set.
2. **Bucket thresholds.** 60/40/20 cutoffs are conventional; adjust if too much lands in "Moderate."
3. **Scale.** 1–5 with 1/3/5 anchors (interpolate 2/4). Switch to 0–4 only if you prefer a defined zero.
4. **Wedge-direction escalation.** Currently a "threatens" direction can bump the action up a level — decide whether that auto-escalation is desired or advisory only.
5. **Headline score.** Using `max()` of the two axes for sorting (recommended) vs. showing both axes unsorted in the brief.
