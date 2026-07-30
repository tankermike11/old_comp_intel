"""Static internal site generator (docs/OLD_CI_System_Build_Roadmap.md, Phase 4).

Regenerates a set of static HTML files from the event store: a scored-event
feed, a convergence tracker, and one profile page per competitor. Pure reads —
imports only db.queries, never db.store — so generating the site can never
mutate data.

No server, no live backend: per CLAUDE.md ("you build it, you don't host it"),
this is meant to be republished behind whatever internal auth gate you choose
(SSO, a reverse-proxy with basic auth, a private bucket) — auth itself is an
explicitly open decision in roadmap.md ("Site auth: SSO vs. simple internal
gate") and is not decided or built here.

Run: python -m surfaces.site [--out surfaces/site/dist]
"""
import argparse
import html
import json
from pathlib import Path

from config import db_path, get_competitors
from db.init_db import connect
from db.queries import (
    latest_run,
    list_competitors,
    list_current_events,
    list_unscored_events,
    sightings_for_event,
)

DEFAULT_OUT_DIR = Path(__file__).parent / "site" / "dist"

ACTION_LABELS = {
    "PRIORITIZE": "Prioritize",
    "ACT_SOON": "Act Soon",
    "COUNTER_POSITION": "Counter-Position",
    "MONITOR": "Monitor",
    "TRACK": "Track",
    "WEDGE_WATCH": "Wedge Watch",
    "NOTE": "Note",
    "LOG": "Log",
    "LOG_ONLY": "Log Only",
}

ACTION_CSS_CLASS = {
    "PRIORITIZE": "action-priority",
    "ACT_SOON": "action-soon",
    "COUNTER_POSITION": "action-counter",
    "WEDGE_WATCH": "action-wedge",
    "MONITOR": "action-monitor",
    "TRACK": "action-track",
    "NOTE": "action-quiet",
    "LOG": "action-quiet",
    "LOG_ONLY": "action-quiet",
}


def e(value):
    """HTML-escape, treating None as empty string."""
    return html.escape("" if value is None else str(value))


# --- shared page chrome ---------------------------------------------------------------

def _page(title, active_nav, body_html, base_path="."):
    nav_items = [("index.html", "Feed"), ("convergence.html", "Convergence"), ("competitors.html", "Competitors")]
    nav_html = "\n".join(
        f'<a href="{base_path}/{href}" class="{"active" if href == active_nav else ""}">{label}</a>'
        for href, label in nav_items
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{e(title)} — One Lucky Dog CI</title>
<link rel="stylesheet" href="{base_path}/assets/style.css"/>
</head>
<body>
<header class="site-header">
  <div class="brand">One Lucky Dog <span>Competitive Intelligence</span></div>
  <nav>{nav_html}</nav>
</header>
<main>
{body_html}
</main>
<footer class="site-footer">Static regeneration — not connected to a live backend. Wrap this output behind your own internal auth gate before sharing it.</footer>
</body>
</html>
"""


def _bucket_class(bucket):
    return {
        "Very High": "bucket-veryhigh", "High": "bucket-high", "Moderate": "bucket-moderate",
        "Low": "bucket-low", "Negligible": "bucket-negligible",
    }.get(bucket, "")


def _event_card(ev, sightings, base_path="."):
    action = ev["action"]
    action_label = ACTION_LABELS.get(action, action)
    action_class = ACTION_CSS_CLASS.get(action, "")
    convergence_badge = '<span class="badge badge-convergence">Convergence</span>' if ev["convergence_flag"] else ""
    cco_badge = '<span class="badge badge-cco">CCO review required</span>' if ev["requires_cco_review"] else ""

    evidence = {}
    if ev.get("dimension_evidence"):
        try:
            evidence = json.loads(ev["dimension_evidence"])
        except (TypeError, json.JSONDecodeError):
            evidence = {}

    evidence_html = "".join(
        f"<dt>{e(dim)}</dt><dd>&ldquo;{e(quote)}&rdquo;</dd>" for dim, quote in evidence.items()
    )

    sightings_html = "".join(
        f'<li><a href="{e(s["source_url"])}" target="_blank" rel="noopener">{e(s["title"] or s["source_url"])}</a> '
        f'<span class="muted">({e(s["surface"])}, {e(s["observed_at"])})</span></li>'
        for s in sightings
    )

    competitor_link = f'{base_path}/competitors/{e(ev["competitor_id"])}.html'

    return f"""
<article class="event-card {action_class}">
  <div class="event-card-header">
    <span class="action-badge {action_class}">{e(action_label)}</span>
    {convergence_badge}{cco_badge}
    <span class="headline-score">Headline {e(ev["headline_score"])}</span>
  </div>
  <h3>{e(ev["title"])}</h3>
  <div class="event-meta">
    <a href="{competitor_link}">{e(ev["competitor_name"])}</a>
    &middot; {e(ev["category"])}
    &middot; {e(ev["pillar"] or "—")}
    &middot; {e(ev["event_date"])}
    &middot; wedge: {e(ev["wedge_direction"])}
  </div>
  <div class="axis-scores">
    <span class="{_bucket_class(ev["industry_bucket"])}">Industry Impact: {e(ev["industry_score"])} ({e(ev["industry_bucket"])})</span>
    <span class="{_bucket_class(ev["relevance_bucket"])}">Relevance to OLD: {e(ev["relevance_score"])} ({e(ev["relevance_bucket"])})</span>
  </div>
  <p class="so-what">{e(ev["so_what"])}</p>
  <details>
    <summary>Evidence &amp; sources ({len(sightings)} sighting(s))</summary>
    <dl class="evidence">{evidence_html}</dl>
    <ul class="sources">{sightings_html}</ul>
  </details>
</article>
"""


def _stat(label, value):
    return f'<div class="stat"><div class="stat-value">{e(value)}</div><div class="stat-label">{e(label)}</div></div>'


# --- page builders ---------------------------------------------------------------------

def build_index_page(conn, run_info):
    events = list_current_events(conn)
    unscored = list_unscored_events(conn)
    priority_count = sum(1 for ev in events if ev["action"] == "PRIORITIZE")
    convergence_count = sum(1 for ev in events if ev["convergence_flag"])

    stats_html = "".join([
        _stat("Scored events", len(events)),
        _stat("Prioritize", priority_count),
        _stat("Convergence signals", convergence_count),
        _stat("Pending review", len(unscored)),
    ])

    run_line = ""
    if run_info:
        run_line = f'<p class="muted">Last run: {e(run_info["id"])} ({e(run_info["status"])}, started {e(run_info["started_at"])})</p>'

    cards_html = "".join(_event_card(ev, sightings_for_event(conn, ev["id"])) for ev in events)
    if not events:
        cards_html = '<p class="empty">No scored events yet — run the collector and analysis pass first.</p>'

    unscored_html = ""
    if unscored:
        rows = "".join(
            f'<li>{e(u["title"])} <span class="muted">({e(u["competitor_id"])}, {e(u["event_date"])})</span></li>'
            for u in unscored
        )
        unscored_html = f"""
<section class="pending">
  <h2>Pending review ({len(unscored)})</h2>
  <p class="muted">Clustered but not yet scored — narration failed validation or hasn't run.</p>
  <ul>{rows}</ul>
</section>
"""

    body = f"""
<h1>Scored Event Feed</h1>
{run_line}
<div class="stats">{stats_html}</div>
{cards_html}
{unscored_html}
"""
    return _page("Scored Event Feed", "index.html", body)


def build_convergence_page(conn):
    events = list_current_events(conn, convergence_only=True)
    cards_html = "".join(_event_card(ev, sightings_for_event(conn, ev["id"])) for ev in events)
    if not events:
        cards_html = '<p class="empty">No convergence signals yet.</p>'
    body = f"""
<h1>Convergence Tracker</h1>
<p class="muted">Fires when a watched competitor adds, acquires, or materially expands one of the other two pillars (options / crypto / prediction).</p>
{cards_html}
"""
    return _page("Convergence Tracker", "convergence.html", body)


def build_competitors_index_page(conn):
    competitors = list_competitors(conn)
    rows = "".join(
        f'<tr><td><a href="competitors/{e(c["id"])}.html">{e(c["name"])}</a></td>'
        f'<td>{e(c["tier"])}</td><td>{e(c["ownership"])}</td>'
        f'<td>{e(", ".join(json.loads(c["pillars"])))}</td><td>{e(c["cadence"])}</td></tr>'
        for c in competitors
    )
    body = f"""
<h1>Competitors</h1>
<table class="competitor-table">
<thead><tr><th>Name</th><th>Tier</th><th>Ownership</th><th>Pillars</th><th>Cadence</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""
    return _page("Competitors", "competitors.html", body)


def build_competitor_profile_page(conn, competitor):
    events = list_current_events(conn, competitor_id=competitor["id"])
    unscored = list_unscored_events(conn, competitor_id=competitor["id"])
    pillars = ", ".join(json.loads(competitor["pillars"]))
    tickers = ", ".join(json.loads(competitor["tickers"])) if competitor.get("tickers") else "— (private)"

    cards_html = "".join(_event_card(ev, sightings_for_event(conn, ev["id"]), base_path="..") for ev in events)
    if not events:
        cards_html = '<p class="empty">No scored events yet for this competitor.</p>'

    body = f"""
<h1>{e(competitor["name"])}</h1>
<div class="event-meta">
  {e(competitor["tier"])} &middot; {e(competitor["ownership"])} &middot; {e(tickers)}
  &middot; pillars: {e(pillars)} &middot; cadence: {e(competitor["cadence"])}
</div>
<p class="muted">{e(competitor["notes"])}</p>
<h2>Scored events ({len(events)})</h2>
{cards_html}
"""
    return _page(competitor["name"], "competitors.html", body, base_path="..")


STYLE_CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --card-bg: #f8fafc; --border: #e2e8f0;
  --accent: #2563eb;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --card-bg: #171a21; --border: #2a2f3a; --accent: #60a5fa; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font-family: -apple-system, Segoe UI, Roboto, sans-serif; line-height: 1.5; }
main { max-width: 900px; margin: 0 auto; padding: 24px 20px 80px; }
a { color: var(--accent); }
.site-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 24px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 12px; }
.brand { font-weight: 700; }
.brand span { font-weight: 400; color: var(--muted); }
.site-header nav a { margin-left: 16px; text-decoration: none; color: var(--fg); }
.site-header nav a.active { color: var(--accent); font-weight: 600; }
.site-footer { text-align: center; color: var(--muted); font-size: 0.85em; padding: 20px; border-top: 1px solid var(--border); }
.muted { color: var(--muted); font-size: 0.9em; }
.empty { color: var(--muted); font-style: italic; }
.stats { display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0 28px; }
.stat { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; min-width: 120px; }
.stat-value { font-size: 1.6em; font-weight: 700; }
.stat-label { color: var(--muted); font-size: 0.85em; }
.event-card { background: var(--card-bg); border: 1px solid var(--border); border-left-width: 4px; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; }
.event-card h3 { margin: 6px 0; }
.event-card-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.event-meta { color: var(--muted); font-size: 0.9em; margin-bottom: 8px; }
.axis-scores { display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.9em; margin-bottom: 8px; }
.so-what { margin: 8px 0; }
.action-badge { font-size: 0.75em; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 4px; color: #fff; }
.action-priority { background: #dc2626; } .event-card.action-priority { border-left-color: #dc2626; }
.action-soon { background: #ea580c; } .event-card.action-soon { border-left-color: #ea580c; }
.action-counter { background: #7c3aed; } .event-card.action-counter { border-left-color: #7c3aed; }
.action-wedge { background: #db2777; } .event-card.action-wedge { border-left-color: #db2777; }
.action-monitor { background: #2563eb; } .event-card.action-monitor { border-left-color: #2563eb; }
.action-track { background: #0891b2; } .event-card.action-track { border-left-color: #0891b2; }
.action-quiet { background: #6b7280; } .event-card.action-quiet { border-left-color: #6b7280; }
.badge { font-size: 0.75em; padding: 3px 8px; border-radius: 4px; border: 1px solid var(--border); }
.badge-convergence { color: #db2777; border-color: #db2777; }
.badge-cco { color: #dc2626; border-color: #dc2626; }
.headline-score { margin-left: auto; font-weight: 600; }
.bucket-veryhigh { color: #dc2626; } .bucket-high { color: #ea580c; } .bucket-moderate { color: #ca8a04; }
.bucket-low { color: var(--muted); } .bucket-negligible { color: var(--muted); }
details summary { cursor: pointer; color: var(--accent); margin-top: 6px; }
dl.evidence { margin: 10px 0; }
dl.evidence dt { font-weight: 600; text-transform: capitalize; margin-top: 6px; }
dl.evidence dd { margin: 0 0 0 12px; color: var(--muted); font-style: italic; }
ul.sources { margin: 10px 0 0; padding-left: 20px; }
.competitor-table { width: 100%; border-collapse: collapse; margin-top: 16px; }
.competitor-table th, .competitor-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
.pending { margin-top: 32px; padding-top: 16px; border-top: 1px dashed var(--border); }
"""


def write_site(conn, out_dir=DEFAULT_OUT_DIR):
    out_dir = Path(out_dir)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "competitors").mkdir(parents=True, exist_ok=True)

    (out_dir / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")

    run_info = latest_run(conn)
    (out_dir / "index.html").write_text(build_index_page(conn, run_info), encoding="utf-8")
    (out_dir / "convergence.html").write_text(build_convergence_page(conn), encoding="utf-8")
    (out_dir / "competitors.html").write_text(build_competitors_index_page(conn), encoding="utf-8")

    for competitor in list_competitors(conn):
        page = build_competitor_profile_page(conn, competitor)
        (out_dir / "competitors" / f"{competitor['id']}.html").write_text(page, encoding="utf-8")

    return out_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    connection = connect(db_path())
    try:
        written_to = write_site(connection, out_dir=args.out)
        print(f"Site regenerated at {written_to}")
    finally:
        connection.close()
