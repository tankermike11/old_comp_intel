"""iOS App Store release-notes collector (Path B, docs/OLD_CI_System_Build_Roadmap.md).

Uses Apple's official, free iTunes Lookup/Search API — no scraping, no auth,
the same official-API footing as the EDGAR collector. App IDs are resolved
and verified against the live Search API (see config/app_store_ids.yaml),
never hardcoded/guessed.

Android/Play Store is explicitly out of scope: there's no equivalent official
API, so pulling Android release notes would mean scraping the Play Store
page — that needs the CCO/compliance sign-off CLAUDE.md's guardrail #5 calls
for, which hasn't happened. Don't add it here without that sign-off.

Release notes are a small, already-official, already-final field Apple itself
publishes for the current version — unlike EDGAR's long filings, there's no
LLM extraction pass here. The collector source-cites Apple's own
`releaseNotes` field verbatim; source_url + content_hash dedup are still
enforced (schema.md's structural anti-hallucination rule), but there's no
paraphrase/hallucination risk to gate against since nothing summarizes it.
"""
import hashlib
import re
import uuid

import httpx

from collectors.rate_limiter import RateLimiter, get_with_backoff


def build_client_and_limiter(settings):
    limiter = RateLimiter(
        max_rps=settings["app_store"]["max_rps"],
        min_spacing_ms=settings["app_store"]["min_spacing_ms"],
    )
    client = httpx.Client(timeout=30.0)
    return client, limiter


def lookup_app(client, limiter, settings, app_id):
    """GET the iTunes Lookup API for one app id. Returns the raw result dict,
    or None if the id doesn't resolve (removed app, bad id, etc.).
    """
    url = f"{settings['app_store']['base_url']}/lookup"
    params = {"id": app_id, "country": settings["app_store"]["country"]}
    resp = get_with_backoff(client, url, limiter, settings["app_store"]["backoff_seconds"], params=params)
    results = resp.json().get("results", [])
    return results[0] if results else None


def search_apps(client, limiter, settings, term):
    """GET the iTunes Search API — used to RESOLVE/verify an app id from a
    name, never to hardcode one blindly. Returns the raw list of result dicts.
    """
    url = f"{settings['app_store']['base_url']}/search"
    params = {"term": term, "country": settings["app_store"]["country"], "entity": "software", "limit": 10}
    resp = get_with_backoff(client, url, limiter, settings["app_store"]["backoff_seconds"], params=params)
    return resp.json().get("results", [])


def content_hash(app_id, version, release_notes):
    normalized = re.sub(r"\s+", " ", f"{app_id}|{version}|{release_notes or ''}").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_sighting(competitor_id, run_id, app_record):
    """app_record: one result dict from lookup_app. Returns a sighting dict,
    or None if there's nothing reportable (no release notes, or no dated
    version — sighting.observed_at is NOT NULL, so we never fabricate a date).
    """
    release_notes = (app_record.get("releaseNotes") or "").strip()
    observed_at = (app_record.get("currentVersionReleaseDate") or "")[:10]
    if not release_notes or not observed_at:
        return None

    version = app_record.get("version", "")
    app_id = app_record.get("trackId")
    return {
        "id": str(uuid.uuid4()),
        "competitor_id": competitor_id,
        "run_id": run_id,
        "event_id": None,
        "surface": "app_store_ios",
        "source_url": app_record.get("trackViewUrl") or f"https://apps.apple.com/us/app/id{app_id}",
        "observed_at": observed_at,
        "title": f"{app_record.get('trackName', 'App')} v{version} release notes",
        "raw_excerpt": release_notes,
        "content_hash": content_hash(app_id, version, release_notes),
        "embedding": None,
    }


def collect_for_competitor(client, limiter, settings, competitor_id, app_id, run_id):
    """Returns a list of 0 or 1 sighting dicts — the iTunes Lookup API only
    ever reports the CURRENT version's release notes, not history. Re-running
    against an unchanged version is a no-op via content_hash dedup.
    """
    app_record = lookup_app(client, limiter, settings, app_id)
    if app_record is None:
        return []
    sighting = build_sighting(competitor_id, run_id, app_record)
    return [sighting] if sighting else []
