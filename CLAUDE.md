# CLAUDE.md — One Lucky Dog Competitive Intelligence System

This file orients you (Claude Code) to this repo. Read it first, every session. The detailed specs in `/docs` are the source of truth; this file is the briefing that ties them together and tells you how to work here.

---

## Mission

Build an in-house competitive intelligence system for **One Lucky Dog (OLD)**, a US retail brokerage launching options-first, with crypto and prediction markets as additional pillars. The system monitors a fixed set of competitors, scores each development on two axes, and produces three outputs: a monthly brief (+ deck), a private internal site, and trigger-based alerts. It must be cheap to run, low-maintenance, and trustworthy enough that people act on it.

## Source-of-truth docs (`/docs`) — read the relevant one before touching related code

- `watchlist.md` — the locked Tier-1 competitor set, tiers, ownership, pillars.
- `roadmap.md` — the phased build plan and the four-layer architecture.
- `rubric.md` — the two-axis impact-scoring rubric (dimensions, weights, anchors, action matrix).
- `schema.md` — the event-store data model (sightings vs. events, DDL, vocabularies).

If code and a doc disagree, the doc wins unless a human says otherwise. If a doc is silent, ask rather than invent.

---

## Current phase

We are in **Phase 0 → Phase 1**. Build, in order:
1. The event store from `schema.md` (the v1-essential tables only).
2. The rubric engine from `rubric.md` (deterministic rollup; see guardrails).
3. The **EDGAR collector** (`/docs/edgar_collector_spec.md`) as the first live pipeline.

**Do NOT build yet:** the internal site, the notification/alert layer, the deck generator, or any social/buzz/scraping collector. Those are later phases with their own gates. Don't scaffold them speculatively.

---

## Domain context (so your extraction and scoring make sense)

**OLD's positioning / wedge.** OLD is not competing on raw feature parity — the giants are assembling the same product footprint (see convergence thesis). OLD's defensible wedge is: a content/education flywheel, an **anti-guru** stance (transparent, no hype, no signal-selling), **income-as-architecture** (product design oriented around trading for income, not gambling), and transparent active-trader pricing. When you assess "relevance to OLD," these are what the wedge dimension refers to.

**Audience.** Active options traders and income-oriented retail traders (the "Career Hedger" persona), not passive buy-and-hold investors.

**Convergence thesis (central).** Options, crypto, and prediction markets are collapsing into one competitive set via acquisition (Coinbase→Deribit, Kraken→NinjaTrader, Robinhood→MIAXdx, Kalshi→crypto perps). A competitor adding one of the other two pillars is a first-class signal — it trips `convergence_flag` and a dedicated alert.

**The Tier-1 watchlist** (full detail in `watchlist.md`; this is the seed data for the `competitor` table):

| id | tier | ownership | pillars | filings_path | cadence |
|---|---|---|---|---|---|
| tastytrade | tier1 | private (IG Group) | options | lse (via IG) | monthly |
| robinhood | tier1 | public (HOOD) | options, crypto, prediction | edgar | monthly |
| webull | tier1 | public (BULL) | options, crypto | edgar | monthly |
| interactive_brokers | tier1 | public (IBKR) | options, crypto, prediction, futures | edgar | monthly |
| public_com | tier1 | private | options, crypto, equities_etfs | none | monthly |
| moomoo | tier1 | public (FUTU, foreign private issuer) | options, crypto | edgar (20-F/6-K) | monthly |
| coinbase | tier1 | public (COIN) | crypto, options | edgar | monthly |
| kraken | tier1 | pre_ipo | crypto, futures | edgar (once S-1 lands) | monthly |
| kalshi | tier1 | private | prediction, crypto | cftc | monthly |
| polymarket | tier1 | pre_ipo | prediction | cftc | monthly |
| thinkorswim (schwab) | benchmark | public (SCHW) | options | edgar | quarterly |
| crypto_com | convergence_watch | private | crypto, prediction, equities_etfs | none | on-trigger |

US-only scope. Non-US launches are out of scope — US regulatory approval is the gating blocker, so foreign product velocity is a weak predictor of what reaches our market.

---

## Architecture (four layers; detail in `roadmap.md`)

```
Collection  →  Event Store  →  Analysis & Scoring  →  Delivery
(collectors)   (SQLite)        (cluster/score/       (brief · site · alerts)
                                narrate + CCO review)
```

Everything downstream is a query over the event store. Get collection and the store right and the rest is rendering.

### Repo layout

```
CLAUDE.md
/docs                 # the four spec docs + edgar_collector_spec.md
/db
  schema.sql          # the DDL from schema.md
  migrations/
/config
  competitors.yaml    # the watchlist as seed data (loads into `competitor`)
  rubric.yaml         # weights, anchors, bucket thresholds (from rubric.md)
  settings.yaml       # user-agent, rate limits, lookback windows
/collectors
  edgar.py            # FIRST — Path A public filings
  app_store.py        # iOS only, via official iTunes API — no compliance gate needed
  # pricing.py, and Android app-store collection, are gated on a CCO/compliance
  # sign-off (guardrail #5) — not built yet
/pipeline
  cluster.py          # dedup: sighting → event
  score.py            # DETERMINISTIC rubric rollup (pure functions)
  narrate.py          # LLM narration + dimension-score proposals
/surfaces             # empty for now (later phases)
/tests
  golden/             # golden calibration set for drift checks
  fixtures/           # saved sample filings for collector tests
run.py                # orchestrator; stamps a `run` row per execution
```

---

## Tech stack & runtime reality

- **Language:** Python (consistent with existing OLD quant code).
- **Store:** SQLite + `sqlite-vec` for embeddings/similarity. One file to start.
- **HTTP:** `httpx` (or `requests`) behind a shared rate-limiter.
- **LLM:** Anthropic SDK, used only for extraction proposals and narration — never for final scores (see guardrails).
- **Runtime:** you build it; you do not host it. Scheduled runs go on **GitHub Actions cron**; the future site is a static regeneration behind auth. Do not write code that assumes a long-running server unless asked.

---

## Engineering guardrails (non-negotiable)

1. **Engine computes, model narrates.** The rubric rollup (weighted sum → 0–100 → bucket → action) lives in `score.py` as pure, tested functions. The LLM may *propose* 1–5 dimension scores with cited evidence; it must never emit the final score, bucket, or action. If you find yourself asking the model for "the impact level," stop — compute it.
2. **Source-or-it-didn't-happen.** No `sighting` is written without a non-empty `source_url`. No `event` exists without ≥1 sighting. Before emitting any extracted excerpt, verify it is a substring of the fetched source text — reject hallucinated quotes.
3. **Rate-limit every external call.** All SEC traffic goes through one shared limiter at ≤8 req/s (safety margin under the 10 req/s cap), ~120 ms spacing, exponential backoff on 429. Always send the configured descriptive User-Agent. Cache responses locally.
4. **Idempotent runs.** Re-running a period must not duplicate data. Dedupe sightings on `content_hash`. Stamp every sighting/event with its `run_id`.
5. **No scraping or third-party skills without a compliance gate.** EDGAR and other official APIs/filings are fine (public, statutory). Anything involving scraping, browser cookies, or third-party data tools requires explicit human/CCO sign-off first — do not add such a collector on your own initiative.
6. **Vocabularies are centralized.** Enums (surface, category, pillar, action, status) live in one module and must match `schema.md` exactly. Don't invent new values inline.
7. **Config over hardcoding.** Competitors, forms, lookbacks, weights, thresholds, and the User-Agent all come from `/config`. No magic values in collector or scoring code.

## Conventions

- **IDs:** slugs for stable entities (`competitor`, `product_line`); UUIDs for transactional rows (`sighting`, `event`, `assessment`).
- **Dates:** ISO-8601 UTC text everywhere.
- **Scores are historized, never overwritten** — re-score into a new `assessment` row and flip `is_current` (needed for drift detection).
- Keep functions small and unit-tested, especially in `score.py` — it's the trust anchor for the whole system.
