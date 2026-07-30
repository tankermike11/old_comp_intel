"""Sighting -> event clustering (docs/OLD_CI_System_Build_Roadmap.md, Phase 2).

No embedding model is wired up yet — schema.md's sqlite-vec path is reserved for
that once one is chosen — so v1 clustering uses a deterministic text-similarity
heuristic over each sighting's title + raw_excerpt, scoped per competitor within
a single run. This is the simplest thing that dedupes "the primary 8-K and its
EX-99.1 both describe the same launch" without inventing an embedding pipeline
that wasn't asked for. Swap in sqlite-vec cosine similarity later by replacing
group_by_similarity's body — callers don't need to change.

Category is a schema-required NOT NULL field on `event`, but this module only
groups sightings — it doesn't read or judge their content, so it writes a
placeholder category. narrate.py proposes the real category (validated against
the vocab) once it actually reads the cluster's evidence; the analysis pass
updates the event row with that proposal.
"""
import re
import uuid

DEFAULT_SIMILARITY_THRESHOLD = 0.35
PLACEHOLDER_CATEGORY = "other"


def _tokenize(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def jaccard_similarity(a_tokens, b_tokens):
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _fetch_unclustered_sightings(conn, run_id):
    rows = conn.execute(
        "SELECT id, competitor_id, title, raw_excerpt, observed_at, surface "
        "FROM sighting WHERE run_id = ? AND event_id IS NULL",
        (run_id,),
    ).fetchall()
    return [
        {
            "id": r[0], "competitor_id": r[1], "title": r[2],
            "raw_excerpt": r[3], "observed_at": r[4], "surface": r[5],
        }
        for r in rows
    ]


def group_by_similarity(sightings, threshold=DEFAULT_SIMILARITY_THRESHOLD):
    """Greedy clustering within ONE competitor's sightings. Returns a list of
    clusters, each a list of sighting dicts. Order-dependent but deterministic
    for a fixed input order.
    """
    tokens = [_tokenize(f"{s['title']} {s['raw_excerpt']}") for s in sightings]
    assigned = [False] * len(sightings)
    clusters = []
    for i in range(len(sightings)):
        if assigned[i]:
            continue
        cluster = [sightings[i]]
        assigned[i] = True
        for j in range(i + 1, len(sightings)):
            if assigned[j]:
                continue
            if jaccard_similarity(tokens[i], tokens[j]) >= threshold:
                cluster.append(sightings[j])
                assigned[j] = True
        clusters.append(cluster)
    return clusters


def _representative_title(cluster):
    return max((s["title"] or "" for s in cluster), key=len)


def cluster_sightings_into_events(conn, run_id, threshold=DEFAULT_SIMILARITY_THRESHOLD):
    """Groups this run's unclustered sightings (event_id IS NULL) into events,
    one competitor at a time, and sets sighting.event_id. Returns the list of
    newly created event ids.
    """
    sightings = _fetch_unclustered_sightings(conn, run_id)
    by_competitor = {}
    for s in sightings:
        by_competitor.setdefault(s["competitor_id"], []).append(s)

    new_event_ids = []
    for competitor_id, group in by_competitor.items():
        for cluster in group_by_similarity(group, threshold):
            event_id = str(uuid.uuid4())
            event_date = min(s["observed_at"] for s in cluster)
            conn.execute(
                "INSERT INTO event (id, competitor_id, title, category, event_date, created_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, competitor_id, _representative_title(cluster), PLACEHOLDER_CATEGORY, event_date, run_id),
            )
            conn.executemany(
                "UPDATE sighting SET event_id = ? WHERE id = ?",
                [(event_id, s["id"]) for s in cluster],
            )
            new_event_ids.append(event_id)
    conn.commit()
    return new_event_ids
