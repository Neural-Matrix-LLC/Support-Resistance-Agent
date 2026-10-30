# Support-Resistance-Agent — Repo Overview & New Implementation Plan

**Date:** 2026-10-29 · **Repo:** `/opt/data/Support-Resistance-Agent` (origin: `Neural-Matrix-LLC/Support-Resistance-Agent`, local `main` = `cc4e85c`, in sync)
**Status:** P0 done & verified. **This plan waits for Thomas's review — no code until approved.**

---

## Part 1 — Repo overview (as found)

### What the project is
An LLM-orchestrated agent that, given a ticker, returns 2–4 support and 2–4
resistance **zones** for the next 5 trading sessions, each with calibrated
`P(touch)`, `P(hold)`, `P(break)`, expected reaction, confidence, and an
evidence trail. **The LLM never emits a number** — it selects data sources,
extracts features from text, and narrates; a deterministic Python core owns
every price, probability, and score.

### Document hierarchy (precedence, per CLAUDE.md)
| File | Role | Wins |
|---|---|---|
| `docs/BUILD-PLAN.md` (655 L, v1.2) | *What* to build, order, gates, kill criteria, frozen constants | Highest |
| `docs/SR_Technical_Document.md` (3,137 L, v0.4) | *How*: per-phase P0–P6 design, mermaid arch + dataflow, classes, formulas, gate tests | Below BUILD-PLAN |
| `docs/Support-Resistance-design-fixed.MD`, `docs/SR-Plan.md` | Superseded reference catalogues | Reference only |
| `HISTORY.md` (436 L) | Change log, one entry per change | — |

### Current state (verified 2026-10-29)
- **P0 walking skeleton COMPLETE** (gate passed 2026-09-18/19).
  `sr p0 TICKER`: yfinance daily bars → Wilder ATR(20) → swing (multi-k) +
  round-number generators → naive clusterer → bar-triple bootstrap MC (10k
  paths) → fixed-width zone report; `--dump` CSVs reproduce the report offline.
- **Live P0 run verified today:** AAPL as_of 2026-10-30 — spot 348.91,
  ATR20 6.459, **125 candidates → 8 zones** with P(touch) 0.27–0.89, 2.7 s.
- **Tests: 59/59 offline pass** (3.2 s, no network). Load-bearing tests
  enforce: frozen constants = BUILD-PLAN; L0–L5 no-upward-imports; replay
  byte-identical; swing `available_at` leakage trap; immutable raw cache;
  partial-bar hiding; `--dump` CSVs re-derive the report.
- **Code: ~930 LOC** in `src/sr_agent/` (cli, data/ingestion ×4 sources,
  levels/{atr,cluster,zone,generators/{structure,round}}, simulate/monte_carlo,
  reporting, config). Layers L3+ (`features/`, `models/`, `calibrate/`,
  `validation/`, `agent/`, `api/`, `ops/`) are **empty `__init__.py` stubs**.
- **Next phase per docs: P1 (data spine)** — tech doc §4 (M0–M8), BUILD-PLAN §17.
- Git: 6 commits; `docs/p1-plan` branch merged into `main`.

### The original implementation plan (BUILD-PLAN §12, ~18 wks part-time)
| Phase | Weeks | Content | Gate (kill if failed) |
|---|---|---|---|
| **P0** ✅ | 1 | Walking skeleton, 1 ticker, daily bars | Runs |
| **P1** ⏭ | 2–4 (47 h + 24 h upstream) | Point-in-time data spine: PIT store, `event_ts`+`available_at` everywhere, corp actions, exchange calendars, PIT universe w/ delisted names (SP500+NDX+DJIA+HSI ≈1,150 securities from 2008), DQ scoring, DuckDB/Parquet lake on R2, VPS ingest, 3 AWS Lambdas (EDGAR, FRED, watchdog). Upstream: Fin-Lambda absorbs 2 myFinData crons. | a) adj-close reconciles vs Tiingo (50-name sample); b) 2015 universe contains dead companies; c) leakage suite green |
| **P2** | 4–6 | All Tier-0 generators (families A–F), HDBSCAN in ATR space, zone identity + state machine, triple-barrier labels, level-reaction DB, **matched-control experiment** | **THE gate:** real zones beat matched-distance placebos, per distance decile, CI>0, ≥2 regimes, ≥3 families — else kill/pivot |
| **P3** | 7–10 | Model ladder rungs 0–6: baselines → hist. frequency → logistic → **LightGBM multi-task** → MC paths → isotonic calibration; walk-forward w/ purge+embargo; trials.jsonl | Calibrated LGBM beats logistic (Brier, CI>0), ECE<0.05, slope ∈[0.85,1.15] |
| **P4** | 11–14 | **Agent layer**: MCP tools, agent loop, verifier, API, reports; enrichment (options/GEX from in-house chains, EDGAR text, sector) each via ablation; HK generalization | Guardrail suites pass; each module ΔBrier>0 or removed; HK calibrates w/o arch change |
| **P5** | 15–18 | Challenger (TCN/Transformer — ships only if it beats LGBM OOS), ACI conformal, meta-ensemble, trading sim + Deflated Sharpe | DSR survives trial count |
| **P6** | ongoing | Friday post-close production loop, forecast store, weekly scoring, drift monitors | — |

### Key decisions already baked in
D1 no new data purchases (in-house MySQL `histdailyprice7` + `OptionChains`
yfinance-mirror, R2, VPS, Lambda); D2 US first, HK = P4 generalization test;
D4 spine per security: MySQL → yfinance → Tiingo → Stooq, never spliced; D6
DuckDB-over-Parquet lake, MySQL read-only; D10 two repos (Fin-Lambda writes
MySQL, this repo reads); A2 store traded prices, adjust point-in-time on read
(yfinance has no traded-price series — AAPL 4:1 split case); LLM = planner +
narrator only; matched-control placebo is the central evidence gate; LightGBM
production, DL challenger.

---

## Part 2 — New implementation plan

### What changes vs the docs' plan, and why
The docs' P1 is a 47 h, four-host build (DigitalOcean MySQL + Hostinger VPS +
Cloudflare R2 + AWS Lambda) plus a 24 h upstream migration in a second repo —
**before a single label or model exists**. That is heavy for where the project
actually is: P2's matched-control gate (the make-or-break evidence that S/R
works at all on daily bars) needs *labels and zones*, not infrastructure.
The new plan **flips the order: prove the premise on the box you already have,
then buy infrastructure only for a premise that passed.**

**Flip:** data spine *decanted* — M2/M3-lite first (thin, local), M4–M6/R2/
Lambda/upstream **deferred behind the P2 gate**. Nothing in the P2 or P3 gates
depends on R2, Lambdas, or 1,150 securities.

### Guiding rules (unchanged from BUILD-PLAN — they are the project's armor)
1. Frozen constants in `thresholds.yaml`, test-locked to BUILD-PLAN.
2. Leakage is a type error: `event_ts`/`available_at` on every row, `as_of`
   filtered reads, no unfiltered path.
3. Walk-forward only, purged CV + embargo; trials.jsonl from day one.
4. Every metric stratified by distance decile; matched-control is THE gate.
5. Layer discipline L0→L5 enforced by `test_no_upward_imports`.
6. Each phase ends at its gate with an explicit kill criterion.

### Stage A — P1-lite: local PIT spine (est. 12–16 h) — *replaces doc M0–M8 for now*
*Objective: labels can be computed honestly for the whole US universe on this box.*

| # | Task | Detail | Exit |
|---|---|---|---|
| A1 | Config & secrets | `SR_HISTORY_START`, MySQL DSN, Tiingo token in `.env`; `markets.yaml` universe = SP500+NDX+DJIA (HK deferred to P4) | `.env.example` + config green |
| A2 | `SessionCalendar` (XNYS/XHKG) | via `exchange_calendars`; sessions, half-days, closures | `test_calendar` |
| A3 | Local lake v0 | DuckDB + Parquet **on local disk** (`data/lake/`); `LakeWriter` idempotent, partitions rewritten deterministically; `AsOfQuery` filter | `test_lake_replay` |
| A4 | MySQL extract → traded prices | Read `histdailyprice7` read-only; **split-state classifier** (applied / not-applied / ambiguous = DQ blocker) → recover traded prices (§4.6.1); `load_audit`-style `available_at` = owner's load time | `test_split_state`, `test_mysql_extract` |
| A5 | Corporate actions + PIT adjust | yfinance split/dividend actions for listed; **Tiingo free (500 sym/30d)** for ≈350 delisted; adjust on read only | `test_adjust`, `test_raw_reconstruct` |
| A6 | Universe, point-in-time | Hand-curated `curated/index_membership.csv` (SP500 2010→ priority; NDX/DJIA follow), delisted names included, EDGAR Form 25/15 evidence | **gate b** on SP500: ≥60 departed 2015 members |
| A7 | `PITStore` + DQ v0 | Only-read path: `available_at ≤ as_of` or exception; DQ score gates labelling | **gate c** leakage suite on defined features |
| A8 | `sr p0 --store` | P0 reads through PITStore incl. one delisted name (XLNX @ 2021-06-30) — the survivorship case yfinance cannot run | manual + test |

**Gate = doc P1 gates a/c on SP500 scope (Tiingo 50-name reconciliation) + b for SP500 only.**
**Kill/descope:** if curation cannot reach 90% coverage per year → hand-verified
smaller universe; do NOT proceed survivorship-biased.
**Deferred to Stage D:** R2, Hostinger ingest, Lambda fetchers/watchdog,
Fin-Lambda migration, HSI, options landing.

### Stage B — P2: zones, labels, matched control (est. 20–25 h) — *the decision point*
| # | Task | Detail | Exit |
|---|---|---|---|
| B1 | Generators A–F | structure (multi-k swings, PDH/PWH, 52w, gaps), round, volume profile, VWAP (+anchored), pivots/Fib/Bollinger, KDE/GMM | unit tests per family |
| B2 | HDBSCAN clustering | ATR-normalized space; **not** the naive tiling P0 used; learned width `q` per (market × vol decile) | `test_cluster` upgrade |
| B3 | Zone identity + state machine | weekly matching ≤0.25 ATR + provenance; UNTESTED→TOUCHED→HOLD/BREAK, polarity flips | `test_identity` |
| B4 | Triple-barrier labels | touch/hold/break/reaction/time, δ=0.25·ATR, R_min=0.5·ATR, H=5 | `test_labels` |
| B5 | Level-reaction DB | all zones × universe × history ≈ 3M rows, `event_ts`+`available_at` | row-count + DQ check |
| B6 | **Matched-control experiment** | K placebos per real zone at same d±ε, same width, no provenance; hold rate + reaction per distance decile × regime × vol decile; bootstrap CI; BH-FDR; logged in trials.jsonl | **THE GATE** |

**Gate (unchanged, from BUILD-PLAN §12 P2):** real zones beat matched placebos
per distance decile, CI excluding zero, ≥2 regimes, ≥3 generator families.
**Kill:** no family beats placebo → restrict to families that worked, drop to
intraday horizon, or stop. **No ML before this table exists.**

### Stage C — P3-lite: models + calibration (est. 25–30 h)
- Rungs 0–6: unconditional base rates by distance decile → rule baselines →
  historical frequency → logistic (~30 feat) → **LightGBM multi-task** (touch/
  hold/break/reaction/T_break) → MC path engine (GARCH(1,1)+block bootstrap +
  overnight gaps + event-jump mixture) → isotonic per (market × regime ×
  distance decile).
- Walk-forward expanding, annual retrain, purge + embargo ≥ H + max lookback.
- `research/trials.jsonl` + leakage suite in CI from the first rung.
- **Gate:** LGBM beats logistic (Brier, CI>0); ECE<0.05 in 3 largest strata;
  calibration slope ∈ [0.85, 1.15]; matched-control lift preserved after
  calibration. **Kill:** ML adds nothing → ship the statistical engine
  (legitimate outcome).

### Stage D — scale out *only if B and C passed* (the deferred doc-P1 remainder)
R2 as canonical lake + write-once raw; Hostinger VPS ingest + systemd timers;
3 Lambdas (EDGAR, FRED, watchdog); Fin-Lambda upstream migration (shadow →
cutover); HSI universe; options history landing (≈50 underlyings). Effort per
doc §17: ≈ 35 h + 24 h upstream. Rationale to defer: none of it gates B/C, and
if B fails, none of it is ever needed.

### Stage E — P4: agent layer (unchanged in shape, per BUILD-PLAN §10)
MCP tools (`resolve_security`, `run_forecast`, `get_attribution`, …), agent
loop (deterministic steps 1/3/4/5; LLM only source-selection + narrative),
5 guardrail test suites (numeric grounding regex, no-forecast-without-tool,
leakage at tool boundary, replay determinism, refusal path), publication
thresholds (P(touch)≥0.60 ∧ P(hold)≥0.65 ∧ conf≥0.70 ∧ DQ≥0.80), top-2 per
side. Then enrichment modules one at a time, each through the rung-7 ablation
gate: options/GEX (in-house chains), EDGAR text features, sector/market, HK.

### Execution mechanics (for either of us — agent or Thomas)
- Stack per docs: uv, Python 3.11, Polars, pytest+Hypothesis, ruff, mypy.
- Pre-commit gate on every milestone: `uv run ruff check src tests && uv run mypy && uv run pytest`.
- Each task: failing test → minimal impl → green → commit → HISTORY.md entry.
- Load-bearing tests are never weakened (test_config frozen constants,
  test_no_upward_imports, replay byte-identical, leakage, immutable cache).
- Working on the `dev` profile / Kanban `t_5994097a` once unblocked; repo stays
  on GitHub `Neural-Matrix-LLC/Support-Resistance-Agent` (or migrate to
  thomas-choi/scout org later — Thomas's call).

### Timeline summary
| Stage | Est. hours | Gate |
|---|---|---|
| A — P1-lite local spine | 12–16 | leakage suite + Tiingo recon (SP500 scope) |
| B — P2 zones/labels/matched-control | 20–25 | **THE decision gate** |
| C — P3-lite models/calibration | 25–30 | LGBM beats logistic, ECE<0.05 |
| D — scale-out (deferred doc-P1) | ~35+24 | jobs unattended, watchdog green, restore drill |
| E — P4 agent layer | per doc | 5 guardrail suites |

**Total to the honest product decision: A+B ≈ 32–41 h** (vs 71 h in the docs'
P1+P2 ordering) — and the premise (S/R works on daily bars) is settled by week
2–3 instead of month 2.

### Open questions for Thomas (answer with the review) — REVISED 2026-10-29 PM

1. ~~Confirm the flip~~ — **answered**: storage on Fin-Lambda MySQL, R2 = events only; `fin-deep-data` is the collector (not `fin-cron-data`).
2. **Design review (this doc's §4 rev):** SR_Technical_Document.md v0.5 §4 re-planned in place — approve before Stage-A coding?
3. **DO MySQL access:** create `sr_reader` (SELECT-only) + allow-list this box's IP?
4. **Tiingo free tier** still the plan for delisted-US actions + recon sample?
5. **Fin-Lambda owner items** (not SR blockers): U6 cutover — note `serverless.yml` still has the four live schedules `enabled: false`; the 2008 prepend (U2b); U7 archive; R2 news-token 403 fix.
6. **Scope of Stage A universe:** SP500-only first, or all three US indexes at once? (Recommended: SP500 first, NDX/DJIA in Stage B prep.)
7. **Git remote:** keep `Neural-Matrix-LLC/...` or migrate to `thomas-choi/`? (Cosmetic; either works.)
8. Budget for Tiingo free tier is assumed fine ($0, 500 sym/30 d). Any objection?

---

# REV 2 — 2026-10-29 (evening): Fin-Lambda reviewed; storage decision

**Thomas's directives:** (1) **data storage = Fin-Lambda's MySQL** (`GlobalMarketData`/`Trading`), with **news/events in Cloudflare R2**; (2) review what Fin-Lambda has done, then re-review the plan.

## What Fin-Lambda has actually done (verified 2026-10-29)

- **PLAN-SR-UPSTREAM Phases A–F: DONE** — deployed 2026-10-01 as the new python3.13 service `Ops/fin-deep-data` (own serverless.yml, env, layers, tests; shares no file with `fin-cron-data`).
- **All 10 collector functions ported to py3.13** (last five on 2026-10-11: cronHandler→stock_snapshot, optHandler→opt_snapshot, FXrate, fff, news); py3.13 + MySQL 8.4 migration complete (commit `91505e0`, 2026-10-14). 426 unit tests passing per HISTORY.
- **Shadow run (G1/U5) LIVE since 2026-10-06**: `eodDaily` (18:30+19:00 ET) writes `histdailyprice7_shadow` + `corp_action_daily`; `optChainEOD` (17:40 dispatch + shards/sweeps) writes `OptionChains_shadow` + raw chains → R2; `statusReport` 20:00 → SNS e-mail. `load_audit` rows with exact `finished_at` per run.
- **Membership collector**: `portAssetsHandlerv2` fetches SP500+NDX100+**DJIA+HSI** (schedule disabled pending cutover).
- Plus: FX daily EOD + FX spot, US rates (H.15), Fama-French 3-factor, US+Asia **15-min bars** (`histminprice`), stock/options snapshots, news → R2 (hourly).

**Open items in Fin-Lambda (owner-run, flagged, not blocking SR Stage A):**
1. `serverless.yml` still says `enabled: false` on the four live schedules — a redeploy silently kills the shadow run.
2. `optChainEOD`'s 19:40 sweep DISABLED (half-enablement artefact in the shadow diff).
3. Account Lambda concurrency quota = 10 (needs L-B99A9384 → 1000 before full shard fan-out).
4. **`portAssetsHandler` old+new BOTH DISABLED → SP500/NDX100 membership updates stopped** (§5.12; route (a) per-data-set cutover fixes it).
5. News → R2 writes 403 on every object — R2 token lacks Object Read/Write; fix in Cloudflare dashboard + redeploy (HISTORY 2026-10-14).
6. Pending: finish 10-session shadow diff → U6 cutover → U2b 2008 prepend → U7 cache archive.

## Family A–G × Fin-Lambda coverage map

| SR generator family (BP §6.2) | Needs | Fin-Lambda source | Status |
|---|---|---|---|
| **A** price structure (swings, PDH/PWH, 52w, gaps, pivots) | daily OHLCV, traded prices | `histdailyprice7` (eodDaily; 857 sym V4/V5; delisted kept) | ✅ covered (2008 prepend pending) |
| **B** round numbers | daily closes | same | ✅ covered |
| **C** volume profile (POC/VAH/VAL/HVN/LVN) | intraday vol ideally | daily bars ✅; **`histminprice` 15-min US bars exist** → true daily VP possible | ✅ + bonus (15-min) |
| **D** VWAP (+anchored) | session OHLCV×V | daily approx ✅; 15-min exact | ✅ |
| **E** pivots/Fib/Bands/GARCH σ | daily + risk-free rate | bars + `USRates` (H.15) | ✅ covered |
| **F** statistical (KDE/GMM) | daily bars | bars | ✅ covered |
| **G** options (OI strikes, call/put wall, gamma flip) | EOD chains + IV + OI + underlying | `OptionChains` (optChainEOD; lastPrice>0.05, OI>p25 filter; IV+OI+UnderlyingPrice stored) + `options_snapshot` | ⚠️ covered **without greeks** — gamma/walls must be computed SR-side from IV+OI (Black-Scholes); underlyings ≈50 US names within V4 |
| (P4) text features / events | news, filings | news → **R2** (403 fix pending); **EDGAR: NOT collected** | ⚠️ news pending token; **EDGAR/FRED must be fetched SR-side → R2** (as events), not via Lambda (account quota) |
| Universe (PIT) | membership history 2010→ | `Trading.portfolio_assets_info` = **current-only** collector (v2 disabled; DJI/HSI rows stale-manual) | ⚠️ **forward updates only** — SR still must curate `index_membership.csv` history 2010→ |

## Plan changes (Rev 1 → Rev 2)

1. **Stage A re-cut from "local lake build" → "PIT read layer over Fin-Lambda MySQL."** No Parquet lake as canonical storage (Thomas: storage lives in Fin-Lambda; R2 = news/events only). SR gets `AsOfQuery` + `PITStore` that query MySQL **read-only** filtered by `load_audit.finished_at ≤ as_of` (Fin-Lambda now provides the `available_at` SR's D6 objection assumed missing). Local Parquet is an **ephemeral compute cache** for walk-forward training, rebuilt deterministically, never canonical. D6 amended accordingly.
2. **Stage D shrinks from ~59 h to ~15–20 h:** no R2 lake, no VPS ingest host, no SR Lambdas. What remains: SR-side EDGAR+FRED fetchers (cron on this box → R2 `events/` prefix), plus *helping Thomas close Fin-Lambda items 1–6* (owner-run).
3. **Options history lands in Stage A now** (was P4): `OptionChains` already flows nightly into MySQL. Family G stays ablation-gated at P4; only the *storage* moved earlier.
4. **15-min bars upgrade:** `histminprice` enables exact daily volume profiles + approach-velocity features at touch (BP §7.2) — flag as a candidate feature, still gate-admitted.
5. **Stages B, C, E unchanged** (matched-control gate remains the decision point).
6. New action items for Thomas (Fin-Lambda, owner-run): fix `serverless.yml` enabled flags or don't redeploy; resolve R2 token 403; raise concurrency quota; schedule the cutover week; run 2008 prepend after cutover.

**Revised timeline:** Stage A (PIT read layer + universe curation) 10–14 h → Stage B 20–25 h → Stage C 25–30 h. Still ≈ A+B ≈ 30–39 h to the honest go/no-go.
