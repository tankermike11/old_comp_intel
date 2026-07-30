# One Lucky Dog — CI Event Store Schema (v1 draft)

*Working document and build spec. The backbone of the CI system — every downstream surface (brief, site, alerts) is a query over these tables. Written as SQLite DDL because that's the recommended starting store and it drops straight into Claude Code. Ports to Postgres with trivial type changes.*

---

## The one decision that shapes everything: sightings vs. events

The most important modeling choice here is separating two things people usually conflate:

- A **sighting** is a *raw observation on one surface* — an app-store release-note line, an 8-K item, a blog post, a pricing-page diff. It's append-only, never edited, and always carries a source URL. This is your provenance and audit layer.
- An **event** is a *deduplicated logical development* — "Coinbase launched crypto options in the US." One event is supported by one or more sightings (the blog + the release note + the tweet that all describe the same launch).

This split gives you three things for free:
1. **Dedup** becomes "cluster N sightings into one event" instead of a messy after-the-fact filter.
2. **Provenance** is structural: an event's evidence *is* its set of sightings, each with a mandatory `source_url`. An event with zero sightings is invalid by construction — that's your anti-hallucination rule enforced at the schema layer, not by prompt discipline.
3. **Scoring** attaches to the event (the logical thing), while the raw text stays immutable in the sightings.

```
competitor ──< competitor_surface        (what to monitor)
     │
     ├──< product_line ──< event          (the "story over time" spine)
     │                      │
     │                      ├──< sighting  (raw, source-cited, append-only)
     │                      ├──< assessment (versioned rubric scores)
     │                      └──< alert      (fired notifications)
     │
run ──< sighting                           (every observation stamped to a run → deltas)
```

---

## Tables

### `competitor` — the watchlist, as data
The locked Tier-1 watchlist becomes rows here. Tier and ownership drive cadence and which financial pipeline applies.

```sql
CREATE TABLE competitor (
  id            TEXT PRIMARY KEY,               -- slug: 'robinhood', 'tastytrade'
  name          TEXT NOT NULL,
  tier          TEXT NOT NULL,                  -- tier1 | benchmark | convergence_watch | tier2
  ownership     TEXT NOT NULL,                  -- public | private | pre_ipo
  tickers       TEXT,                           -- JSON array '["HOOD"]'; null if private
  pillars       TEXT NOT NULL,                  -- JSON array: ["options","crypto","prediction","equities_etfs","futures"]
  cadence       TEXT NOT NULL DEFAULT 'monthly',-- monthly | quarterly
  filings_path  TEXT,                           -- 'edgar' | 'lse' | null  (which financial pipeline)
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### `competitor_surface` — what to monitor, per competitor
Feeds the collectors. One row per surface you watch for that competitor.

```sql
CREATE TABLE competitor_surface (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  surface       TEXT NOT NULL,                  -- see surface vocab
  url           TEXT,                           -- page / feed / app id
  collector     TEXT,                           -- which collector handles it
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_checked  TEXT,
  notes         TEXT
);
```

### `product_line` — the spine of the "story over time"
This is what makes component 4 (the diff) work: link events to a product line and `launched_at`, and "the 4th feature on a 6-month-old product" is a single ordered query. Nullable on events, because company-level moves (an acquisition, a firm-wide pricing change) don't belong to one line.

```sql
CREATE TABLE product_line (
  id            TEXT PRIMARY KEY,               -- slug: 'robinhood-prediction-markets'
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  name          TEXT NOT NULL,
  pillar        TEXT,                           -- options | crypto | prediction | ...
  launched_at   TEXT,                           -- anchor date for the story
  status        TEXT DEFAULT 'active',          -- active | sunset
  notes         TEXT
);
```

### `run` — every pipeline execution
Stamping sightings to a run is what enables "what's new since last month" (watchlist deltas) and gives you a clean audit trail.

```sql
CREATE TABLE run (
  id            TEXT PRIMARY KEY,               -- '2026-07-monthly' or uuid
  type          TEXT NOT NULL,                  -- monthly | baseline | convergence_check | adhoc
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT,
  status        TEXT NOT NULL DEFAULT 'running',-- running | complete | failed
  sources       TEXT,                           -- JSON array of surfaces covered
  notes         TEXT
);
```

### `sighting` — raw observations (append-only, source-mandatory)
The immutable evidence layer. `source_url` is `NOT NULL` on purpose — that's the anti-hallucination rule as a constraint. `content_hash` dedupes identical re-observations across runs; `embedding` powers semantic clustering and site search.

```sql
CREATE TABLE sighting (
  id            TEXT PRIMARY KEY,               -- uuid
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  run_id        TEXT NOT NULL REFERENCES run(id),
  event_id      TEXT REFERENCES event(id),      -- null until clustered into an event
  surface       TEXT NOT NULL,                  -- see surface vocab
  source_url    TEXT NOT NULL,                  -- never null: no source, no sighting
  observed_at   TEXT NOT NULL,                  -- the date the source itself carries
  collected_at  TEXT NOT NULL DEFAULT (datetime('now')),
  title         TEXT,
  raw_excerpt   TEXT,                           -- extracted text, verbatim
  content_hash  TEXT,                           -- identical-content dedupe
  embedding     BLOB,                           -- vector for clustering + search
  UNIQUE(competitor_id, surface, content_hash)
);
```

### `event` — deduplicated logical developments
The unit of intelligence. Carries category/pillar/date, the human-review state, the convergence flag, and a pointer to its current score. Raw text lives in its sightings, not here.

```sql
CREATE TABLE event (
  id               TEXT PRIMARY KEY,            -- uuid
  competitor_id    TEXT NOT NULL REFERENCES competitor(id),
  product_line_id  TEXT REFERENCES product_line(id),   -- null for company-level moves
  title            TEXT NOT NULL,               -- one-line factual summary
  category         TEXT NOT NULL,               -- see category vocab
  pillar           TEXT,                        -- asset class touched
  event_date       TEXT NOT NULL,               -- when the development happened
  first_seen       TEXT NOT NULL DEFAULT (datetime('now')),
  last_updated     TEXT NOT NULL DEFAULT (datetime('now')),
  confidence       TEXT NOT NULL DEFAULT 'medium', -- high | medium | low
  status           TEXT NOT NULL DEFAULT 'proposed', -- proposed | confirmed | dismissed | superseded
  convergence_flag INTEGER NOT NULL DEFAULT 0,
  current_assessment_id TEXT REFERENCES assessment(id),
  reviewed_by      TEXT,                        -- CCO/product adjudication
  reviewed_at      TEXT,
  created_run_id   TEXT REFERENCES run(id)      -- the run that first surfaced it → deltas
);
```

### `assessment` — versioned rubric output
Scores are **historized, not overwritten**. When you tune the rubric or change models, you re-score into a new row and flip `is_current` — which is exactly what the golden-set drift check needs (compare assessments across `rubric_version`). Mirrors the rubric's JSON output object field-for-field.

```sql
CREATE TABLE assessment (
  id                TEXT PRIMARY KEY,           -- uuid
  event_id          TEXT NOT NULL REFERENCES event(id),
  rubric_version    TEXT NOT NULL,              -- 'v1'
  model_version     TEXT,
  scored_at         TEXT NOT NULL DEFAULT (datetime('now')),
  is_current        INTEGER NOT NULL DEFAULT 1,

  -- Axis A: Industry Impact
  a_novelty         INTEGER, a_reach INTEGER, a_revenue INTEGER,
  a_defensibility   INTEGER, a_regulatory INTEGER,
  industry_score    INTEGER,                    -- 0-100
  industry_bucket   TEXT,

  -- Axis B: Relevance to OLD
  b_pillar          INTEGER, b_audience INTEGER, b_wedge INTEGER,
  b_convergence     INTEGER, b_time_to_impact INTEGER,
  relevance_score   INTEGER,                    -- 0-100
  relevance_bucket  TEXT,

  headline_score    INTEGER,                    -- max(industry, relevance)
  wedge_direction   TEXT,                       -- reinforces | validates | dilutes | threatens | neutral
  action            TEXT,                       -- see action vocab
  requires_cco_review INTEGER NOT NULL DEFAULT 0,
  so_what           TEXT,                       -- narration
  dimension_evidence TEXT                       -- JSON: per-dimension cited justification
);
```

### `alert` — fired notifications (Phase 5)
Lightweight; exists so the notification layer doesn't re-fire and so alerts can be acknowledged. Defer until you build notifications.

```sql
CREATE TABLE alert (
  id              TEXT PRIMARY KEY,             -- uuid
  event_id        TEXT NOT NULL REFERENCES event(id),
  trigger         TEXT NOT NULL,                -- convergence | priority | s1_filing | threshold
  fired_at        TEXT NOT NULL DEFAULT (datetime('now')),
  channel         TEXT,                         -- slack | email | webhook
  acknowledged    INTEGER NOT NULL DEFAULT 0,
  acknowledged_by TEXT
);
```

---

## Controlled vocabularies (keep these centralized in code)

- **surface:** `edgar` · `app_store_ios` · `app_store_android` · `pricing_page` · `cftc` · `press_blog` · `social` · `careers` · `earnings_call` · `other`
- **category:** `feature_launch` · `product_launch` · `pricing_change` · `acquisition_ma` · `regulatory_filing` · `partnership` · `hiring_signal` · `content_education` · `platform_infra` · `other`
- **pillar:** `options` · `crypto` · `prediction` · `equities_etfs` · `futures` · `multi` · `other`
- **action:** `PRIORITIZE` · `ACT_SOON` · `COUNTER_POSITION` · `MONITOR` · `TRACK` · `WEDGE_WATCH` · `NOTE` · `LOG` · `LOG_ONLY`
- **status:** `proposed` · `confirmed` · `dismissed` · `superseded`

---

## How the schema delivers each capability

- **Dedup / cluster-merge:** insert sightings with `event_id` null → clustering step (embedding similarity) creates events and sets `sighting.event_id`. Many sightings, one event.
- **The diff / story over time (component 4):** `SELECT * FROM event WHERE product_line_id = ? ORDER BY event_date` — the feature-accumulation timeline, anchored by `product_line.launched_at`.
- **Convergence alert:** `event.convergence_flag = 1` (set when Axis-B convergence scores 5) → fires and lands in `alert`.
- **Deltas between runs:** `event.created_run_id = <current run>` gives "new since last month"; status changes are also run-stamped.
- **Anti-hallucination:** enforced structurally — events exist only via sightings, and `sighting.source_url` is `NOT NULL`.
- **Drift detection:** re-score into a new `assessment` row; compare golden-set events across `rubric_version`.
- **The three surfaces**, all as queries over this store:
  - *Brief:* events where `status='confirmed'` and `created_run_id=<run>`, ordered by `headline_score`, grouped by `action`.
  - *Site:* competitor profiles (`competitor` + its events), product-line timelines, a scored feed, and search over `sighting.embedding`.
  - *Notifications:* events crossing a trigger → `alert`.

---

## Embeddings / vector search

`sighting.embedding` is stored as a BLOB. For similarity (clustering + search) either add the **`sqlite-vec`** extension (keeps everything in one SQLite file — simplest, recommended to start) or keep a FAISS sidecar index keyed by `sighting.id` if you outgrow it.

---

## Phasing (don't build it all at once)

- **v1 essential (Phase 0–1):** `competitor`, `competitor_surface`, `run`, `sighting`, `event`, `assessment`.
- **Add in Phase 2:** `product_line` (needed once the diff engine comes online).
- **Add in Phase 5:** `alert`.

---

## Flagged decisions

1. **Sighting→event cardinality.** Modeled one-to-many (FK on sighting). If a single sighting ever describes *two* developments (e.g., a blog post announcing two features), you'd need a many-to-many join table instead. Deferred as a v1 simplification — revisit if it happens in practice.
2. **Embeddings in-DB vs. sidecar.** `sqlite-vec` (recommended to start) vs. FAISS sidecar.
3. **IDs.** Slugs for stable entities (`competitor`, `product_line`), UUIDs for transactional rows (`sighting`, `event`, `assessment`). Confirm you're happy with that split.
4. **JSON-in-TEXT** for `pillars`, `tickers`, `dimension_evidence`. Fine in SQLite; becomes native `jsonb` if you move to Postgres.
5. **Dates** as ISO-8601 UTC text throughout. Confirm before data lands, since it's painful to change later.
6. **Assessment history retention** — keep every historical `assessment` forever (recommended; cheap and gives full drift/audit history) vs. prune.
