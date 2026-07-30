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
from surfaces.brand import (
    ACTION_LABELS,
    ACTION_TIER_COLOR,
    COLORS,
    DARK_COLORS,
    FONT_BODY,
    FONT_HEADLINE,
    FONT_MONO,
    best_text_color,
)

DEFAULT_OUT_DIR = Path(__file__).parent / "site" / "dist"

# One CSS class per distinct brand color used for action severity (4 tiers,
# not 9 — several actions share a tier's color; see brand.ACTION_TIER_COLOR).
_ACTION_TIER_CLASS_BY_COLOR = {c: f"action-tier-{i}" for i, c in enumerate(dict.fromkeys(ACTION_TIER_COLOR.values()))}
ACTION_CSS_CLASS = {action: _ACTION_TIER_CLASS_BY_COLOR[color] for action, color in ACTION_TIER_COLOR.items()}


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
    # Three-tier severity conveyed by font weight, not color — colored small
    # text reads as harsh even when it passes contrast math (see brand.py's
    # note on badge fills vs. plain text). urgent (Very High/High) is
    # boldest, notable (Moderate) is semi-bold, quiet (Low/Negligible) is
    # normal weight in the muted secondary color.
    return {
        "Very High": "bucket-urgent", "High": "bucket-urgent", "Moderate": "bucket-notable",
        "Low": "bucket-quiet", "Negligible": "bucket-quiet",
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
    <span class="headline-score">Headline <span class="score-num">{e(ev["headline_score"])}</span></span>
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
    <span class="{_bucket_class(ev["industry_bucket"])}">Industry Impact: <span class="score-num">{e(ev["industry_score"])}</span> ({e(ev["industry_bucket"])})</span>
    <span class="{_bucket_class(ev["relevance_bucket"])}">Relevance to OLD: <span class="score-num">{e(ev["relevance_score"])}</span> ({e(ev["relevance_bucket"])})</span>
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
    return f'<div class="stat"><div class="stat-value score-num">{e(value)}</div><div class="stat-label">{e(label)}</div></div>'


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


# Built from surfaces/brand.py's transcribed guideline colors, not invented
# hex values — see brand.py's module docstring for the mode-per-surface rule
# ("product / dense workflows" -> dark default) this site follows.
_D = DARK_COLORS
_L = COLORS
_TIER_COLORS = list(dict.fromkeys(ACTION_TIER_COLOR.values()))  # [negative_red, lucky_copper, signal_blue, text_secondary]
# Each light-mode tier color's dark-mode equivalent, so badges swap with the
# theme instead of staying pinned to light-mode hex values in both themes.
_TIER_DARK_EQUIVALENT = {
    _L["negative_red"]: _D["negative"],
    _L["lucky_copper"]: _D["accent_copper"],
    _L["signal_blue"]: _D["accent_blue"],
    _L["text_secondary"]: _D["text_secondary"],
}
_tier_var_names = [f"--tier-{i}" for i in range(len(_TIER_COLORS))]


def _tier_vars_css(colors):
    """colors: the tier backgrounds for one theme. Emits both the background
    variable and a COMPUTED (not assumed) text-color variable per tier — some
    brand accents (lucky_copper especially) contrast better with dark text
    even inside an otherwise-dark theme, so text can't just follow the theme.
    """
    parts = []
    for name, color in zip(_tier_var_names, colors):
        parts.append(f"{name}: #{color}")
        parts.append(f"{name}-text: #{best_text_color(color)}")
    return "; ".join(parts)


_tier_vars_light = _tier_vars_css(_TIER_COLORS)
_tier_vars_dark = _tier_vars_css([_TIER_DARK_EQUIVALENT[c] for c in _TIER_COLORS])
_tier_css = "\n".join(
    # Scoped to `.action-badge.action-tier-N`, NOT the bare tier class: the
    # event-card article carries the same action-tier-N class (for the
    # border-left accent below), and a bare `.action-tier-N { background;
    # color }` rule has equal specificity to `.event-card { background:
    # var(--surface) }` — appearing later in the stylesheet, it was winning
    # and painting the WHOLE card (not just the badge pill) with the tier
    # fill color, flipping the card's inherited text color to black/white.
    # That's why the badge text looked right (computed per-background) while
    # --muted/--fg text elsewhere (event-meta, so-what, links) — which don't
    # change per tier — read identically across differently-colored cards
    # instead of adapting, and lost contrast against the accidental fill.
    f'.action-badge.{_ACTION_TIER_CLASS_BY_COLOR[color]} {{ background: var(--tier-{i}); color: var(--tier-{i}-text); }} '
    f'.event-card.{_ACTION_TIER_CLASS_BY_COLOR[color]} {{ border-left-color: var(--tier-{i}); }}'
    for i, color in enumerate(_TIER_COLORS)
)

# Colored TEXT (as opposed to a filled badge background) reads as harsh at
# small sizes, even when it technically clears WCAG contrast — reported
# directly against the copper/gray text on this site. So: color lives ONLY
# in badge/pill fills and borders now (where best_text_color already picks
# plain black/bone — exactly the two colors that read fine), never in body
# text, links, or bucket labels. Severity there is now conveyed by font
# weight instead of hue.
#
# Light mode's --muted went through several rounds chasing "softer but
# still >=4.5:1 AA" via blend math (30%, then 15%) — both rejected on sight.
# A directly-chosen #9CA3AF was then also too light. Settled by publishing
# an actual side-by-side swatch comparison (solid color blocks + the real
# event-meta text, five candidates spanning the original raw gray to the
# too-light one) and letting the user pick directly rather than continuing
# to guess — #88909B ("D") is what was chosen. It sits below the WCAG AA
# floor for small text (~2.9:1 against --bg): a deliberate call for this
# secondary/de-emphasized meta text, made after direct visual comparison,
# not an oversight.
_muted_soft_light = "88909B"

STYLE_CSS = f"""
:root {{
  --bg: #{_D['bg']}; --surface: #{_D['surface']}; --fg: #{_D['text_primary']}; --muted: #{_D['text_secondary']};
  --border: #{_D['text_secondary']}33; --accent: #{_D['accent_blue']}; --accent-warm: #{_D['accent_copper']};
  --positive: #{_D['positive']}; --negative: #{_D['negative']};
  --font-headline: '{FONT_HEADLINE}', -apple-system, 'Segoe UI', sans-serif;
  --font-body: '{FONT_BODY}', -apple-system, 'Segoe UI', sans-serif;
  --font-mono: '{FONT_MONO}', 'SFMono-Regular', Consolas, monospace;
  {_tier_vars_dark};
}}
/* Guidelines: light mode for decks/proposals, dark for product/dense workflows.
   This IS the product surface, so dark is the base — light is the override,
   not the default, for both the OS-preference signal and the manual toggle. */
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #{_L['bg']}; --surface: #{_L['surface']}; --fg: #{_L['text_primary']}; --muted: #{_muted_soft_light};
    --border: #{_L['text_primary']}22; --accent: #{_L['signal_blue']}; --accent-warm: #{_L['lucky_copper']};
    --positive: #{_L['ledger_green']}; --negative: #{_L['negative_red']};
    {_tier_vars_light};
  }}
}}
:root[data-theme="light"] {{
  --bg: #{_L['bg']}; --surface: #{_L['surface']}; --fg: #{_L['text_primary']}; --muted: #{_muted_soft_light};
  --border: #{_L['text_primary']}22; --accent: #{_L['signal_blue']}; --accent-warm: #{_L['lucky_copper']};
  --positive: #{_L['ledger_green']}; --negative: #{_L['negative_red']};
  {_tier_vars_light};
}}
:root[data-theme="dark"] {{
  --bg: #{_D['bg']}; --surface: #{_D['surface']}; --fg: #{_D['text_primary']}; --muted: #{_D['text_secondary']};
  --border: #{_D['text_secondary']}33; --accent: #{_D['accent_blue']}; --accent-warm: #{_D['accent_copper']};
  --positive: #{_D['positive']}; --negative: #{_D['negative']};
  {_tier_vars_dark};
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font-family: var(--font-body); line-height: 1.55; }}
main {{ max-width: 900px; margin: 0 auto; padding: 24px 20px 80px; }}
h1, h2, h3 {{ font-family: var(--font-headline); text-wrap: balance; }}
a {{ color: var(--fg); text-decoration: underline; text-underline-offset: 2px; }}
a:focus-visible, button:focus-visible, summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.site-header {{ display: flex; justify-content: space-between; align-items: center; padding: 14px 24px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 12px; }}
.brand {{ font-family: var(--font-headline); font-weight: 700; }}
.brand span {{ font-family: var(--font-body); font-weight: 400; color: var(--muted); }}
.site-header nav a {{ margin-left: 16px; text-decoration: none; color: var(--fg); }}
.site-header nav a.active {{ font-weight: 700; text-decoration: underline; text-underline-offset: 2px; }}
.site-footer {{ text-align: center; color: var(--muted); font-size: 0.85em; padding: 20px; border-top: 1px solid var(--border); }}
.muted {{ color: var(--muted); font-size: 0.9em; }}
.empty {{ color: var(--muted); font-style: italic; }}
.score-num {{ font-family: var(--font-mono); font-variant-numeric: tabular-nums; }}
.stats {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0 28px; }}
.stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; min-width: 120px; }}
.stat-value {{ font-size: 1.6em; font-weight: 700; }}
.stat-label {{ color: var(--muted); font-size: 0.85em; }}
.event-card {{ background: var(--surface); border: 1px solid var(--border); border-left-width: 4px; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; }}
.event-card h3 {{ margin: 6px 0; }}
.event-card-header {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.event-meta {{ color: var(--muted); font-size: 0.9em; margin-bottom: 8px; }}
.axis-scores {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.9em; margin-bottom: 8px; }}
.so-what {{ margin: 8px 0; }}
.action-badge {{ font-size: 0.75em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; padding: 3px 8px; border-radius: 4px; }}
{_tier_css}
.badge {{ font-size: 0.75em; padding: 3px 8px; border-radius: 4px; border: 1px solid var(--border); }}
.badge-convergence {{ color: var(--fg); font-weight: 700; border-color: var(--accent-warm); }}
.badge-cco {{ color: var(--fg); font-weight: 700; border-color: var(--negative); }}
.headline-score {{ margin-left: auto; font-weight: 600; }}
.bucket-urgent {{ color: var(--fg); font-weight: 700; }}
.bucket-notable {{ color: var(--fg); font-weight: 600; }}
.bucket-quiet {{ color: var(--muted); }}
details summary {{ cursor: pointer; color: var(--fg); text-decoration: underline; text-underline-offset: 2px; margin-top: 6px; }}
dl.evidence {{ margin: 10px 0; }}
dl.evidence dt {{ font-weight: 600; text-transform: capitalize; margin-top: 6px; }}
dl.evidence dd {{ margin: 0 0 0 12px; color: var(--muted); font-style: italic; }}
ul.sources {{ margin: 10px 0 0; padding-left: 20px; }}
.competitor-table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
.competitor-table th, .competitor-table td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }}
.pending {{ margin-top: 32px; padding-top: 16px; border-top: 1px dashed var(--border); }}
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
