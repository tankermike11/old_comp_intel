"""EDGAR collector (docs/OLD_CI_EDGAR_Collector_Spec.md) — Path A, the first live pipeline.

Pulls SEC filings for the US-public Tier-1 names, extracts source-cited candidate
developments, and emits schema-conformant `sighting` dicts (event_id null). This
module does not score — that's pipeline/score.py, a separate step.

Anti-hallucination gate: the LLM extraction pass only proposes {title, category_guess,
verbatim_excerpt, section}. Every verbatim_excerpt is verified as a literal substring
of the cleaned filing text before a sighting is built; anything that fails is dropped.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from collectors.rate_limiter import RateLimiter, get_with_backoff
from config import get_sec_user_agent, get_settings

CIK_CACHE_PATH = Path(__file__).parent.parent / ".cik_cache.json"

EXTRACTION_SYSTEM_PROMPT = """You are extracting candidate competitive-intelligence \
developments from one section of an SEC filing for One Lucky Dog, a US options-first \
retail brokerage tracking competitors across options, crypto, and prediction markets.

Return JSON only: a list of objects, each with exactly these keys:
- title: a one-line factual description
- category_guess: one of feature_launch, product_launch, pricing_change, acquisition_ma, \
regulatory_filing, partnership, hiring_signal, content_education, platform_infra, other
- verbatim_excerpt: an EXACT, word-for-word substring copied from the provided text — \
never paraphrase, summarize, or alter it in any way
- section: the section/exhibit this came from (passed to you below)

If the section is routine boilerplate with no product, strategy, or traction signal, \
return an empty list. Do not invent developments not stated in the text."""


def _headers():
    return {"User-Agent": get_sec_user_agent()}


# --- CIK resolution -----------------------------------------------------------------

def resolve_cik_map(client, limiter, settings, cache_path=CIK_CACHE_PATH, force_refresh=False):
    """Ticker -> zero-padded 10-digit CIK. Cached locally; refreshed per cik_cache_ttl_days.
    Never hardcode a CIK — always resolve from company_tickers.json.
    """
    ttl_days = settings["edgar"]["cik_cache_ttl_days"]
    if not force_refresh and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < timedelta(days=ttl_days):
            return cached["map"]

    resp = get_with_backoff(
        client, settings["edgar"]["ticker_map_url"], limiter,
        settings["edgar"]["backoff_seconds"], headers=_headers(),
    )
    raw = resp.json()
    ticker_to_cik = {entry["ticker"].upper(): str(entry["cik_str"]).zfill(10) for entry in raw.values()}
    cache_path.write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "map": ticker_to_cik}),
        encoding="utf-8",
    )
    return ticker_to_cik


# --- Filing discovery -----------------------------------------------------------------

def fetch_submissions(client, limiter, settings, cik):
    url = f"{settings['edgar']['base_url']}/submissions/CIK{cik}.json"
    resp = get_with_backoff(client, url, limiter, settings["edgar"]["backoff_seconds"], headers=_headers())
    return resp.json()


def filter_new_filings(submissions, forms, since_date=None):
    """since_date: 'YYYY-MM-DD', exclusive lower bound; None pulls everything in `recent`."""
    recent = submissions["filings"]["recent"]
    count = len(recent["accessionNumber"])
    out = []
    for i in range(count):
        form = recent["form"][i]
        if form not in forms:
            continue
        filed = recent["filingDate"][i]
        if since_date and filed <= since_date:
            continue
        primary_document = recent["primaryDocument"][i]
        if not primary_document:
            continue  # spec: missing primaryDocument -> skip, log, continue
        out.append({
            "accession_no": recent["accessionNumber"][i],
            "form": form,
            "filing_date": filed,
            "primary_document": primary_document,
        })
    return out


# --- Document fetch + cleaning ---------------------------------------------------------

def _accession_no_dashes_removed(accession_no):
    return accession_no.replace("-", "")


def build_document_url(settings, cik, accession_no, filename):
    cik_no_leading_zeros = str(int(cik))
    return (
        f"{settings['edgar']['archives_base_url']}/{cik_no_leading_zeros}/"
        f"{_accession_no_dashes_removed(accession_no)}/{filename}"
    )


def clean_html_to_text(html_or_text):
    lowered = html_or_text[:2000].lower()
    if not any(tag in lowered for tag in ("<html", "<div", "<p", "<body", "<table")):
        return html_or_text.strip()
    soup = BeautifulSoup(html_or_text, "html.parser")
    text = soup.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_document_text(client, limiter, settings, cik, accession_no, filename):
    url = build_document_url(settings, cik, accession_no, filename)
    resp = get_with_backoff(client, url, limiter, settings["edgar"]["backoff_seconds"], headers=_headers())
    return clean_html_to_text(resp.text)


def fetch_filing_index(client, limiter, settings, cik, accession_no):
    cik_no_leading_zeros = str(int(cik))
    url = (
        f"{settings['edgar']['archives_base_url']}/{cik_no_leading_zeros}/"
        f"{_accession_no_dashes_removed(accession_no)}/index.json"
    )
    resp = get_with_backoff(client, url, limiter, settings["edgar"]["backoff_seconds"], headers=_headers())
    return resp.json()


def find_exhibit_filenames(index_json, pattern=r"ex-?99"):
    items = index_json.get("directory", {}).get("item", [])
    return [item["name"] for item in items if re.search(pattern, item["name"], re.IGNORECASE)]


def chunk_text(text, max_chars=12000):
    """Chunk by paragraph so long 10-K/20-F documents fit the extraction context."""
    paragraphs = text.split("\n\n")
    chunks, current = [], ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks or [text]


# --- Extraction + anti-hallucination verification ---------------------------------------

def extract_candidates(anthropic_client, text, section, model="claude-sonnet-5"):
    """The one place the LLM is used here: propose candidates only, never scores. Nothing
    downstream trusts this output until verify_excerpt confirms it against the source text.
    """
    message = anthropic_client.messages.create(
        model=model,
        max_tokens=2048,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Section: {section}\n\n{text}"}],
    )
    raw = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    try:
        candidates = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return candidates if isinstance(candidates, list) else []


def verify_excerpt(excerpt, source_text):
    """Anti-hallucination gate: reject any excerpt that isn't a literal substring of the
    cleaned source text. Code, not trust — this runs regardless of how confident the model sounds.
    """
    return bool(excerpt) and excerpt in source_text


def verified_candidates(candidates, source_text):
    return [c for c in candidates if verify_excerpt(c.get("verbatim_excerpt", ""), source_text)]


def content_hash(excerpt):
    normalized = re.sub(r"\s+", " ", excerpt).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_sighting(competitor_id, run_id, source_url, observed_at, candidate):
    excerpt = candidate["verbatim_excerpt"]
    return {
        "id": str(uuid.uuid4()),
        "competitor_id": competitor_id,
        "run_id": run_id,
        "event_id": None,
        "surface": "edgar",
        "source_url": source_url,
        "observed_at": observed_at,
        "title": candidate.get("title"),
        "raw_excerpt": excerpt,
        "content_hash": content_hash(excerpt),
        "embedding": None,
    }


# --- Per-filing / per-competitor orchestration -------------------------------------------

def process_filing(client, limiter, anthropic_client, settings, competitor_id, run_id, cik, filing):
    """Fetch a filing's primary document (+ EX-99.x exhibits for 8-K), extract
    candidates per chunk, verify, and emit deduped sightings for this filing.
    """
    documents = [filing["primary_document"]]
    if filing["form"] == "8-K":
        try:
            index_json = fetch_filing_index(client, limiter, settings, cik, filing["accession_no"])
            documents.extend(find_exhibit_filenames(index_json))
        except httpx.HTTPStatusError:
            pass  # exhibit index unavailable shouldn't drop the primary document

    sightings = []
    seen_hashes = set()
    for filename in documents:
        try:
            text = fetch_document_text(client, limiter, settings, cik, filing["accession_no"], filename)
        except httpx.HTTPStatusError:
            continue  # spec: missing/unfetchable document -> skip, log, continue
        for chunk in chunk_text(text):
            candidates = extract_candidates(anthropic_client, chunk, section=f"{filing['form']} — {filename}")
            for candidate in verified_candidates(candidates, chunk):
                sighting = build_sighting(
                    competitor_id, run_id,
                    build_document_url(settings, cik, filing["accession_no"], filename),
                    filing["filing_date"], candidate,
                )
                if sighting["content_hash"] in seen_hashes:
                    continue
                seen_hashes.add(sighting["content_hash"])
                sightings.append(sighting)
    return sightings


def collect_for_competitor(client, limiter, anthropic_client, settings, competitor, run_id, last_checked=None):
    """competitor: a dict from config/competitors.yaml (raw, tickers as a list or None).
    Returns a list of sighting dicts; [] for competitors with no ticker (private/pre-IPO —
    out of scope for this collector per the spec) or a filer_type this collector doesn't handle.
    """
    tickers = competitor.get("tickers")
    if not tickers:
        return []

    is_fpi = competitor.get("filer_type") == "fpi"
    forms = settings["edgar"]["forms_fpi"] if is_fpi else settings["edgar"]["forms_domestic"]

    cik_map = resolve_cik_map(client, limiter, settings)
    cik = cik_map.get(tickers[0].upper())
    if not cik:
        raise ValueError(f"could not resolve CIK for ticker {tickers[0]!r} ({competitor['id']})")

    submissions = fetch_submissions(client, limiter, settings, cik)

    since_date = last_checked
    if since_date is None:
        lookback_days = settings["edgar"]["lookback_days_first_run"]
        since_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    filings = filter_new_filings(submissions, forms, since_date)

    all_sightings = []
    for filing in filings:
        all_sightings.extend(
            process_filing(client, limiter, anthropic_client, settings, competitor["id"], run_id, cik, filing)
        )
    return all_sightings


def build_client_and_limiter(settings=None):
    settings = settings or get_settings()
    limiter = RateLimiter(
        max_rps=settings["edgar"]["max_rps"],
        min_spacing_ms=settings["edgar"]["min_spacing_ms"],
    )
    client = httpx.Client(timeout=30.0)
    return client, limiter
