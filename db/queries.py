"""Read-only queries over the event store, used by the internal site generator
(surfaces/site.py). Kept separate from db/store.py (which run.py uses to write)
so the site's read path can't accidentally mutate the store.
"""


def list_competitors(conn):
    rows = conn.execute(
        "SELECT id, name, tier, ownership, tickers, pillars, cadence, filings_path, notes "
        "FROM competitor ORDER BY name"
    ).fetchall()
    cols = ["id", "name", "tier", "ownership", "tickers", "pillars", "cadence", "filings_path", "notes"]
    return [dict(zip(cols, row)) for row in rows]


_CURRENT_EVENT_COLUMNS = """
    e.id, e.competitor_id, c.name AS competitor_name, e.title, e.category, e.pillar,
    e.event_date, e.status, e.convergence_flag, e.reviewed_by, e.reviewed_at, e.created_run_id,
    a.id AS assessment_id, a.industry_score, a.industry_bucket,
    a.relevance_score, a.relevance_bucket, a.headline_score, a.wedge_direction,
    a.action, a.requires_cco_review, a.so_what, a.dimension_evidence, a.scored_at
"""

_CURRENT_EVENT_FIELDS = [
    "id", "competitor_id", "competitor_name", "title", "category", "pillar",
    "event_date", "status", "convergence_flag", "reviewed_by", "reviewed_at", "created_run_id",
    "assessment_id", "industry_score", "industry_bucket",
    "relevance_score", "relevance_bucket", "headline_score", "wedge_direction",
    "action", "requires_cco_review", "so_what", "dimension_evidence", "scored_at",
]


def list_current_events(conn, competitor_id=None, convergence_only=False):
    """Events that have a current (scored) assessment, newest headline first."""
    query = f"""
        SELECT {_CURRENT_EVENT_COLUMNS}
        FROM event e
        JOIN competitor c ON c.id = e.competitor_id
        JOIN assessment a ON a.id = e.current_assessment_id
        WHERE e.current_assessment_id IS NOT NULL
    """
    params = []
    if competitor_id:
        query += " AND e.competitor_id = ?"
        params.append(competitor_id)
    if convergence_only:
        query += " AND e.convergence_flag = 1"
    query += " ORDER BY a.headline_score DESC, e.event_date DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(zip(_CURRENT_EVENT_FIELDS, row)) for row in rows]


def list_events_for_run_digest(conn, run):
    """Events belonging to one run's digest (the brief/deck delta): events
    whose CURRENT assessment was scored during this run's execution window.

    Deliberately NOT filtered by event.created_run_id. pipeline/analyze.py
    retries any previously-unscored event on every subsequent run (a
    narration failure — e.g. a live model wrapping JSON in a markdown fence —
    is retried, not permanent), so an event first clustered in an earlier run
    but only successfully scored in THIS run must show up in THIS run's
    digest, not the one that first clustered it (which had no assessment at
    the time) and not be silently invisible forever. An event created and
    scored in the same run is naturally captured too, since analysis always
    runs after collection and before the run is marked finished — its
    scored_at necessarily falls inside its own run's window.

    `run`: a dict from get_run/latest_run (needs id, started_at, finished_at).
    """
    query = f"""
        SELECT {_CURRENT_EVENT_COLUMNS}
        FROM event e
        JOIN competitor c ON c.id = e.competitor_id
        JOIN assessment a ON a.id = e.current_assessment_id
        WHERE e.current_assessment_id IS NOT NULL
          AND a.scored_at BETWEEN :started_at AND :finished_at
        ORDER BY a.headline_score DESC, e.event_date DESC
    """
    params = {
        "started_at": run["started_at"],
        "finished_at": run["finished_at"] or run["started_at"],
    }
    rows = conn.execute(query, params).fetchall()
    return [dict(zip(_CURRENT_EVENT_FIELDS, row)) for row in rows]


def list_unscored_events(conn, competitor_id=None):
    """Clustered events with no current assessment yet — pending or failed
    narration. Surfaced explicitly rather than silently hidden.
    """
    query = (
        "SELECT id, competitor_id, title, category, event_date, status, created_run_id "
        "FROM event WHERE current_assessment_id IS NULL"
    )
    params = []
    if competitor_id:
        query += " AND competitor_id = ?"
        params.append(competitor_id)
    query += " ORDER BY event_date DESC"
    rows = conn.execute(query, params).fetchall()
    cols = ["id", "competitor_id", "title", "category", "event_date", "status", "created_run_id"]
    return [dict(zip(cols, row)) for row in rows]


def sightings_for_event(conn, event_id):
    rows = conn.execute(
        "SELECT surface, source_url, observed_at, title, raw_excerpt FROM sighting WHERE event_id = ? "
        "ORDER BY observed_at",
        (event_id,),
    ).fetchall()
    cols = ["surface", "source_url", "observed_at", "title", "raw_excerpt"]
    return [dict(zip(cols, row)) for row in rows]


def latest_run(conn):
    row = conn.execute(
        "SELECT id, type, started_at, finished_at, status FROM run ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "type", "started_at", "finished_at", "status"], row))


def get_run(conn, run_id):
    row = conn.execute(
        "SELECT id, type, started_at, finished_at, status FROM run WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "type", "started_at", "finished_at", "status"], row))
