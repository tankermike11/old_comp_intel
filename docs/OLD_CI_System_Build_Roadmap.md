# One Lucky Dog — Competitive Intelligence System: Build Roadmap (v1)

*Working document. Phased, dependency-ordered build plan for the in-house CI system, targeting three delivery surfaces: an internal site, a notification/alert engine, and the monthly brief + deck. Assumes Claude Code as the build environment.*

---

## Framing: four layers, built bottom-up

The three surfaces you named are all **delivery** — they're the top layer. None of them can exist before the data and scoring underneath them do. So the build order isn't "site, then alerts, then brief"; it's foundation-up, with the surfaces layered on once there's something real to deliver.

```
   ┌─────────────────────────────────────────────────────────┐
   │  LAYER 4 — DELIVERY                                       │
   │  Internal site   ·   Notifications   ·   Brief + Deck     │
   ├─────────────────────────────────────────────────────────┤
   │  LAYER 3 — ANALYSIS & SCORING                            │
   │  Dedup/cluster · Impact rubric · "So what for OLD" ·      │
   │  Diff/delta engine · Convergence detector · CCO review    │
   ├─────────────────────────────────────────────────────────┤
   │  LAYER 2 — EVENT STORE  (the backbone; everything is a    │
   │  view over this)                                          │
   ├─────────────────────────────────────────────────────────┤
   │  LAYER 1 — COLLECTION                                     │
   │  Path A: EDGAR / filings / earnings (public names)        │
   │  Path B: app-store notes · pricing diffs · CFTC · press   │
   └─────────────────────────────────────────────────────────┘
```

Everything downstream is a *view* over the event store. Get Layers 1–2 right and the site, alerts, and brief are all just different renderings of the same scored data.

---

## The Claude Code reality check (build vs. run)

Claude Code is an excellent **build** environment for this — it'll scaffold the repo, write the collectors, the store, the scoring module, the site generator, and iterate fast. But be clear about one boundary so you architect correctly:

**Claude Code builds the system; it doesn't run or host it.** The scheduled monthly runs, the always-on alert checks, and the private site all need a **runtime** that exists independent of your Claude Code session. Don't design as if Claude Code is the cron or the web host.

For your "keep costs low, stay nimble" constraints, the pragmatic low-cost stack is:
- **Store:** SQLite to start (simple, file-based, and it happens to match how the last30days skill persists — easy interop if you adopt it). Move to hosted Postgres only if the site later needs real concurrency.
- **Scheduled runs + alerts:** GitHub Actions cron (near-free, version-controlled, no server to babysit) or a small always-on VM if you outgrow it.
- **Internal site:** a **static site regenerated on each run** behind an internal auth gate (SSO or a simple gate). Cheapest possible "always-viewable" surface — no live backend to secure or scale.

Claude Code writes all of that; the runtime just executes what it wrote.

---

## Phased build (prioritized)

### Phase 0 — Foundations *(SPECS COMPLETE — ready to build)*

The two artifacts everything depends on are now specified (see the companion docs):

1. **The event store schema** — specified in `schema.md` (SQLite DDL). Backbone record built on the sightings-vs-events split, with `source_url` mandatory at the schema layer. ✅ *drafted*
2. **The impact-scoring rubric** — specified in `rubric.md`. Two-axis (Industry Impact × Relevance-to-OLD) weighted engine with anchored 1–5 scales, action matrix, and a machine-readable output object that maps to the store. This closes the item this roadmap previously flagged as "the one missing linchpin." ✅ *drafted*

Also complete: **`CLAUDE.md`** (repo briefing carrying the watchlist, wedge, convergence thesis, and engineering guardrails) and the **EDGAR collector spec** (`edgar_collector_spec.md`, the first Phase-1 pipeline). ✅ *drafted*

*Deliverable:* a correct (empty) store and a rubric that can score a hand-entered event end to end — now ready to implement in Claude Code.

### Phase 1 — Collection MVP *(highest-signal, lowest-maintenance sources first)*

Build the collectors in value order, not completeness order:

- **Path A — EDGAR pipeline.** The submissions API + full-text search for your public names (COIN, HOOD, IBKR, Webull, Futu/Moomoo, Schwab; IG Group via its UK filings for tastytrade). Pull 10-K/10-Q/8-K + earnings transcripts. Stable, free, doesn't break like a scraper — and it's the layer you'd otherwise rent from AlphaSense. **This is your edge; build it in-house regardless of anything else.**
- **Path B — the two collectors that earn their keep first:** app-store release-notes and pricing/fee-page semantic diffing. These are the highest-signal, lowest-noise product surfaces for every competitor.
- **Decision point (build vs. adopt):** for the *social/buzz + hiring-signal* collection, evaluate the `last30days` skill (sandboxed, after the compliance/security gates below) rather than hand-building brittle scrapers. Recommendation: build Path A + the two Path-B collectors in-house now; slot buzz in via `last30days` later once vetted.

*Deliverable:* the store auto-populating for Tier-1 names across EDGAR + the two product surfaces.

### Phase 2 — Analysis *(turn raw events into scored, contextualized intelligence)*

- **Dedup / cluster-merge** — same event across surfaces collapses to one (blog + release note + tweet = one launch).
- **Apply the rubric** → score every event; the model narrates *why* each dimension scored as it did, plus the **"so what for OLD"** line and the **"reinforce or dilute our wedge?"** test.
- **Diff/delta engine** — link each new event to the same product line over time, so the 4th feature on a 6-month-old product reads as *sustained investment*, not an isolated ship (your original component 4).
- **Convergence detector** — flag when any watched name adds/acquires one of the other two pillars.
- **Human-in-the-loop** — a CCO/product adjudication step on high-scored items before they're marked "confirmed." Ties to your existing 48-hour CCO review SLA.

*Deliverable:* a scored, deduped, contextualized event stream.

### Phase 3 — Delivery surface #1: the monthly brief (+ deck) *(build this output first)*

Even though it's third on your list, the **brief is the right first surface** — it forces the whole pipeline to work end-to-end, it's the thing people actually read, and it needs almost no infrastructure. It de-risks everything downstream.

- Brief generator: one command → the scored monthly digest with "so what" lines, straight from the store.
- Deck generator: the same data rendered to slides from a template (when you want this built, it'd use the presentation tooling + your Old Lucky Dog brand system).

*Deliverable:* one-command monthly brief + deck.

### Phase 4 — Delivery surface #2: the internal site *(a living view over the store)*

The private, always-viewable surface. Because it's a static regeneration over the same store, the marginal effort is mostly front-end.

- Views: competitor profiles, **product-line timelines** (where the diff/story visualizes beautifully), the scored-event feed, the convergence tracker, and search across everything you've collected.
- Behind internal auth; regenerated each pipeline run.

*Why after the brief:* richer surface, more effort, same underlying data — value compounds but it's not the fastest path to "is this useful?"

*Deliverable:* a private site internal users can check anytime.

### Phase 5 — Delivery surface #3: notifications *(last, deliberately)*

Alerts go last on purpose. **Alert quality depends on calibrated triggers, and a noisy alert channel gets muted — which quietly kills the credibility of the whole system.** You need baseline data and reliable delta/convergence detection before you can tell "material" from "marketing re-announcement."

- Start **narrow and high-precision**: new S-1 filed (Kraken, Polymarket), a convergence pillar-add, or an impact score above a threshold *with CCO confirmation*. Rare and right beats frequent and fuzzy.
- Expand the trigger set only after you've tuned against real history.
- Channel: Slack/webhook or email.

*Deliverable:* trigger-based alerts people trust because they're rare and correct.

---

## Parallel track — the 12–18 month baseline

Run this **once, early, alongside Phases 1–2** (don't serialize it behind them):
- EDGAR history for the public names (free, deep).
- **Wayback Machine** for historical product/pricing pages (the only way to reconstruct the past you can't scrape live).
- A one-time deep social pass (via `last30days --as-of`, if adopted, or manual) for the private names.

This backfills the store so the diff/delta engine has history to compare against from day one.

---

## Cross-cutting gates *(must clear before production)*

1. **Compliance/legal sign-off on collection methods.** The *data* is public; the *methods* (any scraping, browser-cookie sessions, third-party skills) are what your CCO/legal need to approve for a broker-dealer. Do this before wiring anything into production, and before adopting `last30days`.
2. **Security review + version-pinning** for any adopted third-party component; sandbox it, no production credentials.
3. **Anti-hallucination, enforced at the store layer:** no event is written without a `source_url`. Primary-source-or-omit isn't a guideline here, it's a schema constraint.

---

## Immediate next steps (in Claude Code)

Phase-0 specs are done — the next actions are implementation, not more design. Hand Claude Code the kickoff prompt and have it, in order:

1. **Scaffold the repo + drop in `CLAUDE.md`** and the four specs under `/docs`.
2. **Implement the event store** from `schema.md` (v1-essential tables) and seed the `competitor` table from the watchlist.
3. **Implement the deterministic rubric engine** (`score.py`) from `rubric.md`, with the two worked examples as golden test cases. ✅ *spec done — was previously the blocking "still missing" item*
4. **Build the EDGAR collector** from `edgar_collector_spec.md` — the first live pipeline and fastest path to real data in the store.
5. **In parallel (non-code):** book the compliance conversation on collection methods so it's not a late blocker for the Path-B / social collectors.

---

## Flagged decisions

- **Runtime/hosting:** GitHub Actions cron (recommended for low cost) vs. small VM vs. serverless.
- **Build vs. adopt for buzz/social:** hand-build later vs. adopt `last30days` (recommended: adopt, post-gates).
- **Store:** SQLite to start (recommended) vs. hosted Postgres (only if the site needs concurrency).
- **Site auth:** SSO vs. simple internal gate.
- **CCO-in-the-loop ownership + SLA:** who adjudicates high-scored items, at what turnaround (align to the existing 48-hour review SLA).
