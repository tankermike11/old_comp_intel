-- One Lucky Dog CI — event store DDL. Transcribed from docs/OLD_CI_Event_Store_Schema.md.
-- v1-essential tables plus product_line (Phase 2, added now that clustering/scoring
-- are being built). alert (Phase 5) is still deliberately not created — see schema.md phasing.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS competitor (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  tier          TEXT NOT NULL,
  ownership     TEXT NOT NULL,
  tickers       TEXT,
  pillars       TEXT NOT NULL,
  cadence       TEXT NOT NULL DEFAULT 'monthly',
  filings_path  TEXT,
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS competitor_surface (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  surface       TEXT NOT NULL,
  url           TEXT,
  collector     TEXT,
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_checked  TEXT,
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS run (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT,
  status        TEXT NOT NULL DEFAULT 'running',
  sources       TEXT,
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS product_line (
  id            TEXT PRIMARY KEY,
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  name          TEXT NOT NULL,
  pillar        TEXT,
  launched_at   TEXT,
  status        TEXT DEFAULT 'active',
  notes         TEXT
);

-- event is created before sighting even though sighting is documented first,
-- because sighting.event_id references it; SQLite resolves FK names at use time
-- regardless of declaration order, so this keeps CREATE TABLE statements valid.
CREATE TABLE IF NOT EXISTS event (
  id               TEXT PRIMARY KEY,
  competitor_id    TEXT NOT NULL REFERENCES competitor(id),
  product_line_id  TEXT REFERENCES product_line(id),
  title            TEXT NOT NULL,
  category         TEXT NOT NULL,
  pillar           TEXT,
  event_date       TEXT NOT NULL,
  first_seen       TEXT NOT NULL DEFAULT (datetime('now')),
  last_updated     TEXT NOT NULL DEFAULT (datetime('now')),
  confidence       TEXT NOT NULL DEFAULT 'medium',
  status           TEXT NOT NULL DEFAULT 'proposed',
  convergence_flag INTEGER NOT NULL DEFAULT 0,
  current_assessment_id TEXT REFERENCES assessment(id),
  reviewed_by      TEXT,
  reviewed_at      TEXT,
  created_run_id   TEXT REFERENCES run(id)
);

CREATE TABLE IF NOT EXISTS sighting (
  id            TEXT PRIMARY KEY,
  competitor_id TEXT NOT NULL REFERENCES competitor(id),
  run_id        TEXT NOT NULL REFERENCES run(id),
  event_id      TEXT REFERENCES event(id),
  surface       TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  observed_at   TEXT NOT NULL,
  collected_at  TEXT NOT NULL DEFAULT (datetime('now')),
  title         TEXT,
  raw_excerpt   TEXT,
  content_hash  TEXT,
  embedding     BLOB,
  UNIQUE(competitor_id, surface, content_hash)
);

CREATE TABLE IF NOT EXISTS assessment (
  id                TEXT PRIMARY KEY,
  event_id          TEXT NOT NULL REFERENCES event(id),
  rubric_version    TEXT NOT NULL,
  model_version     TEXT,
  scored_at         TEXT NOT NULL DEFAULT (datetime('now')),
  is_current        INTEGER NOT NULL DEFAULT 1,

  a_novelty         INTEGER, a_reach INTEGER, a_revenue INTEGER,
  a_defensibility   INTEGER, a_regulatory INTEGER,
  industry_score    INTEGER,
  industry_bucket   TEXT,

  b_pillar          INTEGER, b_audience INTEGER, b_wedge INTEGER,
  b_convergence     INTEGER, b_time_to_impact INTEGER,
  relevance_score   INTEGER,
  relevance_bucket  TEXT,

  headline_score    INTEGER,
  wedge_direction   TEXT,
  action            TEXT,
  requires_cco_review INTEGER NOT NULL DEFAULT 0,
  so_what           TEXT,
  dimension_evidence TEXT
);
