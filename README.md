# Support-Resistance-Agent

An agent that, given a ticker, returns support and resistance *zones* for the
next 5 trading sessions with calibrated probabilities. The numbers come from a
deterministic Python core; the LLM only plans and narrates and never emits a
price or a probability.

- What and why: [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md)
- How, per phase: [`docs/SR_Technical_Document.md`](docs/SR_Technical_Document.md)
- Change log: [`HISTORY.md`](HISTORY.md)

## Status

P0 walking skeleton (2026-09-18): daily bars → ATR → swing + round-number
candidate levels → naive zones → bootstrap Monte Carlo `P(touch)` → printed
report. Next: P1 data spine.

## Quick start

```bash
uv sync --extra dev
uv run sr p0 AAPL               # daily bars via yfinance (no token), cached under data/raw/
uv run sr p0 700 --market HK    # 0700.HK
uv run sr p0 AAPL --dump out/   # + bars/candidates/zones/triples/paths CSVs for offline checks
uv run pytest                   # offline unit tests
```

Other sources: `--source tiingo` (free token in `.env`, see `.env.example`; US only,
unadjusted prices) or `--source stooq --offline` with a browser-downloaded
`https://stooq.com/q/d/l/?s=aapl.us&i=d` saved as `data/raw/stooq/AAPL.US/YYYY-MM-DD.csv`
(Stooq's endpoint needs a browser since 2026-09).
