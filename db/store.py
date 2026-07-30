"""Thin persistence helpers over the event store used by run.py. Sightings are
inserted idempotently — the sighting UNIQUE(competitor_id, surface, content_hash)
constraint makes a re-run's duplicate inserts no-ops (schema.md, edgar_collector_spec.md).
"""
import sqlite3


def create_run(conn, run_id, run_type, sources=None):
    conn.execute(
        "INSERT INTO run (id, type, sources) VALUES (?, ?, ?)",
        (run_id, run_type, sources),
    )
    conn.commit()


def finish_run(conn, run_id, status="complete"):
    conn.execute(
        "UPDATE run SET status = ?, finished_at = datetime('now') WHERE id = ?",
        (status, run_id),
    )
    conn.commit()


def get_or_create_surface(conn, competitor_id, surface, collector=None):
    row = conn.execute(
        "SELECT id, last_checked FROM competitor_surface WHERE competitor_id = ? AND surface = ?",
        (competitor_id, surface),
    ).fetchone()
    if row:
        return {"id": row[0], "last_checked": row[1]}
    cur = conn.execute(
        "INSERT INTO competitor_surface (competitor_id, surface, collector) VALUES (?, ?, ?)",
        (competitor_id, surface, collector),
    )
    conn.commit()
    return {"id": cur.lastrowid, "last_checked": None}


def update_surface_last_checked(conn, surface_id, checked_at):
    conn.execute(
        "UPDATE competitor_surface SET last_checked = ? WHERE id = ?",
        (checked_at, surface_id),
    )
    conn.commit()


def get_event(conn, event_id):
    row = conn.execute(
        "SELECT id, competitor_id, title, category, pillar, event_date, status FROM event WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "competitor_id": row[1], "title": row[2],
        "category": row[3], "pillar": row[4], "event_date": row[5], "status": row[6],
    }


def get_sightings_for_event(conn, event_id):
    rows = conn.execute(
        "SELECT surface, source_url, observed_at, raw_excerpt FROM sighting WHERE event_id = ?",
        (event_id,),
    ).fetchall()
    return [
        {"surface": r[0], "source_url": r[1], "observed_at": r[2], "raw_excerpt": r[3]}
        for r in rows
    ]


def insert_assessment(conn, assessment_id, event_id, rubric_version, model_version, scored):
    """scored: the dict returned by pipeline.score.score_event, plus so_what and
    dimension_evidence (JSON-serialized) merged in by the caller.
    """
    conn.execute(
        """
        INSERT INTO assessment (
          id, event_id, rubric_version, model_version,
          a_novelty, a_reach, a_revenue, a_defensibility, a_regulatory,
          industry_score, industry_bucket,
          b_pillar, b_audience, b_wedge, b_convergence, b_time_to_impact,
          relevance_score, relevance_bucket,
          headline_score, wedge_direction, action, requires_cco_review,
          so_what, dimension_evidence
        ) VALUES (
          :id, :event_id, :rubric_version, :model_version,
          :a_novelty, :a_reach, :a_revenue, :a_defensibility, :a_regulatory,
          :industry_score, :industry_bucket,
          :b_pillar, :b_audience, :b_wedge, :b_convergence, :b_time_to_impact,
          :relevance_score, :relevance_bucket,
          :headline_score, :wedge_direction, :action, :requires_cco_review,
          :so_what, :dimension_evidence
        )
        """,
        {
            "id": assessment_id, "event_id": event_id,
            "rubric_version": rubric_version, "model_version": model_version,
            "a_novelty": scored["industry_dimensions"]["novelty"],
            "a_reach": scored["industry_dimensions"]["reach"],
            "a_revenue": scored["industry_dimensions"]["revenue"],
            "a_defensibility": scored["industry_dimensions"]["defensibility"],
            "a_regulatory": scored["industry_dimensions"]["regulatory"],
            "industry_score": scored["industry_score"], "industry_bucket": scored["industry_bucket"],
            "b_pillar": scored["relevance_dimensions"]["pillar"],
            "b_audience": scored["relevance_dimensions"]["audience"],
            "b_wedge": scored["relevance_dimensions"]["wedge"],
            "b_convergence": scored["relevance_dimensions"]["convergence"],
            "b_time_to_impact": scored["relevance_dimensions"]["time_to_impact"],
            "relevance_score": scored["relevance_score"], "relevance_bucket": scored["relevance_bucket"],
            "headline_score": scored["headline_score"], "wedge_direction": scored["wedge_direction"],
            "action": scored["action"], "requires_cco_review": int(scored["requires_cco_review"]),
            "so_what": scored["so_what"], "dimension_evidence": scored["dimension_evidence"],
        },
    )
    conn.commit()


def update_event_after_assessment(conn, event_id, category, pillar, confidence, convergence_flag, assessment_id):
    conn.execute(
        """
        UPDATE event SET
          category = ?, pillar = ?, confidence = ?, convergence_flag = ?,
          current_assessment_id = ?, last_updated = datetime('now')
        WHERE id = ?
        """,
        (category, pillar, confidence, int(convergence_flag), assessment_id, event_id),
    )
    conn.commit()


def insert_sighting(conn, sighting):
    """Returns True if a new row was written, False if it was a dedupe no-op."""
    try:
        conn.execute(
            """
            INSERT INTO sighting
              (id, competitor_id, run_id, event_id, surface, source_url, observed_at, title, raw_excerpt, content_hash, embedding)
            VALUES (:id, :competitor_id, :run_id, :event_id, :surface, :source_url, :observed_at, :title, :raw_excerpt, :content_hash, :embedding)
            """,
            sighting,
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
