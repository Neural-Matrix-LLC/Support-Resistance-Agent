# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

An LLM-orchestrated agent that, given a ticker, returns 2–4 support and 2–4 resistance zones for the next 5 trading sessions, each with calibrated `P(touch)`, `P(hold)`, `P(break)`, expected reaction, confidence, and an evidence trail.

**P0 (walking skeleton) is implemented and its live gate passed** (2026-09-18/19, see `HISTORY.md`): `uv run sr p0 TICKER` runs yfinance daily bars → Wilder ATR → swing + round-number generators → naive clusterer → bar-triple bootstrap Monte Carlo → fixed-width report, with `--dump DIR` writing every intermediate as CSV. No DuckDB, no LLM, no persistence beyond the immutable raw CSV cache. **P1 (data spine) is next**; its design is `docs/SR_Technical_Document.md` §4. P0 findings that shape P1: the price spine is **yfinance** (Stooq's CSV endpoint needs a browser; Tiingo's unadjusted history leaks pre-split prices into the level generators — D4 in the tech doc); a provider's partial bar for an open session must be cut by `available_at ≤ now`; the round-number ladder tiles the ±3 ATR window under the naive clusterer (P2's HDBSCAN must not inherit that).

## Documents and their precedence

| File | Role | Wins when in conflict |
|---|---|---|
| `docs/BUILD-PLAN.md` | *What* we build, in what order, with what gates/kill criteria and frozen constants (§6–§12) | Highest |
| `docs/SR_Technical_Document.md` | *How*: per-phase architecture, flows, classes, storage, algorithms, gate tests | Below BUILD-PLAN |
| `docs/Support-Resistance-design-fixed.MD`, `docs/SR-Plan.md` | Superseded reference catalogues (label definitions, state machine, schema, generator formulas) | Reference only |

`SR_Technical_Document.md` has one section per phase (P0–P6) with a fixed sub-section template: `.1` objective/gate/kill · `.2` architecture (Mermaid) · `.3` data/work flow (Mermaid) · `.4` layers & classes · `.5` data sources & storage · `.6` algorithms & formulas · `.7` gate tests · `.8` deliverables. When designing or changing a phase, edit that phase's section in place — do not create a new design doc. P5–P6 are marked **[provisional]** and get rewritten when work reaches them. Constants BUILD-PLAN fixes are cited as `(BP §x)`; constants introduced in the tech doc are marked **initial** and may only be tuned inside walk-forward validation.

## Working in this repository

Stack: Python 3.11 via `uv` (`.python-version` is pinned; system python is 3.10), Polars, NumPy, `exchange_calendars`, `typer`, PyYAML, python-dotenv; dev: pytest + Hypothesis, ruff, mypy. Later phases add DuckDB/Parquet, scikit-learn, LightGBM, `arch`, `hdbscan`.

```bash
uv sync --extra dev                      # env + deps (creates .venv)
uv run pytest                            # 59 offline unit tests, ~2 s; no network
uv run pytest -m integration             # live yfinance (US+HK) / Tiingo (needs token) / Stooq status
uv run pytest tests/unit/test_mc.py -k byte_identical   # one test
uv run ruff check src tests && uv run mypy              # the pre-commit gate

uv run sr p0 AAPL                        # P0 gate; yfinance, no token; caches data/raw/yfinance/AAPL/
uv run sr p0 700 --market HK             # 0700.HK
uv run sr p0 AAPL --dump out/aapl        # + run/bars/candidates/zones/triples/paths.csv
uv run sr p0 AAPL --offline --as-of 2026-09-11 --seed 0 --paths 10000   # cache only, replayable
uv run sr p0 AAPL --source tiingo        # TIINGO_API_KEY in .env; --source stooq --offline reads a
                                         # browser-downloaded CSV at data/raw/stooq/AAPL.US/YYYY-MM-DD.csv
```

Layout: `src/sr_agent/` (src-layout; import paths are the documented `sr_agent.*`), `tests/{unit,integration}/`, raw cache under `data/` (git-ignored). Tests build synthetic bars through `tests/conftest.py` (`synthetic_ohlcv`, `bars_from_ohlcv`, `cached_stooq`) and never touch the network; anything live is `@pytest.mark.integration` and deselected by default.

Permanent, load-bearing tests — do not weaken them to make a change pass:

- `tests/unit/test_config.py::test_frozen_constants_match_build_plan` — `thresholds.yaml` `frozen:` keys equal BUILD-PLAN. Change BUILD-PLAN first, then the test, then the YAML.
- `tests/unit/test_layering.py::test_no_upward_imports` — the L0–L5 import boundaries below. Move the code, do not widen the rule.
- `tests/unit/test_cli.py::test_replay_is_byte_identical` — replay determinism (BP §10.4.4).
- `tests/unit/test_swings.py::test_available_at_is_after_formation_and_grows_with_k` — a swing is not knowable until its retrace confirms it; the first leakage trap.
- `tests/unit/test_ingestion.py::test_cache_is_immutable_and_dated` — raw downloads are never overwritten.
- `tests/unit/test_ingestion.py::test_bars_hide_the_partial_bar_of_an_open_session` — `available_at ≤ min(end of as_of, now)`; providers serve today's half-finished bar during the session.
- `tests/unit/test_cli.py::test_dump_csvs_reproduce_the_report_offline` — the `--dump` CSVs alone re-derive TR/ATR, the §3.6.4 zone geometry and `P(touch)`; keep it in step with any formula change.

## Architecture invariants (these are tests, not policies)

1. **The LLM never emits a number.** No price, probability, zone boundary, or confidence score originates in the agent layer. The LLM only (a) selects data sources, (b) extracts structured features from text, (c) writes narrative grounded in structured output. A verifier regexes every number out of the narrative and asserts it exists in the structured forecast; tools return a `display_string` the LLM must quote verbatim.
2. **Leakage is a type error.** Every table carries `event_ts` and `available_at`; every data tool and `PITStore` read takes `as_of` and filters `available_at ≤ as_of`. There is no unfiltered read path.
3. **Replay determinism.** `(security_id, as_of, config_version)` → byte-identical forecast. MC uses a seeded RNG; `forecast_id = sha256(security_id, forecast_ts, config_version, model_version)[:16]` so replays collide on purpose.
4. **Session arithmetic goes through `exchange_calendars`**, never calendar days. Horizon H = 5 sessions.
5. **Layer discipline** (each layer imports only lower ones): L0 `config/` → L1 `data/` → L2 `levels/`, `labels/` → L3 `features/`, `simulate/` → L4 `models/`, `calibrate/`, `validation/` → L5 `agent/`, `api/`, `reporting/`, `ops/`.
6. **Frozen constants** live in `config/thresholds.yaml`, listed under its `frozen:` key, and `test_config.py` asserts they match BUILD-PLAN (e.g. `atr_window: 20`, `horizon_sessions: 5`, `delta_atr: 0.25`, publication thresholds `p_touch ≥ 0.60`, `p_hold ≥ 0.65`, `confidence ≥ 0.70`, `dq ≥ 0.80`).
7. **Raw data is never overwritten**; `data/raw/` is immutable per `(source, symbol, fetch_date)`; lake partitions are rewritten by idempotent jobs; `data/` and `mlruns/` are git-ignored.
8. **Every experiment is logged** to `research/trials.jsonl` (feeds the Deflated Sharpe calculation in P5); rejected enrichment modules go to `research/rejected.md` with their numbers.

## Standing project decisions

- **No data budget — Tier-0 sources only**: yfinance (price spine, US + HK, split-adjusted at source — decided 2026-09-18, replacing Stooq), Tiingo free tier (reconciliation only), Stooq as a manual-download fallback, SEC EDGAR, FRED, free CBOE daily options snapshot (archived from P1, consumed by nothing), `exchange_calendars` built from 1960. Do not design for or recommend paid feeds; keep schema slots for missing sources with `*_available = 0`. Options/GEX and intraday modules are **not built** — this is a daily-bar forecaster.
- **LLM is provider-agnostic.** All calls go through an `LLMClient` interface with roles (planner, extractor, narrator, research) mapped to `(provider, model)` in `config/agent.yaml`; `ProviderAdapter`s translate MCP tool schemas per provider. Vendor model ids in BUILD-PLAN §10.3 are shipped config defaults, not design decisions. MCP is the tool boundary between agent and core.
- **US first (S&P 500 + 400, point-in-time incl. delisted names, 2010→), HK second** (P4 generalisation test). A-share price limits are an inactive hook in the MC engine.
- **LightGBM is the production model; deep learning is a challenger** that ships only if it beats LightGBM out-of-sample with CI excluding zero.
- **Phase gates are sequential and can kill the project.** P2's matched-control test (real zones vs. distance-matched placebos) must pass before any ML is written. Do not add features or models to get past a failed gate.

## Repository rules (the author's standing rules; apply here)

- **Every implemented formula carries the original formula** from the tech doc in its docstring or an end-of-line comment (`# H_j = C_{j−1}·τ.h`), citing the section, so code can be checked against the design without opening the doc.
- **`HISTORY.md` is mandatory**: every code/config/architectural change is logged there — goal, root cause for bugs, implementation detail, deviations from the design and why, related files, test coverage — before the change is considered complete. Newest entry first.
- **Every change plan includes a test section**: no regressions, obsolete tests announced for removal, new tests announced for new code paths, added/removed tests documented in `CLAUDE.md` / `HISTORY.md`.
- Keep `.env.example` in sync with every env var the code reads; never commit `.env`.
- Unit tests must not make real API calls (synthetic fixtures, fake sources); anything live is `@pytest.mark.integration`.
- When a phase's implementation departs from `docs/SR_Technical_Document.md`, update that phase's section in place (and the decision table in §1 if a decision is affected) in the same change.
