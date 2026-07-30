# Fixtures

Real filings, live-fetched from SEC EDGAR on 2026-07-29, trimmed to a manageable
excerpt for a test fixture. Wording within each kept passage is unaltered
(verbatim from the source); each file's provenance (source URL, accession
number, filing date) is documented in an HTML comment at the top of the file.

- `coinbase_8k.htm` — Coinbase Global, Inc. Form 8-K, accession
  0001679788-26-000011, filed 2026-02-12 (unmodified full document, ~31KB).
- `coinbase_ex99_1.htm` — Exhibit 99.1 (Q4/FY2025 shareholder letter) to the
  same 8-K, trimmed from ~1.3MB to two passages: the "Everything Exchange"
  convergence-thesis paragraph and the Deribit derivatives-performance paragraph.
- `robinhood_10q.htm` — Robinhood Markets, Inc. Form 10-Q for Q1 2026,
  accession 0001783879-26-000062, filed 2026-04-29, trimmed from ~2.3MB to
  two passages: the prediction-markets roadmap risk factor and the business
  description (equities/options/event contracts/futures/crypto).
- `futu_20f.htm` — Futu Holdings Limited (Moomoo) Form 20-F for FY2025,
  accession 0001104659-26-043451, filed 2026-04-15, trimmed from ~6.6MB to
  the Business Overview passage on US market-data partnerships and free
  crypto Level II data.

Note: Webull Corp (BULL) turned out to file as a foreign private issuer
(20-F/6-K), not domestic 10-Q/8-K as `docs/OLD_CI_EDGAR_Collector_Spec.md`'s
form table assumed — a real discrepancy discovered while fetching these
fixtures. Robinhood's 10-Q was substituted for the domestic-10-Q fixture
instead. Worth a spec correction / `filer_type` update for Webull in
`config/competitors.yaml` before Webull is added to a live collector run.

`test_edgar_collector.py` asserts on exact substrings pulled from these files
at test time (not hand-typed), so the tests stay correct even if a file is
re-trimmed, as long as the named sentences remain present verbatim.
