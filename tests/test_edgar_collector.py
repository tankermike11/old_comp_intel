import json
from pathlib import Path

import pytest

from collectors import edgar
from collectors.rate_limiter import RateLimiter

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- HTML cleaning --------------------------------------------------------------------

def test_clean_html_to_text_strips_tags_and_keeps_prose():
    cleaned = edgar.clean_html_to_text(read_fixture("coinbase_ex99_1.htm"))
    assert "<p>" not in cleaned
    assert "Everything Exchange" in cleaned


# --- Anti-hallucination substring gate ---------------------------------------------------

def test_verify_excerpt_accepts_real_substring():
    source = edgar.clean_html_to_text(read_fixture("coinbase_ex99_1.htm"))
    # exact substring must match after cleaning; pull the literal slice instead of hand-typing it
    idx = source.index("Derivatives, notably")
    literal = source[idx: idx + 80]
    assert edgar.verify_excerpt(literal, source) is True


def test_verify_excerpt_rejects_fabricated_excerpt():
    source = edgar.clean_html_to_text(read_fixture("coinbase_ex99_1.htm"))
    fabricated = "Coinbase announced it will acquire Robinhood in an all-stock merger."
    assert edgar.verify_excerpt(fabricated, source) is False


def test_verified_candidates_drops_only_the_fabricated_one():
    source = edgar.clean_html_to_text(read_fixture("robinhood_10q.htm"))
    idx = source.index("Robinhood was founded in 2013")
    real = source[idx: idx + 60]
    candidates = [
        {"title": "Real signal", "category_guess": "content_education", "verbatim_excerpt": real, "section": "Note 1"},
        {"title": "Hallucinated signal", "category_guess": "acquisition_ma",
         "verbatim_excerpt": "Robinhood agreed to acquire Interactive Brokers.", "section": "Note 1"},
    ]
    kept = edgar.verified_candidates(candidates, source)
    assert len(kept) == 1
    assert kept[0]["title"] == "Real signal"


# --- content hash + dedupe -------------------------------------------------------------

def test_content_hash_is_stable_and_whitespace_insensitive():
    a = edgar.content_hash("Some   excerpt\ntext")
    b = edgar.content_hash("some excerpt text")
    assert a == b


def test_build_sighting_shape():
    candidate = {"title": "T", "category_guess": "feature_launch", "verbatim_excerpt": "exact text", "section": "MD&A"}
    sighting = edgar.build_sighting("webull", "run-1", "https://example.test/doc.htm", "2026-07-01", candidate)
    assert sighting["competitor_id"] == "webull"
    assert sighting["run_id"] == "run-1"
    assert sighting["event_id"] is None
    assert sighting["surface"] == "edgar"
    assert sighting["source_url"] == "https://example.test/doc.htm"
    assert sighting["raw_excerpt"] == "exact text"
    assert sighting["content_hash"] == edgar.content_hash("exact text")


# --- filing filtering --------------------------------------------------------------------

def _submissions(forms, dates, primary_docs):
    return {
        "filings": {
            "recent": {
                "accessionNumber": [f"0001-{i}" for i in range(len(forms))],
                "form": forms,
                "filingDate": dates,
                "primaryDocument": primary_docs,
            }
        }
    }


def test_filter_new_filings_respects_forms_and_since_date():
    submissions = _submissions(
        forms=["8-K", "10-Q", "4"],
        dates=["2026-07-01", "2026-06-01", "2026-07-15"],
        primary_docs=["a.htm", "b.htm", "c.htm"],
    )
    out = edgar.filter_new_filings(submissions, forms=["8-K", "10-Q"], since_date="2026-06-15")
    assert len(out) == 1
    assert out[0]["form"] == "8-K"


def test_filter_new_filings_skips_missing_primary_document():
    submissions = _submissions(
        forms=["8-K", "8-K"],
        dates=["2026-07-01", "2026-07-02"],
        primary_docs=["a.htm", ""],
    )
    out = edgar.filter_new_filings(submissions, forms=["8-K"], since_date=None)
    assert len(out) == 1
    assert out[0]["primary_document"] == "a.htm"


# --- CIK resolution never hardcodes -------------------------------------------------------

def test_resolve_cik_map_caches_and_never_hardcodes(tmp_path, monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        status_code = 200

        def json(self_inner):
            calls["n"] += 1
            return {"0": {"cik_str": 1679788, "ticker": "coin", "title": "Coinbase Global, Inc."}}

        def raise_for_status(self_inner):
            pass

    class FakeClient:
        def get(self_inner, url, headers=None, params=None):
            return FakeResp()

    from config import get_settings
    settings = get_settings()
    cache_path = tmp_path / "cik_cache.json"
    limiter = RateLimiter(max_rps=8, min_spacing_ms=0)

    result = edgar.resolve_cik_map(FakeClient(), limiter, settings, cache_path=cache_path)
    assert result["COIN"] == "0001679788"
    assert calls["n"] == 1

    # second call within TTL must hit the cache, not the network
    result2 = edgar.resolve_cik_map(FakeClient(), limiter, settings, cache_path=cache_path)
    assert result2["COIN"] == "0001679788"
    assert calls["n"] == 1


# --- end-to-end per-filing processing with fakes (no live network) -------------------------

class FakeAnthropicMessage:
    def __init__(self, text):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class FakeAnthropicMessages:
    def __init__(self, responses_by_section):
        self._responses = responses_by_section

    def create(self, model, max_tokens, system, messages):
        content = messages[0]["content"]
        section = content.split("\n", 1)[0].replace("Section: ", "")
        return FakeAnthropicMessage(self._responses.get(section, "[]"))


class FakeAnthropicClient:
    def __init__(self, responses_by_section):
        self.messages = FakeAnthropicMessages(responses_by_section)


class FakeHttpResponse:
    def __init__(self, text=None, json_body=None):
        self.text = text
        self._json = json_body
        self.status_code = 200

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, routes):
        self.routes = routes  # url -> FakeHttpResponse

    def get(self, url, headers=None, params=None):
        return self.routes[url]


def test_process_filing_extracts_verified_sighting_and_drops_fabrication(monkeypatch):
    from config import get_settings
    settings = get_settings()
    cik = "0001679788"
    accession_no = "0001679788-26-000123"

    primary_text = read_fixture("coinbase_8k.htm")
    exhibit_text = read_fixture("coinbase_ex99_1.htm")

    primary_url = edgar.build_document_url(settings, cik, accession_no, "8k.htm")
    exhibit_url = edgar.build_document_url(settings, cik, accession_no, "ex99_1.htm")
    index_url = (
        f"{settings['edgar']['archives_base_url']}/{int(cik)}/"
        f"{accession_no.replace('-', '')}/index.json"
    )

    client = FakeHttpClient({
        primary_url: FakeHttpResponse(text=primary_text),
        exhibit_url: FakeHttpResponse(text=exhibit_text),
        index_url: FakeHttpResponse(json_body={"directory": {"item": [{"name": "ex99_1.htm"}]}}),
    })
    limiter = RateLimiter(max_rps=8, min_spacing_ms=0)

    cleaned_exhibit = edgar.clean_html_to_text(exhibit_text)
    idx = cleaned_exhibit.index("Derivatives, notably")
    real_excerpt = cleaned_exhibit[idx: idx + 90]

    responses = {
        "8-K — 8k.htm": "[]",
        "8-K — ex99_1.htm": json.dumps([
            {
                "title": "Coinbase expands crypto options access",
                "category_guess": "product_launch",
                "verbatim_excerpt": real_excerpt,
                "section": "EX-99.1",
            },
            {
                "title": "Fabricated merger claim",
                "category_guess": "acquisition_ma",
                "verbatim_excerpt": "Coinbase agreed to merge with Robinhood in Q3 2026.",
                "section": "EX-99.1",
            },
        ]),
    }
    anthropic_client = FakeAnthropicClient(responses)

    filing = {
        "accession_no": accession_no,
        "form": "8-K",
        "filing_date": "2026-07-24",
        "primary_document": "8k.htm",
    }

    sightings = edgar.process_filing(
        client, limiter, anthropic_client, settings, "coinbase", "run-1", cik, filing
    )

    assert len(sightings) == 1
    assert sightings[0]["raw_excerpt"] == real_excerpt
    assert sightings[0]["source_url"] == exhibit_url
    assert sightings[0]["competitor_id"] == "coinbase"
    assert sightings[0]["event_id"] is None


def test_process_filing_handles_10q(monkeypatch):
    from config import get_settings
    settings = get_settings()
    cik = "0001783879"
    accession_no = "0001783879-26-000062"

    text = read_fixture("robinhood_10q.htm")
    url = edgar.build_document_url(settings, cik, accession_no, "10q.htm")
    client = FakeHttpClient({url: FakeHttpResponse(text=text)})
    limiter = RateLimiter(max_rps=8, min_spacing_ms=0)

    cleaned = edgar.clean_html_to_text(text)
    idx = cleaned.index("accelerate delivery of futures and derivative product offerings")
    real_excerpt = cleaned[idx: idx + 100]

    anthropic_client = FakeAnthropicClient({
        "10-Q — 10q.htm": json.dumps([
            {
                "title": "Robinhood signals prediction-markets roadmap in 10-Q risk factors",
                "category_guess": "regulatory_filing",
                "verbatim_excerpt": real_excerpt,
                "section": "MD&A",
            }
        ]),
    })

    filing = {
        "accession_no": accession_no,
        "form": "10-Q",
        "filing_date": "2026-04-29",
        "primary_document": "10q.htm",
    }
    sightings = edgar.process_filing(client, limiter, anthropic_client, settings, "robinhood", "run-1", cik, filing)
    assert len(sightings) == 1
    assert sightings[0]["competitor_id"] == "robinhood"
    assert sightings[0]["raw_excerpt"] == real_excerpt


def test_process_filing_handles_20f_fpi_form(monkeypatch):
    from config import get_settings
    settings = get_settings()
    cik = "0001754581"
    accession_no = "0001104659-26-043451"

    text = read_fixture("futu_20f.htm")
    url = edgar.build_document_url(settings, cik, accession_no, "20f.htm")
    client = FakeHttpClient({url: FakeHttpResponse(text=text)})
    limiter = RateLimiter(max_rps=8, min_spacing_ms=0)

    cleaned = edgar.clean_html_to_text(text)
    idx = cleaned.index("free real-time Level II market data for dozens of cryptocurrencies")
    real_excerpt = cleaned[idx: idx + 120]

    anthropic_client = FakeAnthropicClient({
        "20-F — 20f.htm": json.dumps([
            {
                "title": "Moomoo expands crypto trading offering",
                "category_guess": "feature_launch",
                "verbatim_excerpt": real_excerpt,
                "section": "Item 4.B Business Overview",
            }
        ]),
    })

    filing = {
        "accession_no": accession_no,
        "form": "20-F",
        "filing_date": "2026-04-30",
        "primary_document": "20f.htm",
    }
    sightings = edgar.process_filing(client, limiter, anthropic_client, settings, "moomoo", "run-1", cik, filing)
    assert len(sightings) == 1
    assert sightings[0]["competitor_id"] == "moomoo"
    assert sightings[0]["raw_excerpt"] == real_excerpt
