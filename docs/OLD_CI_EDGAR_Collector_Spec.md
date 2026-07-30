# One Lucky Dog — EDGAR Collector Spec (v1)

*Build spec for `collectors/edgar.py`, the first live pipeline (Path A). Its job: pull SEC filings for the US-public Tier-1 names, extract source-cited signals, and emit `sighting` rows into the event store. It does not score — scoring is a separate pipeline step. This is the cleanest collector to build first: the data is public and statutory, the API is official and free, and there's no ToS or scraping gate to clear.*

---

## Scope

**In scope:** the US-public watchlist names, via the official SEC EDGAR REST API and full-text search.

| Competitor | Ticker | Filer type | Forms to watch |
|---|---|---|---|
| Coinbase | COIN | Domestic | 8-K, 10-Q, 10-K, DEF 14A, S-1/S-3 |
| Robinhood | HOOD | Domestic | 8-K, 10-Q, 10-K, DEF 14A |
| Interactive Brokers | IBKR | Domestic | 8-K (incl. monthly metrics), 10-Q, 10-K |
| Webull | BULL | Domestic | 8-K, 10-Q, 10-K, S-1 (recent registrant) |
| Charles Schwab / thinkorswim | SCHW | Domestic | 8-K, 10-Q, 10-K *(quarterly cadence — benchmark)* |
| Moomoo (Futu Holdings) | FUTU | **Foreign private issuer** | 20-F (annual), 6-K (interim/material), F-1 |

**Out of scope for this collector (handled elsewhere):**
- **tastytrade** — owned by IG Group, which files on the **LSE (RNS)**, not EDGAR. Separate `lse` collector (`filings_path='lse'`).
- **Kraken / Polymarket** — private today. When either files an **S-1/F-1**, that's a priority one-time ingest; add its CIK to config then.
- **Verbatim earnings-call transcripts** — *not on EDGAR.* EDGAR gives you the 8-K earnings **release** (exhibit EX-99.1) and **shareholder letter** (often EX-99.2), which are rich and roadmap-heavy — but the spoken transcript comes from the webcast/IR or a third party and is a separate, later concern. Do not spec around transcripts here.

---

## API reference (verified current)

- **Base:** `https://data.sec.gov/` — free, no API key.
- **Auth:** a declared `User-Agent` header naming the org + contact email (e.g. `One Lucky Dog research@oneluckydog.com`). Missing/invalid → **403**. Pull from `config/settings.yaml`.
- **Rate limit:** hard cap **10 requests/second per IP**. Exceed → **429** and temporary IP block. Run the collector at **≤8 req/s** through the shared limiter (~120 ms spacing), exponential backoff on 429.
- **CIK format:** zero-padded to 10 digits, prefixed `CIK` in data.sec.gov URLs.

### Endpoints used

| Purpose | Endpoint |
|---|---|
| Ticker → CIK map (resolve once, cache) | `https://www.sec.gov/files/company_tickers.json` |
| Company submissions (recent filings list) | `https://data.sec.gov/submissions/CIK##########.json` |
| Filing primary doc / exhibits | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primaryDocument}` |
| Full-text search (2001–present) | `https://efts.sec.gov/LATEST/search-index?q="phrase"&forms=8-K&startdt=&enddt=` |
| Company facts (XBRL financials, optional) | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` |

> **Do not guess a filing's `primaryDocument` name** — read it from the submissions metadata. If absent, skip and log.

> **Bulk option:** for the 12–18 month baseline backfill, prefer the SEC bulk data downloads (`sec.gov/dera/data`) over thousands of per-filing calls.

---

## Form → signal map (what to extract from each)

| Form | Why it matters | Target sections |
|---|---|---|
| **8-K** | Timeliest event source | Item 1.01 (material agreement / M&A), 2.01 (acquisition completed), 5.02 (exec change → leadership/hiring signal), 7.01 / 8.01 (Reg FD / other — product & strategy announcements); **EX-99.1** earnings release, **EX-99.2** shareholder letter (Coinbase/Robinhood especially roadmap-rich) |
| **10-Q / 10-K** | Strategic direction + traction | MD&A, Business section (new product lines), Risk Factors (sometimes names competitors), segment revenue (traction proxy) |
| **DEF 14A** | Strategy via incentives | Exec-comp metrics tied to strategic goals |
| **S-1 / F-1** | One-time intelligence windfall | Whole document — business, strategy, risk, financials |
| **20-F / 6-K** (Futu) | FPI equivalents of 10-K / 8-K | Same targets, different structure |

Convergence keywords to run through **full-text search** across all filers (feed `convergence_flag` candidates): `prediction market`, `event contract`, `perpetual futures`, `crypto derivatives`, `options on futures`, plus each competitor name in others' risk factors.

---

## Collection flow

```
1. Load config: competitors + forms + lookback window + user-agent + rate limit.
2. Resolve CIKs from company_tickers.json (cache; refresh weekly).
3. For each in-scope competitor:
   a. GET submissions JSON.
   b. Filter recent filings to target forms AND accepted_date > surface.last_checked.
   c. For each new filing:
      - Fetch primary document; for 8-K, also fetch EX-99.x exhibits.
      - Extract & clean text (HTML/inline-XBRL → text).
      - LLM extraction pass → propose candidate developments, each with a
        VERBATIM excerpt + the section it came from.
      - For each candidate: verify the excerpt is a substring of the fetched
        text (reject if not — anti-hallucination gate).
      - Emit a `sighting` per verified candidate.
   d. Update surface.last_checked.
4. (Optional daily mode) Run efts full-text search for convergence keywords
   since yesterday → emit sightings for hits.
5. All calls through the shared ≤8 req/s limiter with 429 backoff.
```

### Sighting output (conforms to `schema.md`)

```json
{
  "competitor_id": "coinbase",
  "run_id": "2026-07-monthly",
  "surface": "edgar",
  "source_url": "https://www.sec.gov/Archives/edgar/data/1679788/000167978825000123/ex99-1.htm",
  "observed_at": "2026-07-24",           // filing/period date
  "title": "8-K EX-99.1 — Q2 shareholder letter references derivatives expansion",
  "raw_excerpt": "<verbatim passage, substring-verified against the source>",
  "content_hash": "<sha256 of normalized excerpt>",
  "embedding": "<vector>"
}
```

The collector stops here — well-sourced sightings, `event_id` null. Clustering (`cluster.py`) and scoring (`score.py` + `narrate.py`) are downstream and out of this spec.

---

## Extraction pass (the one place the LLM is used here)

- **Role:** propose candidate developments and pull the exact supporting passage. Nothing more — no scoring, no impact judgment.
- **Prompt contract:** return JSON only — a list of `{title, category_guess, verbatim_excerpt, section}`. Instruct it to quote verbatim and to return an empty list if the filing is routine boilerplate with no product/strategy/traction signal.
- **Hard verification:** after the model responds, confirm each `verbatim_excerpt` is a literal substring of the cleaned source text. Drop any that aren't. This is code, not trust.
- **Chunking:** long 10-K/20-F documents exceed context — chunk by section and extract per chunk, then de-dupe candidates by `content_hash`.

---

## Configuration (`config/settings.yaml` + `competitors.yaml`)

```yaml
edgar:
  user_agent: "One Lucky Dog research@oneluckydog.com"
  max_rps: 8
  backoff_seconds: [1, 2, 4, 8]
  lookback_days_first_run: 540        # ~18 months for baseline
  forms_domestic: [8-K, 10-Q, 10-K, DEF 14A, S-1, S-3]
  forms_fpi: [20-F, 6-K, F-1]
  convergence_queries:
    - "prediction market"
    - "event contract"
    - "perpetual futures"
    - "crypto derivatives"
```

CIKs are resolved at runtime from `company_tickers.json` — **do not hardcode CIK numbers** (they're easy to get wrong; resolve and cache).

---

## Scheduling

- **Monthly run** (all in-scope competitors, all target forms) → feeds the digest.
- **Optional daily 8-K + full-text sweep** for timely, high-signal filings (S-1 filings, M&A 8-Ks, convergence-keyword hits). These are exactly the items that should trip the always-on alert, so catching them daily rather than monthly is worth the small extra cost. Both modes share the same code path with a different date window.

---

## Error handling & idempotency

- **403** → User-Agent problem; fail fast with a clear message (don't retry blindly).
- **429** → back off per `backoff_seconds`, then resume; never bypass the limiter.
- **Missing `primaryDocument`** → skip filing, log, continue.
- **Re-runs** → `content_hash` + the `UNIQUE(competitor_id, surface, content_hash)` constraint make duplicate inserts no-ops.
- Every run writes a `run` row (start/finish/status/sources) for auditability and delta computation.

---

## Compliance note

EDGAR is public, statutory data accessed through the SEC's own official API within its published fair-access limits. No scraping, no ToS gray area, no compliance gate — which is exactly why it's the first collector. (Contrast: any future social/scraping collector needs CCO sign-off before it's built.)

---

## Definition of done

1. Resolves all in-scope CIKs from `company_tickers.json`.
2. Pulls and filters filings per competitor since `last_checked`, honoring the ≤8 req/s limiter with working 429 backoff and the configured User-Agent.
3. Extracts candidate developments with **substring-verified** verbatim excerpts; zero unsourced or unverifiable excerpts reach the store.
4. Emits schema-conformant `sighting` rows (with `source_url`, `content_hash`, embedding) and updates `last_checked`.
5. Handles Futu's 20-F/6-K forms as well as domestic forms.
6. Idempotent across re-runs; writes a `run` row each execution.
7. Unit tests against saved fixtures in `/tests/fixtures` (at least one 8-K with an EX-99.1, one 10-Q, one 20-F), including a test that a deliberately hallucinated excerpt is rejected.
