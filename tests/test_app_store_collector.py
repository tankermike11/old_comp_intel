from collectors import app_store
from collectors.rate_limiter import RateLimiter
from config import get_settings


class FakeHttpResponse:
    def __init__(self, json_body):
        self._json = json_body
        self.status_code = 200

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, routes_by_params_id=None, lookup_response=None, search_response=None):
        self.lookup_response = lookup_response
        self.search_response = search_response
        self.calls = []

    def get(self, url, headers=None, params=None):
        self.calls.append((url, params))
        if url.endswith("/lookup"):
            return FakeHttpResponse(self.lookup_response)
        if url.endswith("/search"):
            return FakeHttpResponse(self.search_response)
        raise AssertionError(f"unexpected url {url}")


LIMITER = RateLimiter(max_rps=8, min_spacing_ms=0)
SETTINGS = get_settings()

REAL_LOOKING_RESULT = {
    "trackId": 886427730,
    "trackName": "Coinbase: Buy Crypto & Stocks",
    "version": "4.12.0",
    "currentVersionReleaseDate": "2026-07-20T00:00:00Z",
    "releaseNotes": "This update adds support for tracking Deribit crypto options positions directly in the app.",
    "trackViewUrl": "https://apps.apple.com/us/app/coinbase-buy-crypto-stocks/id886427730",
}


def test_lookup_app_returns_first_result():
    client = FakeHttpClient(lookup_response={"resultCount": 1, "results": [REAL_LOOKING_RESULT]})
    result = app_store.lookup_app(client, LIMITER, SETTINGS, "886427730")
    assert result["trackName"] == "Coinbase: Buy Crypto & Stocks"


def test_lookup_app_returns_none_for_empty_results():
    client = FakeHttpClient(lookup_response={"resultCount": 0, "results": []})
    result = app_store.lookup_app(client, LIMITER, SETTINGS, "0000000000")
    assert result is None


def test_search_apps_used_for_resolution_not_hardcoding():
    client = FakeHttpClient(search_response={"resultCount": 1, "results": [REAL_LOOKING_RESULT]})
    results = app_store.search_apps(client, LIMITER, SETTINGS, "Coinbase")
    assert results[0]["trackId"] == 886427730
    # confirms the search call actually asked the API with the given term
    _, params = client.calls[0]
    assert params["term"] == "Coinbase"


def test_build_sighting_uses_real_release_notes_verbatim():
    sighting = app_store.build_sighting("coinbase", "run-1", REAL_LOOKING_RESULT)
    assert sighting["surface"] == "app_store_ios"
    assert sighting["competitor_id"] == "coinbase"
    assert sighting["run_id"] == "run-1"
    assert sighting["event_id"] is None
    assert sighting["raw_excerpt"] == REAL_LOOKING_RESULT["releaseNotes"]
    assert sighting["source_url"] == REAL_LOOKING_RESULT["trackViewUrl"]
    assert sighting["observed_at"] == "2026-07-20"
    assert "4.12.0" in sighting["title"]


def test_build_sighting_returns_none_when_no_release_notes():
    record = {**REAL_LOOKING_RESULT, "releaseNotes": ""}
    assert app_store.build_sighting("coinbase", "run-1", record) is None


def test_build_sighting_returns_none_when_no_release_date():
    record = {**REAL_LOOKING_RESULT, "currentVersionReleaseDate": ""}
    assert app_store.build_sighting("coinbase", "run-1", record) is None


def test_build_sighting_falls_back_to_constructed_url_if_missing():
    record = {**REAL_LOOKING_RESULT}
    del record["trackViewUrl"]
    sighting = app_store.build_sighting("coinbase", "run-1", record)
    assert sighting["source_url"] == "https://apps.apple.com/us/app/id886427730"


def test_content_hash_is_stable_and_whitespace_insensitive():
    a = app_store.content_hash("123", "1.0", "Bug   fixes\nand improvements")
    b = app_store.content_hash("123", "1.0", "bug fixes and improvements")
    assert a == b


def test_content_hash_differs_across_versions():
    a = app_store.content_hash("123", "1.0", "Bug fixes")
    b = app_store.content_hash("123", "2.0", "Bug fixes")
    assert a != b


def test_collect_for_competitor_returns_one_sighting():
    client = FakeHttpClient(lookup_response={"resultCount": 1, "results": [REAL_LOOKING_RESULT]})
    sightings = app_store.collect_for_competitor(client, LIMITER, SETTINGS, "coinbase", "886427730", "run-1")
    assert len(sightings) == 1
    assert sightings[0]["competitor_id"] == "coinbase"


def test_collect_for_competitor_returns_empty_list_for_unresolved_app_id():
    client = FakeHttpClient(lookup_response={"resultCount": 0, "results": []})
    sightings = app_store.collect_for_competitor(client, LIMITER, SETTINGS, "coinbase", "bad-id", "run-1")
    assert sightings == []
