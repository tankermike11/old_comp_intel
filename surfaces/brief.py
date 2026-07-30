"""Monthly brief generator (docs/OLD_CI_System_Build_Roadmap.md, Phase 3).

One command -> a Markdown digest of one run's new developments, grouped by
action (most urgent first), with the "so what" line and cited sources per
event, straight from the store. Pure reads (db.queries only) — generating a
brief can never mutate data.

This is the run's *delta* — events first clustered in this run, OR retried
and successfully scored during this run (see
db.queries.list_events_for_run_digest) — distinct from the internal site's
index page, which is a living view over ALL current scored events regardless
of when they were first seen.

Run: python -m surfaces.brief [--run-id RUN_ID] [--out path/to/brief.md]
"""
import argparse
import json
from pathlib import Path

from config import db_path
from db.init_db import connect
from db.queries import get_run, latest_run, list_events_for_run_digest, list_unscored_events, sightings_for_event
from surfaces.brand import ACTION_LABELS, ACTION_ORDER, PUBLIC_BRAND, TAGLINE_PRIMARY

DEFAULT_OUT_PATH = Path(__file__).parent / "brief" / "brief.md"


def _event_section(ev, sightings):
    lines = [
        f"### {ev['title']} — {ev['competitor_name']} (Headline {ev['headline_score']})",
        "",
        f"Industry Impact: **{ev['industry_score']}** ({ev['industry_bucket']}) &middot; "
        f"Relevance to OLD: **{ev['relevance_score']}** ({ev['relevance_bucket']}) &middot; "
        f"Wedge: {ev['wedge_direction']}"
        + (" &middot; **Convergence signal**" if ev["convergence_flag"] else "")
        + (" &middot; **Requires CCO review**" if ev["requires_cco_review"] else ""),
        "",
        f"> {ev['so_what']}" if ev["so_what"] else "> _(no narration available)_",
        "",
    ]
    if sightings:
        lines.append("**Sources:**")
        for s in sightings:
            label = s["title"] or s["source_url"]
            lines.append(f"- [{label}]({s['source_url']}) ({s['surface']}, {s['observed_at']})")
        lines.append("")
    return "\n".join(lines)


def generate_brief_markdown(conn, run_id=None):
    run = get_run(conn, run_id) if run_id else latest_run(conn)
    if run is None:
        return f"# {PUBLIC_BRAND} — Monthly Competitive Intelligence Brief\n\nNo runs recorded yet.\n"

    all_events = list_events_for_run_digest(conn, run)
    pending = [ev for ev in list_unscored_events(conn) if ev["created_run_id"] == run["id"]]
    by_action = {}
    for ev in all_events:
        by_action.setdefault(ev["action"], []).append(ev)

    convergence_events = [ev for ev in all_events if ev["convergence_flag"]]

    lines = [
        f"# {PUBLIC_BRAND} — Monthly Competitive Intelligence Brief",
        f"*{TAGLINE_PRIMARY}*",
        "",
        f"**Run:** {run['id']} ({run['type']}, {run['status']}) &middot; started {run['started_at']}",
        "",
        f"**Summary:** {len(all_events)} scored event(s) &middot; "
        f"{len(by_action.get('PRIORITIZE', []))} Prioritize &middot; "
        f"{len(convergence_events)} convergence signal(s) &middot; "
        f"{len(pending)} pending review",
        "",
        "---",
        "",
    ]

    if convergence_events:
        lines.append("## ⚡ Convergence Signals")
        lines.append("")
        lines.append("_A watched competitor added, acquired, or materially expanded one of the other two pillars._")
        lines.append("")
        for ev in convergence_events:
            lines.append(_event_section(ev, sightings_for_event(conn, ev["id"])))
        lines.append("---")
        lines.append("")

    for action in ACTION_ORDER:
        events = by_action.get(action)
        if not events:
            continue
        lines.append(f"## {ACTION_LABELS[action]} ({len(events)})")
        lines.append("")
        for ev in events:
            lines.append(_event_section(ev, sightings_for_event(conn, ev["id"])))

    if pending:
        lines.append("---")
        lines.append("")
        lines.append(f"## Pending Review ({len(pending)})")
        lines.append("")
        lines.append("_Clustered this run but not yet scored — narration failed validation or hasn't run._")
        lines.append("")
        for ev in pending:
            lines.append(f"- {ev['title']} ({ev['competitor_id']}, {ev['event_date']})")
        lines.append("")

    if not all_events and not pending:
        lines.append("_No new developments surfaced this run._")
        lines.append("")

    return "\n".join(lines)


def write_brief(conn, run_id=None, out_path=DEFAULT_OUT_PATH):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_brief_markdown(conn, run_id=run_id), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args()
    connection = connect(db_path())
    try:
        written_to = write_brief(connection, run_id=args.run_id, out_path=args.out)
        print(f"Brief written to {written_to}")
    finally:
        connection.close()
