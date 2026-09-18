# Support & Resistance Agent — Finalized Build Plan

**Version:** 1.0 (finalized)
**Date:** 14 September 2026
**Supersedes:** `docs/SR-Plan.md` (institutional proposal) and `docs/Support-Resistance-design-fixed.MD` (research spec) as the *execution* document. Both remain valid as reference catalogues.
**Scope of this document:** what we build, in what order, with what data, and the tests that decide whether each piece survives.

---

## 0. The one-paragraph version

We build an **agent that, given a ticker, returns 2–4 support zones and 2–4 resistance zones for the next 5 trading sessions, each with a calibrated `P(touch)`, `P(hold)`, `P(break)`, an expected reaction size, a confidence score, and a human-readable evidence trail.** The numbers come from a deterministic Python core (candidate-level generation → clustering → feature extraction → gradient-boosted probability models → Monte Carlo path simulation → probability calibration). The LLM is the *orchestrator and explainer*: it decides which data sources are usable for this ticker, extracts structured features from unstructured text, and writes the narrative. **The LLM never produces a price level or a probability.** We start with US large caps on daily + hourly bars, prove incremental value against deliberately hostile baselines, and only then add options, intraday microstructure, event/NLP features, deep learning, and a second market (HK).

---

## 1. Reconciling the two source documents

The two documents disagree about what kind of project this is. The finalized plan takes the **scientific spine from `Support-Resistance-design-fixed.MD`** and the **feature catalogue from `SR-Plan.md`**, and cuts the parts that are not buildable or not evidenced.

### 1.1 Kept as-is

| From | What | Why |
|---|---|---|
| design-fixed §6–7 | Zones as intervals `[L,U]`, reaction threshold `k·ATR₂₀`, breakdown at `Close < L − 0.25·ATR₂₀` | This is the single most important decision in either doc. A level is an interval with an event definition, not a line. Everything downstream depends on it. |
| design-fixed §16 | Labels: touch / hold / break / reaction magnitude / time-to-event | Correct label set. Extended below with triple-barrier semantics. |
| design-fixed §35, §67–69 | Walk-forward only, purged CV, embargo, survivorship + point-in-time universe | Non-negotiable. Violating any of these produces a model that backtests beautifully and loses money. |
| design-fixed §66 | Ablation ladder (price-only → … → full ensemble) | Promoted here into a **hard admission gate**: no module enters the ensemble without passing it. |
| design-fixed §78, §92 | "Do not start with the Transformer" | Correct and we go further: the Transformer must *beat* LightGBM out-of-sample to be deployed at all. |
| design-fixed §60, §87–88 | LLM explains, does not decide; forecasting engine separate from portfolio sizing | This is the architectural boundary the whole agent design rests on. |
| design-fixed §76 | `feature_value` + `feature_available` pairs, graceful degradation | Essential for a multi-source agent where coverage differs per ticker. |
| SR-Plan §1.1, §3.1–3.2 | Anchored volume profile, POC/VAH/VAL, HVN/LVN, adaptive-bandwidth KDE, GMM over swing points | Good candidate-level generators. Demoted from "engines" to "generators" feeding one common pipeline. |
| SR-Plan §2.1 | GEX / call wall / put wall / gamma flip | Kept as a **US-only, Phase-4, ablation-gated** module. |

### 1.2 Cut, deferred, or demoted — with reasons

| Item | Source | Decision | Reason |
|---|---|---|---|
| Vision Transformer / ConvNeXt on rendered chart images | SR-Plan §4.1 | **Cut** | Requires "500,000 manually annotated historical charts" that do not exist and would cost more than the rest of the project to create. Rendering OHLCV to pixels and asking a ViT to recover it discards precision we already have in numeric form. If spatial pattern recognition has value, a 1-D temporal conv/attention model over the raw series tests the same hypothesis at ~1% of the cost. |
| Level 2/3 limit order book, spoofing detection, order decay | SR-Plan §1.2, design-fixed §21 | **Deferred indefinitely** | Full-depth LOB history is $$$$ and ~TB/ticker-year. Not obtainable at this project's scale. We keep the *feature slots* and `orderbook_available=0` so the schema does not need to change if this ever arrives. |
| Dark pool / TRF block VWAP | SR-Plan §1.3 | **Reduced** | True dark-pool attribution is not retail-available. What *is* available is FINRA-reported off-exchange prints in the consolidated trade feed (exchange code for FINRA ADF/TRF). We compute an off-exchange block VWAP from those where a trade-level feed exists. Lower ambition, real data. |
| KDB+/q, Bloomberg B-PIPE, Refinitiv, H100 cluster, Ray across 10,000 tickers | SR-Plan §8.1 | **Cut** | Target hardware is one 16-core / 31 GB workstation with a single consumer GPU. DuckDB + Parquet + Polars handles 500 tickers × 15 years of daily and hourly bars comfortably. |
| Hand-assigned ensemble weight table (M1=20%, M2=25%, …) | SR-Plan §7.2 | **Cut** | Weights asserted with no derivation. Replaced by a learned, regime-conditioned meta-model with calibration (design-fixed §31). If a learned weight lands near those numbers, fine — but it must be learned. |
| "Target: TBR ≥ 68%" | SR-Plan §9.1 | **Cut as a target** | A number with no basis. Bounce rate is meaningless without a matched control (see §7.3) — a zone 0.2 ATR away "bounces" far more often than one 3 ATR away, for reasons that have nothing to do with the zone. Replaced by *calibration* and *lift over matched controls*. |
| Graph neural network | design-fixed §29 | **Deferred to P5-optional** | Plausible, but sector/market context can be captured by ordinary cross-sectional features first. GNN must beat those features to justify the complexity. |
| 10,000 global tickers, 11 markets at launch | both | **Deferred** | Phase 1 universe is US large/mid cap. HK added in P4 only after the US model is calibrated, because HK is the best test of whether the architecture actually generalizes (different microstructure, no 0DTE options, Stock Connect flows). |
| "Unprecedented institutional edge" framing | SR-Plan | **Cut** | Replaced with §2's honest evidence baseline and §14's success definition. |

---

## 2. What the evidence actually supports (and what it doesn't)

Neither source document grounds its ambition in the literature. This matters because it sets the realistic ceiling.

**Support for the concept:**

- Osler's FX work is the strongest direct evidence. Published support/resistance levels from six FX firms had statistically significant power to predict intraday trend *interruptions*, and that power persisted for at least five business days after publication — which happens to be exactly our horizon. Notably, *levels agreed on by multiple firms were not stronger than single-firm levels* — "no power in agreement." This is a direct warning about our confluence score (§6.4): confluence may be measuring redundancy, not independent evidence. `design-fixed §14` already flags this ("five independent signals should be worth more than five variants of the same indicator"); the Osler result says we must *test* it rather than assume it.
- Osler (2003, *Journal of Finance*) gives the **mechanism**: stop-loss and take-profit orders cluster at round numbers. Take-profit clustering produces reversals at round numbers (support/resistance behavior); stop-loss clustering produces cascades through them (breakout behavior). This is the best-evidenced causal story for why S/R exists at all — and **neither source document includes round-number features.** We add them as a first-class candidate generator (§6.2).
- Chung & Bellotti (arXiv:2101.07410) algorithmically discovered S/R levels in intraday data and found statistically significant reversal ability, that **levels with more historical bounces were more likely to reverse price again**, and that reversal probability **decays over time**. This validates two specific features: `touch_count` (design-fixed §52) and `level_age` with exponential decay (§51).

**Against, or cautionary:**

- Equity-market evidence is weaker than FX. At least one study of horizontal S/R levels in US stocks reports results consistent with market efficiency. Osler's mechanism (order clustering at round numbers in a dealer market) is strongest in FX and may attenuate in fragmented, heavily algorithmic equity markets.
- Volume-profile S/R (POC/HVN/LVN) is almost entirely practitioner literature. There is no peer-reviewed base for it. It goes in as a hypothesis with an ablation gate, not as a pillar.

**Conclusion that shapes the plan:** the realistic edge is *modest, conditional, and decays*. That makes the deliverable **calibrated probability**, not "here is the level." A well-calibrated `P(hold) = 0.58` that is genuinely 58% is a valuable, sellable product. A confident-sounding line on a chart is not.

---

## 3. Product definition

### 3.1 What the agent is

A per-ticker, on-demand analyst. Not a 10,000-ticker batch factory (that is the eventual *scaling* story, not the product). Two run modes over the same core:

- **Interactive:** `sr forecast AAPL` → full forecast in < 60 s, < $0.15 of LLM spend.
- **Scheduled:** Friday post-close batch over the universe → forecast database + cross-sectional ranking.

### 3.2 Output contract (frozen in P1, versioned thereafter)

```json
{
  "schema_version": "1.0",
  "ticker": "AAPL", "market": "US", "currency": "USD",
  "forecast_ts": "2026-09-11T20:00:00Z",
  "horizon_sessions": 5,
  "session_calendar": ["2026-09-14", ..., "2026-09-18"],
  "spot": 182.40,
  "atr20": 4.12,
  "regime": {"label": "bull_high_vol", "probs": {"strong_bull": 0.41, "...": "..."}},
  "weekly_distribution": {
    "high": {"q05": 183.1, "q50": 189.4, "q95": 198.2},
    "low":  {"q05": 168.9, "q50": 177.8, "q95": 182.1},
    "close":{"q05": 171.0, "q50": 183.3, "q95": 197.4},
    "interval_method": "ACI-conformalized, target 90%, trailing coverage 0.891"
  },
  "zones": [{
    "zone_id": "AAPL-S-2026W37-01", "side": "support",
    "lower": 178.20, "upper": 180.05, "center": 179.10,
    "width_atr": 0.45,
    "distance_atr": -0.80,
    "state": "UNTESTED", "polarity_history": ["resistance->support@2026-07-22"],
    "p_touch": 0.68, "p_hold": 0.74, "p_break": 0.26,
    "expected_reaction_atr": 1.15,
    "confidence": 0.82,
    "evidence": [
      {"source": "weekly_swing_low", "timeframe": "1W", "age_sessions": 34, "touches": 3, "weight": 0.31},
      {"source": "hvn_60d",          "timeframe": "1D", "volume_pctile": 0.94,  "weight": 0.24},
      {"source": "avwap_earnings_gap","anchor": "2026-07-31",                   "weight": 0.19},
      {"source": "round_number",     "level": 180.00,                           "weight": 0.11}
    ],
    "attribution": {"top_positive": ["confluence_independent_n", "touch_count", "sector_rs_20d"],
                    "top_negative": ["days_to_earnings", "realized_vol_pctile"]},
    "calibration_bin": {"predicted": 0.74, "historical_realized": 0.71, "n": 1843}
  }],
  "event_risk": {"score": 0.55, "drivers": [{"type": "earnings", "date": "2026-09-17", "session_offset": 4}]},
  "data_quality": {"score": 0.91, "missing_sources": ["orderbook", "darkpool"], "notes": ["options OI is T-1"]},
  "model": {"ensemble_version": "v1.4.2", "feature_version": "fs-2026-08", "trained_through": "2026-06-30"},
  "narrative": "…LLM-generated, grounded strictly in the fields above…"
}
```

**Rule:** every number in `narrative` must appear verbatim in a structured field above it. This is machine-checked (§10.4).

---

## 4. Architecture

```
┌─────────────────────────────────────── AGENT LAYER (LLM) ────────────────────────────────────┐
│  Source-selection planner · Text→structured-feature extractor · Explanation writer            │
│  Never emits: a price, a probability, a zone boundary, a confidence score.                    │
└───────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                │  MCP tool calls (typed, validated, logged)
┌───────────────────────────────▼──────────────────────────────────────────────────────────────┐
│                            DETERMINISTIC CORE (pure Python, no LLM)                          │
│                                                                                              │
│   data/          point-in-time store · corporate actions · calendars · DQ scoring            │
│     ↓                                                                                        │
│   levels/        candidate generators → ATR-space clustering → zone construction → state m/c  │
│     ↓                                                                                        │
│   features/      ~180 features across 20 groups, each with an _available flag                │
│     ↓                                                                                        │
│   models/        baselines → LightGBM multi-task → (challenger: TCN/Transformer)             │
│     ↓                                                                                        │
│   simulate/      GARCH+bootstrap Monte Carlo path engine → P(touch), path-dependent stats     │
│     ↓                                                                                        │
│   calibrate/     isotonic per stratum + ACI conformal for quantiles                           │
│     ↓                                                                                        │
│   forecast store (DuckDB, append-only, every forecast retained forever)                       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**The hard boundary is the whole point.** The 2026 consensus in financial LLM systems is explicit: LLMs must not perform the arithmetic. Direct LLM financial prediction is not merely weak, it is actively hazardous, because a plausible-looking number is indistinguishable from a correct one. So: the LLM plans and narrates; a deterministic layer validates, computes, and returns structured results.

### 4.1 Division of labour, precisely

| Task | Owner | Why |
|---|---|---|
| Which data sources are available/appropriate for this ticker | **LLM** | Genuinely a judgment call across heterogeneous coverage; cheap to verify. |
| Fetching, adjusting, aligning data | Core | Deterministic, must be reproducible. |
| Generating candidate levels | Core | Deterministic. |
| Clustering into zones | Core | Deterministic. |
| Computing probabilities | Core | The entire scientific content of the project. |
| Reading an 8-K / earnings transcript → `{guidance_change: -1, severity: 0.7, …}` | **LLM** | This is what LLMs are actually good at: structured extraction from text. Output is a *feature*, then goes through the same ablation gate as any other feature. |
| Deciding a zone's confidence | Core | Formula in §9.3. |
| Explaining the forecast | **LLM** | Grounded in SHAP attributions, verified against structured fields. |
| Answering follow-ups ("why is S2 weak?") | **LLM** + read-only tools | Can re-query the core, cannot recompute. |

---

## 5. Data sources and the degradation ladder

The user requirement is "different data sources." The design principle: **every source is optional; the model learns to work without it.** Missing sources set `*_available = 0` and are never zero-filled silently (design-fixed §76).

### 5.1 Tier 0 — free, mandatory (project works with only these)

| Source | What | Notes |
|---|---|---|
| **Stooq / Alpha Vantage / Tiingo free** | Daily OHLCV | Tiingo's free tier is usable for a full EOD research stack and its data is carefully split/dividend adjusted — the best free choice for the price spine. |
| **SEC EDGAR** (`data.sec.gov` JSON + full-text search) | Filings, 8-K/10-Q/10-K, filing timestamps | Free, official, no key. Requires a descriptive `User-Agent` and ≤10 req/s. The *filing timestamp* is our anti-leakage anchor for text features. |
| **FRED** | Rates, macro series, release calendar | Free, unlimited. |
| **CBOE daily options CSV** | Full chain snapshot incl. OI | Free download; OI is T-1. Sufficient for a Friday-close weekly GEX. |
| **Exchange calendars** (`exchange_calendars` pkg) | Sessions, half-days, holidays | Never assume 5 calendar days = 5 sessions (design-fixed §46). |

**Explicitly not relied upon:** `yfinance`. It is scraping an API Yahoo discontinued in 2017; endpoints change without notice and it is flagged unstable for 2026. Acceptable as a *convenience cross-check* in dev, never as the production spine or as a backtest source of truth.

### 5.2 Tier 1 — ~$10–30/mo, strongly recommended (unlocks P2)

| Source | What | Approx. |
|---|---|---|
| **Tiingo Power** | Clean adjusted EOD + fundamentals, 500 req/hr | ~$10/mo |
| **EODHD** | 150k+ tickers incl. HK/China/EU, EOD + splits + basic intraday | ~€20/mo |

This tier is enough for everything through Phase 3 and most of Phase 4.

### 5.3 Tier 2 — ~$200/mo, only if P2 clears its gate (unlocks intraday + options)

| Source | What | Approx. |
|---|---|---|
| **Polygon.io (now "Massive") Stocks Advanced** | Tick/minute US equities, trade-level incl. FINRA off-exchange prints, WebSocket | ~$199/mo |
| **Databento OPRA Standard** | Options tick, institutional-grade, nanosecond timestamps, 60+ venues | ~$199/mo + $1–5/GB history |

Decision rule: **do not buy Tier 2 until the Tier-1 daily-bar model has passed the P2 gate.** If daily-bar S/R carries no calibrated edge, minute bars will not rescue it, and we will have spent money to overfit faster.

### 5.4 Coverage matrix (what degrades where)

| Feature group | US lg-cap | US sm-cap | HK | China A | EU |
|---|:--:|:--:|:--:|:--:|:--:|
| Daily OHLCV, structure, VWAP, volume profile | ✅ | ✅ | ✅ | ✅ | ✅ |
| Intraday bars (Tier 2) | ✅ | ✅ | ◐ | ◐ | ◐ |
| Options / GEX | ✅ | ◐ | ◐ (no 0DTE) | ✗ | ◐ |
| Off-exchange block prints | ✅ | ✅ | ✗ | ✗ | ◐ |
| Filings / text (EN) | ✅ | ✅ | ✅ (HKEX) | ◐ | ◐ |
| Price-limit / halt rules | n/a | n/a | n/a | **±10%/±20% hard** | n/a |
| Order book | ✗ | ✗ | ✗ | ✗ | ✗ |

China A-share daily price limits are a **hard constraint on the distribution**, not a feature — the Monte Carlo engine must truncate paths at the limit, and any zone beyond the limit has `P(touch) ≈ 0` for the next session by construction. This is the single largest cross-market modelling difference and is why HK/China is the right generalization test.

---

## 6. The level engine

### 6.1 Pipeline

```
raw bars → candidate generators (N≈40 per ticker-date) → dedupe →
HDBSCAN in ATR-normalized price space → zone [L,U] with width = q·ATR (q learned) →
zone identity matching against prior week's zones → state machine update → feature extraction
```

Zone identity persistence matters (design-fixed §63–64): a zone must keep its `zone_id` week to week so we can track `touch_count`, `age`, and polarity flips (broken resistance → support). Match by center within 0.25 ATR + overlapping provenance.

### 6.2 Candidate generators

Grouped by evidence family — the grouping is used for the independence test in §6.4.

**Family A — price structure:** multi-k swing highs/lows (k ∈ {0.5, 1.0, 1.5, 2.0}·ATR, per design-fixed §9), prior day/week/month/quarter high & low, 52-week high & low, YTD extremes, consolidation boundaries, gap edges (open gaps and filled-gap boundaries), prior breakout/breakdown pivots.

**Family B — round numbers** *(new; not in either source doc)*: integer, half-integer, and decade levels scaled to the stock's price magnitude; plus strike-adjacent levels. This is the generator with the clearest documented mechanism (order clustering, Osler 2003) and it costs nothing to compute.

**Family C — volume:** POC, VAH, VAL, HVN, LVN over {5, 20, 60, 120, 252} sessions with adaptive `bin_width = c·ATR`; event-anchored profiles (anchored to earnings, gaps, 252-day extremes) per SR-Plan §1.1.

**Family D — VWAP:** session/weekly/monthly/quarterly/YTD VWAP; anchored VWAP from last major high, last major low, earnings gap, breakout, year start.

**Family E — derived/technical:** classic + Camarilla pivots (H3/H4, L3/L4), Fibonacci retracements (23.6/38.2/50/61.8/78.6) of the dominant swing, Bollinger and Keltner boundaries, GARCH(1,1) 5-session σ envelopes at ±1σ/±2σ.

**Family F — statistical:** adaptive-bandwidth KDE over historical turning points (`h = γ·ATR₁₄`), BIC-selected 1-D GMM over volume-weighted turning points — local maxima become candidates.

**Family G — options (US, P4):** high-OI call/put strikes, gamma concentration peaks (call wall / put wall), zero-gamma flip level, expiry-cluster strikes.

### 6.3 Zone width

`design-fixed §13` says width `W = q·ATR` with `q` learned from historical reaction distributions. Made concrete: fit `q` by maximizing out-of-sample log-likelihood of observed reaction points under a kernel centered on the zone, per `(market × volatility decile)` bucket. A single global `q` will be wrong — a 12% realized-vol utility and a 90%-vol biotech do not have the same zone thickness in ATR units.

### 6.4 Confluence — treated as a hypothesis, not a score

`SR-Plan §7` and `design-fixed §14` both assume more confluence = stronger level. **Osler found agreement across FX firms added nothing.** So confluence enters as *three separate features* and the model decides:

1. `n_sources` — raw count.
2. `n_independent_families` — count of distinct families A–G (a POC and a VAH from the same profile is one family, not two).
3. `redundancy_ratio` = `n_sources / n_independent_families`.

Hypothesis **H1'** (replacing design-fixed H1): *`n_independent_families` carries information; `n_sources` does not, once `n_independent_families` is controlled for.* Testable directly.

---

## 7. Labels and the evaluation protocol that decides the project

This section is the most important in the plan. Both source documents specify labels correctly and then propose evaluation that would produce a false positive.

### 7.1 Labels (horizon H = 5 sessions)

Per zone `[L,U]` observed at Friday close, with `δ = 0.25·ATR₂₀` and reaction threshold `R_min = 0.5·ATR₂₀`:

- `Y_touch ∈ {0,1}` — price enters `[L,U]` within H.
- `Y_hold ∈ {0,1}` — **defined only when `Y_touch = 1`.** After first entry, price achieves `R_min` in the favorable direction before the breach condition.
- `Y_break ∈ {0,1}` — after entry, `Close < L − δ` (support) / `Close > U + δ` (resistance) occurs first.
- `Y_reaction ∈ ℝ` — `(post-touch extreme − entry) / ATR₂₀`.
- `T_touch`, `T_react`, `T_break` — sessions to each.

This is **triple-barrier labeling** (López de Prado): upper barrier, lower barrier, time barrier at H. Stating it in those terms is not cosmetic — it is what tells us the labels overlap in time and therefore that ordinary k-fold CV leaks and inflates accuracy. Overlapping triple-barrier labels *require* purging and embargoing.

### 7.2 The conditioning trap

`P(hold)` is only observable on touched zones. Training a hold-classifier on touched samples and reporting it as `P(hold)` for all zones is a textbook selection bias: zones that get touched are systematically different (closer, in trending tape, lower realized vol on approach). We handle it explicitly:

- Model `P(touch | X)` on **all** zones.
- Model `P(hold | touch, X, approach_features)` on **touched** zones only, with approach features (design-fixed §53–54: approach velocity, consecutive down days, gap, volume acceleration, VWAP distance) that are only knowable *at* touch.
- Publish `P(hold)` as **conditional**, labeled as such. Publish `P(touch) × P(hold|touch)` separately as the joint.
- For the Friday-close forecast where approach features are unknown, integrate over approach scenarios drawn from the Monte Carlo path engine. This is a genuine reason the MC engine exists, beyond generating the quantile bands.

### 7.3 The matched-control test (the project's central gate)

**`P(touch)` is almost entirely explained by `distance / (σ·√5)`.** Any model with distance as a feature will post an impressive AUC while knowing nothing about support or resistance. The same confound contaminates bounce-rate claims: near zones "bounce" more because price loiters near them. `SR-Plan`'s "TBR ≥ 68%" target is meaningless for exactly this reason.

So the gate is a **placebo control**:

> For every real zone at distance `d` (in ATR units) with width `w` at time `t`, sample K synthetic "zones" at the same `d ± ε` and same `w` for the same ticker-date, with **no structural provenance** (no generator produced them). Compute hold rate and reaction magnitude for both.
>
> **The real zones must beat the matched placebos, per distance decile, with a bootstrap CI excluding zero.**

Reported as a table: distance decile × (real hold rate, placebo hold rate, lift, CI, n). Plus the same stratification for regime, market, and volatility decile.

Every headline metric in this project is reported **stratified by distance decile**. An unstratified AUC or bounce rate is not admissible evidence and will not appear in any report.

### 7.4 Validation mechanics

- **Walk-forward only**, expanding window, annual retrain: train ≤ Y−2, validate Y−1, test Y. Never random splits.
- **Purged k-fold with embargo** for hyperparameter search inside the training window; embargo ≥ H + max(feature lookback needed to avoid contamination).
- **Final test years untouched** until model selection is frozen.
- **Multiple-testing control:** we will test 10+ hypotheses, 7 generator families, and hundreds of features. Apply Benjamini–Hochberg FDR control to hypothesis tests; report **Deflated Sharpe Ratio** (Bailey & López de Prado) for any economic result, which corrects for selection bias, sample length, non-normality, and the number of trials attempted. Maintain a `research/trials.jsonl` log of *every* configuration evaluated — DSR requires the trial count, and a trial count reconstructed after the fact is a lie.
- **Leakage test suite** runs in CI: for each feature, assert its value at timestamp `t` is a pure function of data with `available_at ≤ t`. Every row in every table carries both `event_ts` and `available_at`.

---

## 8. Model ladder with admission gates

Nothing is deployed because it is sophisticated. Each rung must beat the rung below it, out-of-sample, with a bootstrap CI excluding zero.

| Rung | Model | Must beat | Gate metric |
|---|---|---|---|
| 0 | Unconditional base rate by distance decile | — | reference |
| 1 | Prior week's high/low; ATR bands; classic pivots; Bollinger | Rung 0 | Brier, log loss |
| 2 | Historical frequency `P(hold \| source, distance bin, regime)` | Rung 1 | Brier, calibration slope |
| 3 | Logistic regression on ~30 features | Rung 2 | Brier, log loss, ECE |
| 4 | **LightGBM multi-task** (touch / hold / break / reaction / time-to-break), ~180 features | Rung 3 | Brier, ECE, matched-control lift |
| 5 | + Monte Carlo path engine for `P(touch)` and path-dependent stats | Rung 4 | Brier on touch, quantile pinball loss |
| 6 | + isotonic calibration per `(market × regime × distance decile)` | Rung 5 | ECE, calibration slope ≈ 1 |
| 7 | + module ablations: options, intraday/VP, events/NLP, sector/market — **each admitted individually** | Rung 6 | ΔBrier with bootstrap CI > 0 |
| 8 | **Challenger:** TCN / small Transformer, multi-task + quantile head | Rung 7 | ΔBrier, pinball loss |
| 9 | Meta-ensemble + conformal | Rung 8 | ECE, coverage, DSR |

**Rung 4 is the production candidate.** Rungs 8–9 are research. If the Transformer does not beat LightGBM out-of-sample, it does not ship — the source doc says this and we are enforcing it as a merge rule, not an aspiration.

### 8.1 Feature groups (~180, not 400)

`design-fixed §49` targets 200–400 features. We target ~180. With ~500 tickers × 15 years × ~8 zones/week, the level-reaction database is ~3M rows — enough for 180 features, thin for 400, and the marginal features are mostly redundant transforms that inflate the multiple-testing burden.

Groups: `price · returns · volatility · volume · structure · vwap · volume_profile · momentum · trend · round_number · options · offexchange · market · sector · factor · macro · event · text · regime · liquidity · zone_history · approach`.

`zone_history` (touch count, prior reactions, age with learned decay `e^{−λ·age}`, polarity flips) and `approach` are the two groups most specific to this problem and most likely to carry the real signal, per Chung & Bellotti.

---

## 9. Uncertainty, calibration, confidence

### 9.1 Probability calibration
Isotonic regression fit on the validation window, per `(market × regime × distance decile)` stratum, with a minimum-n fallback to coarser strata. Report ECE and calibration curves per stratum — a globally calibrated model that is badly miscalibrated in high-vol regimes is not fit for purpose.

### 9.2 Interval calibration — conformal
For the weekly high/low/close quantiles, raw quantile-regression intervals will under-cover under regime shift. Financial time series violate exchangeability, so plain split conformal is insufficient. Use **Adaptive Conformal Inference (ACI)**, which updates the target error rate online via a feedback loop to force long-run coverage to the target, with **EnbPI** as the alternative (it refreshes the residual pool with recent conformity scores so intervals adapt to changing volatility without refitting). Both are benchmarked in P5; report realized trailing coverage in every forecast (see the output contract).

### 9.3 Confidence score
Confidence ≠ probability (design-fixed §33). Concretely:

```
confidence = w₁·model_agreement       (1 − normalized dispersion across ensemble members)
           + w₂·calibration_quality   (1 − ECE in this zone's stratum)
           + w₃·data_quality          (DQ ∈ [0,1], §5.4 coverage + freshness + integrity)
           + w₄·sample_support        (log-scaled n in the historical stratum)
           + w₅·regime_stability      (1 − PSI vs training distribution)
           − penalty(event_risk)
```
Weights fit on validation to maximize the correlation between confidence and realized per-zone Brier. If `DQ < 0.7`, suppress the zone from publication entirely.

### 9.4 Monte Carlo engine
10k–50k weekly paths per ticker: block-bootstrap of standardized residuals + GARCH(1,1) conditional variance + overnight-gap distribution + event-jump mixture (fat-tailed component activated when an earnings date falls in the window) + market-factor shock correlated via beta. Truncated at price limits for China A-shares. Produces `P(touch)`, path-dependent approach-feature distributions for §7.2, `P(Low < L)`, `P(High > R)`, and the raw quantiles that ACI then calibrates.

---

## 10. Agent layer design

### 10.1 Tools (MCP server, `sr_agent/mcp_server.py`)

| Tool | Signature (abridged) | Mutates |
|---|---|---|
| `resolve_security` | `(query) → {security_id, ticker, exchange, currency, coverage{}}` | no |
| `get_price_history` | `(security_id, start, end, bar) → dataframe_ref` | no |
| `assess_data_quality` | `(security_id, as_of) → {dq_score, per_source{}, blockers[]}` | no |
| `compute_levels` | `(security_id, as_of, families[]) → zones[]` | no |
| `run_forecast` | `(security_id, as_of, config_version) → forecast_json` | writes forecast store |
| `get_options_surface` | `(security_id, as_of) → {gex_by_strike, call_wall, put_wall, gamma_flip, available}` | no |
| `get_events` | `(security_id, window) → events[] with available_at` | no |
| `extract_text_features` | `(document_id) → structured_features{value, confidence, source, timestamp}` | writes feature store |
| `query_level_history` | `(security_id, zone_id) → prior touches/reactions/state transitions` | no |
| `get_attribution` | `(forecast_id, zone_id) → SHAP values` | no |
| `backtest_zone_family` | `(family, universe, window) → matched-control table` | no |

Tools return **typed, validated structures**. Any tool that could return a number the LLM might paraphrase also returns a `display_string` the LLM is instructed to quote verbatim.

### 10.2 Agent loop

```
1. resolve_security + assess_data_quality
2. LLM plans source set given coverage and DQ blockers          ← genuine judgment
3. get_events → if unstructured docs present, extract_text_features
4. run_forecast (deterministic; consumes everything above)
5. get_attribution per published zone
6. LLM writes narrative, grounded strictly in 4 + 5
7. Verifier pass (§10.4) → publish or reject
```

Steps 1, 3, 4, 5 are deterministic tool calls. Only 2 and 6 are LLM cognition. This keeps per-forecast LLM cost in the low cents and makes reruns reproducible.

### 10.3 Model selection
Claude Sonnet 5 (`claude-sonnet-5`) for the default loop — the reasoning required (source selection, narrative grounding) is well within its range and the cost profile suits scheduled batch runs. Claude Opus 5 (`claude-opus-5`) for the offline **research assistant** mode (reading a new market's microstructure rules, proposing new candidate generators, reviewing ablation results). Haiku 4.5 (`claude-haiku-4-5-20251001`) for high-volume `extract_text_features` over filings, where the task is narrow structured extraction. Prompt-cache the static system prompt and tool definitions; batch the filing-extraction calls.

### 10.4 Guardrails (each is a test, not a policy)
1. **Numeric grounding check:** regex every number out of `narrative`; assert each appears in the structured forecast. Fail → regenerate once → fail again → publish structured output with a templated narrative.
2. **No-forecast-without-tool:** the agent cannot emit a forecast that has no corresponding `forecast_id` in the store.
3. **Leakage guard at the tool boundary:** every data tool takes `as_of` and filters on `available_at ≤ as_of`. There is no code path to fetch unfiltered data. This makes leakage a *type error*, not a discipline problem.
4. **Replay determinism:** given `(security_id, as_of, config_version)`, `run_forecast` must produce byte-identical output. Seeded RNG for MC. Tested in CI.
5. **Refusal path:** `DQ < 0.7` or no zone clears the publication thresholds → the agent says so plainly rather than manufacturing zones. "No high-conviction levels this week" is a valid, and often correct, answer.

### 10.5 Publication thresholds
Per design-fixed §61–62, frozen before the final test:
`publish if P(touch) ≥ 0.60 and P(hold|touch) ≥ 0.65 and confidence ≥ 0.70 and DQ ≥ 0.80 and event_risk ≤ threshold`.
Rank by `P(touch) × P(hold|touch) × E[reaction] × confidence`; publish top 2 per side, up to 4 with justification.

---

## 11. Stack and repo layout

**Stack:** Python 3.11+ (current env is 3.10 — upgrade via `uv`), `uv` for env/deps, Polars + DuckDB + Parquet for data, NumPy/SciPy, scikit-learn, LightGBM, `arch` (GARCH), `hdbscan`, `exchange_calendars`, `mapie` or `puncc` (conformal), PyTorch (P5 only), MLflow for experiment tracking, Prefect for the weekly schedule, FastAPI for the API, `anthropic` SDK + `mcp` for the agent, pytest + Hypothesis for tests.

Note: the local GPU currently reports `Driver/library version mismatch`. Irrelevant until P5; fix before then or rent a GPU by the hour for the challenger model — buying hardware for this is unjustified.

```
sr_agent/
├─ config/            markets.yaml · features.yaml · models.yaml · thresholds.yaml
├─ data/              ingestion/ · adjust/ · calendars/ · quality/ · store.py
├─ levels/            generators/{structure,round,volume_profile,vwap,technical,statistical,options}.py
│                     cluster.py · zone.py · identity.py · state_machine.py
├─ features/          20 modules, one per group · registry.py (declares available_at per feature)
├─ labels/            triple_barrier.py · touch.py · hold.py · reaction.py
├─ models/            baseline.py · logistic.py · lgbm.py · survival.py · sequence.py · ensemble.py
├─ simulate/          monte_carlo.py · gaps.py · limits.py
├─ calibrate/         isotonic.py · conformal.py · confidence.py
├─ validation/        walk_forward.py · purged_cv.py · matched_control.py · ablation.py
│                     leakage.py · stress.py · dsr.py
├─ agent/             loop.py · prompts/ · verifier.py · mcp_server.py
├─ api/               main.py  (GET /forecast/{ticker})
├─ reporting/         render.py · dashboard.py
├─ research/          notebooks/ · trials.jsonl   ← every trial logged, for DSR
└─ tests/
```

---

## 12. Phase plan

Realistic for one developer at roughly 15–20 h/week. Every phase ends in a gate with an explicit **kill criterion** — a phase that fails its gate stops the project or forces a documented pivot. This is the mechanism that prevents building all 92 sections of the source spec before discovering the premise is wrong.

### P0 — Walking skeleton (Week 1)
One ticker, daily bars only, swing + round-number generators, naive clustering, MC touch probability, printed output. Ugly and end-to-end.
**Purpose:** validate the shape of the pipeline before investing in any of it. **Gate:** it runs. **Kill:** none.

### P1 — Data spine (Weeks 2–3)
Point-in-time store, `event_ts` + `available_at` on every row, corporate actions (raw preserved separately from adjusted, per design-fixed §44), exchange calendars, **point-in-time universe reconstruction including delisted names**, DQ scoring. Universe: S&P 500 + S&P 400 members as of each historical date, 2010→present.
**Gate:** (a) adjusted closes reconcile against a second source within tolerance on a 50-ticker × 200-date sample; (b) the 2015 universe contains companies that no longer exist; (c) the leakage test suite passes on all features defined so far.
**Kill:** cannot assemble a survivorship-free universe → descope to a smaller curated universe with hand-verified delistings; do not proceed with a survivorship-biased one.

### P2 — Levels, labels, and the matched-control gate (Weeks 4–6)
All Tier-0 generators (families A–F), ATR-space HDBSCAN, zone identity + state machine, triple-barrier labels, the full level-reaction database, and the §7.3 matched-control experiment.
**Gate — THE decision point:** real zones beat matched-distance placebos on hold rate and reaction magnitude, per distance decile, bootstrap CI excluding zero, in at least two distinct regimes, for at least three generator families.
**Kill:** no family beats placebo → the premise is not supported on daily bars for this universe. Options then are (i) drop to intraday (the horizon where Osler's evidence is strongest), (ii) restrict to the families that *did* work, or (iii) stop. **Do not proceed to modelling by adding features until something works.** This gate is why P2 comes before any ML.

### P3 — Baselines, LightGBM, calibration, MC (Weeks 7–10)
Rungs 0–6 of §8. Walk-forward with purge + embargo. Isotonic calibration. Full MC path engine. Ablation harness and `trials.jsonl` in place from day one.
**Gate:** calibrated LightGBM beats rung-3 logistic on Brier with bootstrap CI excluding zero, ECE < 0.05 in the three largest strata, calibration slope in [0.85, 1.15], and matched-control lift preserved after calibration.
**Kill:** ML adds nothing over historical frequency → ship the statistical engine as the product. That is a legitimate and honest outcome, and a far better one than a Transformer that fits noise.

### P4 — Agent layer + enrichment (Weeks 11–14)
MCP tools, agent loop, verifier, `GET /forecast/{ticker}`, terminal + HTML report. Then enrichment modules, each through the §8 rung-7 gate individually: options/GEX (US), events + LLM-extracted text features, sector/market context, intraday volume profile (only if Tier 2 was purchased). HK universe added here as the generalization test.
**Gate:** each module admitted or rejected on its own ΔBrier; agent passes all five §10.4 guardrail test suites; HK model calibrates without architecture changes (market embedding + feature-availability flags only).
**Kill (per module):** module fails ablation → it is removed, not "kept for completeness." Rejected modules are documented in `research/rejected.md` with their numbers, so the decision is not silently revisited.

### P5 — Challengers + economic validation (Weeks 15–18)
Sequence model (TCN/small Transformer, multi-task + quantile head), ACI/EnbPI conformal intervals, meta-ensemble, trading simulation with market-specific costs, Deflated Sharpe.
**Gate:** DL beats LightGBM OOS, or it is not deployed. Economic result survives DSR given the true trial count.
**Kill:** DSR indicates the economic result is attributable to selection → publish the forecast product as a *calibrated-probability* tool and do not make trading claims.

### P6 — Production loop (ongoing)
Friday post-close scheduled run, forecast store, weekly scoring of last week's forecast against what happened, drift monitoring (PSI, KS, Wasserstein), model registry with full governance metadata (design-fixed §58), auto-downgrade of confidence on drift.

**Total to a defensible product: ~18 weeks part-time.** Compare with the source docs' 22–25 weeks *full-time with a 7-person team* — the difference is entirely the cuts in §1.2.

---

## 13. Risk register

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | **Distance confound** produces an impressive model that knows nothing about S/R | High | §7.3 matched controls; every metric stratified by distance decile. This is the #1 way this project fails while appearing to succeed. |
| 2 | **Leakage** via `available_at` mistakes, restated fundamentals, post-close timestamps | High | Leakage as a type error (§10.4.3); CI test suite; filing timestamps from EDGAR, not news aggregators. |
| 3 | **Multiple testing** — hundreds of features × 7 families × many configs finds spurious structure | High | `trials.jsonl` from day one; BH-FDR; DSR; final test set sealed. |
| 4 | **The premise is weak in equities** (equity S/R evidence is thinner than FX) | Medium | P2 gate answers this at week 6 for ~3 weeks of work, before any ML investment. |
| 5 | **Conditioning bias** on `P(hold\|touch)` | Medium | §7.2 explicit two-stage model; conditional labeling in the output contract. |
| 6 | Free data quality (splits, bad ticks, unstable endpoints) corrupts labels | Medium | Tiingo/EODHD over yfinance; two-source reconciliation at P1; DQ score gates publication. |
| 7 | Scope creep back toward the 92-section spec | Medium | Ablation gates: nothing enters without paying for itself in ΔBrier. |
| 8 | LLM fabricates a number in the narrative | Low (given guardrails) | §10.4.1 machine verification; templated fallback. |
| 9 | Regime shift invalidates the trained model | Certain, eventually | Walk-forward retrain; PSI drift monitor; confidence auto-downgrade; ACI's online coverage correction. |
| 10 | Options/GEX module yields nothing outside mega-caps | Medium | US-only, ablation-gated, ~$200/mo deferred until P3 clears. |

---

## 14. Definition of success

Adapted from design-fixed §90, made measurable:

**Minimum (the project is worth having):**
- Published zones beat matched-distance placebo controls on hold rate, per distance decile, in ≥2 regimes, with bootstrap CI excluding zero.
- `P(hold|touch)` is calibrated: ECE < 0.05 and calibration slope ∈ [0.85, 1.15] in the three largest strata, out-of-sample, across ≥3 walk-forward test years.
- Weekly high/low conformal intervals achieve 88–92% realized coverage at a 90% target.
- Every published number is traceable to a tool call and a model version; every forecast is retained and re-scorable.

**Target (the project is valuable):**
- The above holds in a second market (HK) with no architecture change beyond market embeddings and availability flags.
- Ablation shows ≥2 enrichment modules each contribute positive ΔBrier with CI excluding zero.
- The trading simulation's Sharpe survives deflation given the true trial count, after realistic costs.

**Explicitly not success:** a good-looking chart; high in-sample R²; a Transformer that produces plausible forecasts; a handful of correct calls. The source documents both warn about this, and both then propose targets (TBR ≥ 68%, "unprecedented edge") that invite exactly that failure mode.

---

## 15. Decisions I made, and open questions for you

**Made, with rationale above — reverse any of these and tell me:**
1. US-first, HK second, other markets deferred (§1.2).
2. Tier-0/Tier-1 data at ≤ ~$30/mo through P3; Tier-2 (~$200–400/mo) only after the P3 gate (§5.3).
3. ViT-on-charts, LOB, and KDB+ cut (§1.2).
4. LightGBM is the production target; deep learning is a challenger that must win (§8).
5. Round-number generators added as a first-class family (§6.2) — the best-evidenced mechanism, absent from both source docs.
6. Confluence is a hypothesis to test, not a scoring axiom (§6.4).

**Open — these change the plan materially:**
- **Budget ceiling.** If there is no monthly budget at all, P4's options module and any intraday work are off the table and the plan ends at a daily-bar product. If ~$400/mo is fine from the start, P4 and P5 can run in parallel and the timeline compresses by ~3 weeks.
- **Horizon.** The plan is built for H=5 sessions per both docs. Osler's evidence is strongest *intraday*. If you would accept an intraday/1–2 session product, the premise is better supported and the data is cheaper to validate — but the product is a different one.
- **Is HK/China a requirement or a nice-to-have?** If A-shares are a hard requirement, the price-limit path truncation in the MC engine moves from P4 to P1, because it changes the label definitions.

---

## 16. Immediate next actions

1. `uv init` the project; Python 3.11; commit the skeleton in §11.
2. P0 walking skeleton on a single ticker (AAPL) with Stooq/Tiingo daily bars — target: end-to-end in 3 days.
3. Stand up `research/trials.jsonl` and the leakage test harness **before** the first model is fit. Both are worthless if added later.
4. Build the P1 point-in-time universe, including delisted names, 2010→present.
5. Run the §7.3 matched-control experiment as soon as P2 labels exist. Do not write a model before that table exists.

---

## Sources consulted beyond the two source documents

- Osler, C. — *Support for Resistance: Technical Analysis and Intraday Exchange Rates* (FRBNY Economic Policy Review, 2000): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=888805
- Osler, C. — *Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis* (Journal of Finance 58(5), 2003): https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588 · working paper: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.pdf
- Chung, K. & Bellotti, A. — *Evidence and Behaviour of Support and Resistance Levels in Financial Time Series* (arXiv:2101.07410): https://arxiv.org/abs/2101.07410
- *Identifying and evaluating horizontal support and resistance levels: an empirical study on US stock markets* (Applied Financial Economics 22:19): https://www.tandfonline.com/doi/abs/10.1080/09603107.2012.663469
- López de Prado, M. — *The 10 Reasons Most Machine Learning Funds Fail* (GARP): https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf · Deflated Sharpe Ratio: https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- Zaffran et al. — *Adaptive Conformal Predictions for Time Series* (PMLR v162): https://proceedings.mlr.press/v162/zaffran22a/zaffran22a.pdf
- *Conformal Prediction Algorithms for Time Series Forecasting: Methods and Benchmarking* (arXiv:2601.18509): https://arxiv.org/pdf/2601.18509
- SEC EDGAR APIs (`data.sec.gov`): https://www.sec.gov/news/press-release/2021-159
- Data provider comparisons — Databento vs Polygon 2026: https://aifinhub.io/articles/market-data-apis-compared-2026/ · Tiingo vs Polygon for indie quants: https://pickuma.com/for-dev/tiingo-vs-polygon-market-data-apis-indie-quant-2026/ · verified-availability API list: https://github.com/jeff3388/awesome-financial-data-apis
- GEX computation reference implementation: https://github.com/Matteo-Ferrara/gex-tracker · method writeup: https://perfiliev.com/blog/how-to-calculate-gamma-exposure-and-zero-gamma-level/
- *Keep the LLM Out of the Math: Deterministic Boundaries for Financial Modelling Agents*: https://dev.to/feasibilityproaiai/keep-the-llm-out-of-the-math-deterministic-boundaries-for-financial-modelling-agents-5cl7
- *RiskLabs: Predicting Financial Risk Using LLMs on Multimodal and Multi-Source Data* (arXiv:2404.07452): https://arxiv.org/pdf/2404.07452
