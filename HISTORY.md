# HISTORY

Every code, configuration, or architectural change to this repository, in
reverse-chronological order. See `CLAUDE.md` for the rule this file follows.

---

## 2026-09-24 — P1 plan: owner review of the upstream migration (docs only)

**Goal.** Apply the owner's four review points on the Fin-Lambda / myFinData plan (tech doc §4.5.7, §4.6.1, §4.8; BUILD-PLAN §17.2 A7–A8, §17.3, §17.4).

- **yfinance ≥ 0.2.51.** Confirmed: `auto_adjust=True` by default, so O/H/L/C come back split- and dividend-adjusted and `Adj Close` is removed. L1 now says so; the port pins `auto_adjust=False`.
- **15-min Lambda limit.** Both ports run as `n` round-robin shards plus a sweep. A time guard stops starting new symbols with < 120 s left and marks the rest `skipped`. Sizing: `n = ⌈T_total/(0.6·900 s)⌉` from measured per-symbol durations. Options default to `OPT_SHARDS=3` (≈ 50 underlyings × 10–25 s ≈ 8–20 min sequentially). Chains are written per underlying, and a late sweep capture keeps its own `available_at`.
- **Status report.** New Lambda `statusReport` (U9), Mon–Fri 20:00 ET, by e-mail and R2 `status/latest.json`. One line per data set: DataName (table), last data date, last run date/time, status (ok/partial/error/stale), symbols ok/expected, rows. It reads the new view `v_load_status`; `load_audit` gains `table_name`, `segment`, `n_ok`, `n_expected`. U10 adds audit rows to the five other daily handlers. SR's `sr status` (S5) prints the same format.
- **Start date 2008 in `.env`.** `FIRSTTRAINDTE="2008/01/01"` (Fin-Lambda) and `SR_HISTORY_START=2008-01-01` (here). A one-off prepend run (U2b) inserts 2008–09 for listed symbols with `INSERT IGNORE`. §4.6.1 generalises to a per-row load date, `raw_t = Close_t·Π_{t<ex_u≤L_t} r_u`, with a 2009/2010 seam check. A8 is no longer pending: names delisted before the prepend keep a 2010 start, and a 2010/2011 index-year is evaluated only if ≥ 90 % of its members have a full lookback.

**Effort.** SR 46 → 47 h (M7 + `sr status`); upstream 16 → 24 h (U2b 1.5, U3 +1, U4 +0.5, U9 3, U10 2).

**Tests.** No code change; 59 offline tests unchanged. Planned additions:
- `test_split_state.py`: a prepend seam case;
- `test_status.py`;
- Fin-Lambda: shard, time-guard and sweep cases in the options handler test, `test_status_report_handler.py`, and an audit-row test per handler.

---

## 2026-09-24 — P1 plan: Fin-Lambda reuse and myFinData migration (docs only)

**Goal.** Fold the owner's existing collectors into the P1 plan. That means `Fin-Lambda/Ops/fin-cron-data` (ten Lambdas) and the two myFinData cron jobs that load `histdailyprice7` and `OptionChains` (`eoddata_ext.sh` 21:10, `optchain-PM.sh` 21:40). Decide the repository split and count the new modules.

**Decisions** (tech doc §4.5.7, D10; BUILD-PLAN §17.2 A7–A8).

- **Two repositories.** Fin-Lambda owns every MySQL writer and absorbs the two cron jobs as Lambdas `eodDaily` and `optChainEOD`. The cutover follows a 10-session shadow run; myFinData is then archived. This repo stays read-only on MySQL. The contract is data (tables and semantics); code is ported, never imported. There is no third repository for the spine.
- **Modules.** No new SR collector beyond the five in the P1 design. Upstream: two ported Lambdas, one extension (`portAssetsHandler` + DJIA/HSI), and two new tables (`load_audit`, `corp_action_daily`). SR changes S1–S4: `load_audit`-triggered extract with exact `available_at`, a membership diff, post-cutover actions, and a loader-cache import.
- **Reuse catalogue.** Twelve upstream assets classified: consumed, ported, pattern, P4 candidate, or never consumed (snapshot tables cannot be point-in-time).

**Findings from reading the loader code** (tech doc §4.5.7 L1–L7).

- **L1.** `auto_adjust` is unpinned; the loader works only on yfinance < 0.2.51.
- **L2.** It runs on host-local cron: 16:10 ET in winter if the host is UTC.
- **L3.** It writes one `to_sql` per list with errors swallowed.
- **L4.** History starts at 2010-01-01, so there are no 2008–09 bars. This leads to A8, pending M0; the recommendation is labelling from each security's 500th session.
- **L5.** Index members outside `current_symbols_V2` are never collected.
- **L6.** No load time is written.
- **L7.** The option-field semantics must be kept identical.
- The local myFinData checkout is not the production copy (logs end 2024-06, config names `histdailyprice6`, no crontab here). **U0 finds the production host.**
- The loader's raw CSV cache dates each symbol's first load exactly (local copy: 181/183 on 2023-04-26). This adds `security_master.mysql_first_load_date`, which turns §4.6.1's inference into a check.

**Effort.** SR 44 → 46 h (M0 +0.5, M3 +0.5, M4 +1). The upstream track is ≈ 16 h in Fin-Lambda, in parallel and not gating P1.

**Tests.** No code change; 59 offline tests unchanged. Planned additions:
- `tests/integration/test_upstream_contract.py`;
- `load_audit` `available_at` cases in `test_mysql_extract.py`;
- the first-load override case in `test_split_state.py`;
- the membership diff case in `test_universe.py`;
- one pytest file per new Fin-Lambda Lambda, under that repo's rules.

---

## 2026-09-24 — P1 plan: MySQL loader is append-only (docs only)

**Goal.** Use the owner's answer that the `histdailyprice7` loader only appends new days and never re-downloads history after a split.

**Design consequences** (tech doc §4.6.1, §4.6.2, §4.6.7, §4.7; BUILD-PLAN §17.2 A2).

- **Two segments per security.** The first-load backfill is rescaled for splits before the backfill date `b`; appended rows are traded prices. The split-state rule now also requires the append-only signature: applied splits all precede non-applied ones, and a violation is a `split_state` blocker. It records the bracket `b̂` in `security_master` (`mysql_backfill_lo/hi`).
- **`AdjClose` is dropped entirely.** On appended rows it equals `Close`, so it carries no dividend information. Dividends come from actions only.
- **Gate a's a2 diagnostic changed.** It now compares the MySQL-recovered traded close with the live-yfinance-recovered traded close: same vendor, independent reconstruction path. It runs monthly (≈ 800 calls). a1 (Tiingo) remains the gate.
- **Restatements.** An overlap mismatch now means a manual edit or reload in MySQL, not a split; the security is re-extracted and the event logged.

**Tests.** No code change. `test_split_state.py` fixtures redefined around the backfill boundary: all/none/some applied, ambiguous, non-monotone.

---

## 2026-09-24 — P1 plan: MySQL audit answers folded in (docs only)

**Goal.** Record the owner's answers about the in-house data and the VPS, and adjust the P1 design to them.

**Answers.**

- Bars are in `histdailyprice7`: PK `(Date, Symbol, Exchange)`; `Open/High/Low/Close/Volume/AdjClose` as `FLOAT`.
- Delisted names are kept up to the delisting date.
- The source is yfinance, loaded every weeknight after the US close and before the HK/China open.
- Options are in `OptionChains` (yfinance `option_chain()` layout), captured daily after the US close, for ≈ 50 US stocks/ETFs.
- The VPS has 4 vCPU / 16 GB / 200 GB NVMe / 16 TB transfer.

**Design consequences** (tech doc §4, BUILD-PLAN §17).

- **Split state of the mirror.** Rows carry yfinance's split adjustment as of their load date, so a table can mix traded and rescaled rows. A new rule classifies every split from the stored jump across its ex-date as `applied`, not applied, or `ambiguous` (a DQ blocker), and recovers traded prices from that (§4.6.1). New planned test `test_split_state.py`.
- **Independence.** MySQL is yfinance, so live yfinance is no longer a reconciliation source. Gate a rests on the Tiingo 50-name sample (a1). a2 becomes a consistency check against the table's own `AdjClose`. yfinance weekly work shrinks to split/dividend actions for listed names. Tiingo now also supplies actions for ≈ 350 delisted US names (one 30-day quota window).
- **Precision.** MySQL `FLOAT` is cast exactly to `DOUBLE`. Strikes are rounded to 0.001 for stable keys.
- **Restatements.** There is no `updated_at`, so the 40-session overlap check is the only detector. Per-security re-extracts are batched because `Symbol` is not a PK prefix.
- **Options semantics** (§4.6.9):
  - `available_at = close + 330 min` (conservative until the load-finish time is measured);
  - `openInterest` → `open_interest_prev` (T-1);
  - `iv_valid` and `quote_stale` flags;
  - greeks computed later (FRED `DTB3` added to the series list);
  - a Friday-close forecast sees Thursday's chain. Whether to move the options-using forecast is a P4 decision.
- **Schedule.**
  - nightly extract Mon–Fri 22:00 ET, freshness-gated to 23:30;
  - weekly build Sat 06:00;
  - watchdog daily 07:00 and Sat 09:00.
- **Resources.** Options ≈ 1 GB per history-year, so 5 years of history is ≈ 6 GB in R2 (inside the free tier, $0). The whole lake fits on the VPS disk. The initial build is ≈ 1.5 h plus one ≈ 8 h Tiingo window. The estimate drops to ≈ 44 h; M0 shrinks to a 3 h residual audit (row counts, `Section` values, coverage, split-state spot checks, load-finish time, HK symbols).

**Tests.** No code change. Planned additions in tech doc §4.7: `test_split_state.py`, `test_options_view.py`; `test_mysql_extract.py` extended with the concrete mapping, the cast and the freshness gate.

---

## 2026-09-24 — P1 plan revised after review: universe, existing infrastructure, options, yfinance adjustment (docs only)

**Goal.** Apply the owner's review of the 2026-09-23 P1 plan:

1. Change the universe to S&P 500, Nasdaq-100, DJIA and HSI.
2. Use the existing resources: MySQL on DigitalOcean (market data), Cloudflare R2, AWS Serverless, a Hostinger VPS.
3. Use the in-house daily OHLCV and daily options data.
4. Reconsider A2, since "yfinance has both adjusted and unadjusted" prices.

**Finding on (4).** Checked live and against the cached raw file. yfinance `history(auto_adjust=False)` returns `Close` split-adjusted and dividend-unadjusted, plus `Adj Close` fully adjusted. Neither is the traded price: AAPL 2020-08-28 `Close` = 124.81, while the traded close was ≈ $499 before the 2020-08-31 4:1 split. `back_adjust=False` and `repair=False` do not change this. A2 therefore stands, reworded precisely. If the in-house MySQL stores traded prices (M0 audit), they are used directly.

**Documentation changes.**

- `SR_Technical_Document.md` v0.3.
  - §4 rewritten again:
    - a deployment view: MySQL (read-only upstream) → VPS (ingest) → R2 (canonical lake + write-once raw) ← Lambda (EDGAR/FRED fetchers + watchdog) → workstation;
    - `MySqlExtractor` (DuckDB `mysql` extension → immutable Parquet extracts), with the schema mapping in `config/sources.yaml`;
    - the `ObjectStore`/`R2Store` layer;
    - the spine chain `mysql → yfinance → tiingo → stooq_manual`;
    - an M0 audit table of what must be learned about the MySQL data;
    - `option_daily` as a view over the raw extracts, with an `available_at` rule (§4.6.9);
    - HK specifics: curated typhoon/black-rain closures, bonus and rights-issue factors, HKEXnews delisting evidence;
    - gate b reported per index;
    - resources re-sized for ≈ 1 150 securities, with options storage given as scenarios;
    - a VPS/Lambda/MySQL schedule;
    - milestones M0–M8, ≈ 46 h.
  - D1, D2, D4, D5, D6 and D9 amended.
  - §2.1/§2.2/§2.5/§2.6, Appendix A (`option_daily`, `closure_reason`, action types, `index_name` values) and Appendix B updated.
  - P4/P6 references to the CBOE archive replaced.
- `BUILD-PLAN.md` v1.2: §17 rewritten (amendments A1–A6, resource table per host, schedule); §12 P1 universe line and §5.1 note amended.
- `CLAUDE.md`: project state and standing decisions (data sources, universe) updated.

**Deviations from BUILD-PLAN.**

- The universe changes (A5, owner decision). Gate b's threshold is unchanged.
- The estimate is ≈ 46 h (Weeks 2–4 against BP's Weeks 2–3).
- The options module becomes a P4 candidate (A6); it is not built in P1.
- The CBOE archive is dropped.

**Tests.** No code change. The planned suites are updated in tech doc §4.7: new `test_mysql_extract`, `test_spine`, `test_objectstore`, `tests/unit/ops/test_lambdas.py`; HK closure and rights/bonus cases; an options leakage trap.

---

## 2026-09-23 — P1 implementation plan: resources, schedule, design amendments (docs only)

**Goal.** Turn P1 (data spine) into an implementation plan with the resources it needs: database, Cloudflare R2, compute, and operating time. Record it in `docs/BUILD-PLAN.md` (new §17) and `docs/SR_Technical_Document.md` (§4 rewritten in place).

**Findings that changed the design.**

- *yfinance has no delisted history.* `XLNX`, `TWTR`, `ATVI` and `CELG` return 0 rows (live check, 2026-09-23). A survivorship-free universe is P1's kill criterion, so delisted names are backfilled from the Tiingo free tier. Its quota is 500 unique symbols/month, 50 req/h, 1 000 req/day and 1 GB/month (confirmed). One spine source per security, never spliced.
- *Back-adjusted prices leak future splits.* yfinance history is split-adjusted through the fetch date. Used as-is, the round-number generator would build ladders on prices nobody traded at (AAPL ≈ $500 in 2020-08 shows as ≈ $125). P1 therefore reconstructs true unadjusted raw and adjusts as of the forecast date on read (`PointInTimeAdjuster`, tech doc §4.6.1). The old `bar_daily_adj.available_at = max(bar, action)` rule is dropped. That rule would have hidden all history before a later split. `bar_daily_adj` becomes `bar_daily_adj_latest`, a reconciliation-only view that `PITStore` cannot read.
- *The curated universe file was under the git-ignored `data/`.* It moves to `curated/index_membership.csv` at the repo root.

**Documentation changes.**

- `BUILD-PLAN.md` v1.1:
  - new §17: deliverables, amendments A1–A4, resources, time of operation, exit;
  - amendment note on §5.1 (spine);
  - pointer from §12 P1.
- `SR_Technical_Document.md` v0.2:
  - §4 rewritten. It covers architecture, initial and weekly flows, classes, sources, and resources §4.5.3–§4.5.6 (DuckDB sizing, R2 layout/cost/immutability, compute, run schedule). It also covers:
    - the point-in-time adjustment formula;
    - spine selection and gate a;
    - DQ, which gains a `c_ohlc` component; `c_ca` weight goes from .20 to .15;
    - universe curation and the quantified kill rule (S&P 500 coverage < 90 % in any year after the Week-7 tranche);
    - incremental ingest with restatement detection;
    - lake determinism;
    - the test plan;
    - milestones M0–M8 (≈ 38 h).
  - D4 and D5 amended, D6 cross-referenced, new D9 (R2 as a write-once mirror, never a read path).
  - §2.5, §2.6, ER diagram, Appendix A (`symbol_map`, `ingest_run`, `spine_source`, `evidence_grade`) and Appendix B updated.
- Import-linter is dropped from the P1 deliverables, because `test_layering.py` already enforces the layer rule.

**Deviations from BUILD-PLAN.** The P1 gates and kill criterion are unchanged. Full S&P 400 delisted coverage completes ≈ Week 7, not Week 3, because of the Tiingo quota. P2 starts on the S&P 500 point-in-time universe and reports coverage (BP §17.2 A3). R2 stays inside its free tier (10 GB-month) for ≈ 3–4 years. An 8 GB warning triggers a decision that would amend D1.

**Tests.** No code change, so no tests were added or removed. The P1 plan announces the new suites (tech doc §4.7): `tests/unit/data/*`, `tests/leakage/test_pit.py`, `tests/determinism/test_lake_replay.py`, `tests/unit/ops/test_backup.py`, `tests/integration/test_recon_live.py`. It also extends `test_ingestion.py::test_cache_is_immutable_and_dated` to `.csv.gz` without weakening it.

---

## 2026-09-23 — P0 regression run and first code commit

**Goal.** Close P0 in version control: re-run the full regression suite on
the working tree and commit P0 (code, tests, config, docs) to `origin/main`
as the baseline P1 builds on.

**Regression results (2026-09-23).**

- `uv run ruff check src tests` — clean; `uv run mypy` — no issues in 35 files.
- `uv run pytest` — 59 passed, 4 deselected (integration), ~2 s.
- `uv run pytest -m integration` — 2 passed (yfinance US + HK live),
  1 skipped (Tiingo: no `TIINGO_API_KEY` in this checkout), 1 xfailed
  (Stooq CSV endpoint still behind the browser challenge, as expected).

**Implementation.** No code or config change. `message.txt` (the
2026-09-18 hand-off note, superseded by this file — it predates the live
gate and the yfinance switch) is left out of the commit.

**Tests.** None added or removed.

---

## 2026-09-19 — yfinance price spine, `--dump` CSV export, partial-bar cut, formula comments

**Goal.** Follow-ups from the first live P0 run (2026-09-18, Tiingo, 9 246
bars, 8 zones): (1) replace Stooq with `yfinance` as the price spine (user
decision), (2) keep the §3.6.4 clustering fix and make every intermediate
validatable offline in CSV, (3) annotate every implemented formula with its
original from the technical document, (4) record the live gate as passed.

**Root causes found on the way (bugs, fixed here).**

- *Partial-bar leak.* Both Tiingo and yfinance serve the current session's
  half-finished bar while the market is open (yfinance marks it with an empty
  `Adj Close`). `Bars.from_frame` cut at the end of the `as_of` day only, so a
  run at 11:30 New York on 2026-09-18 saw `last_session=2026-09-18` with an
  intraday "close". The availability rule is now
  `available_at ≤ min(end_of_day(as_of), now)`, `now` defaulting to the wall
  clock and injectable (`load_bars(..., now=)`).
- *Calendar too short.* Yahoo's AAPL history starts 1980-12-12; the
  `exchange_calendars` instance was built from 1990-01-01 and `is_session`
  raised on the early rows (Tiingo starts at 1990-01-01, which hid this).
  Calendars are now built from 1960-01-01 (XHKG's lower bound; ~0.4 s once per
  process) and `is_session` returns `False` outside the calendar's range
  instead of raising, so such rows get the warned fallback stamp.
- *Unadjusted history as a level source.* With Tiingo's unadjusted columns,
  AAPL's pre-2014-split prices in the $300s fell inside ±6 ATR of today's
  spot and produced `swing_*` candidates in every zone (371 candidates vs 140
  from yfinance's split-adjusted series). Not fixed in code — it is why the
  spine is yfinance and why P1's corporate-action layer must run before any
  level generator sees Tiingo data (D4).

**Implementation.**

- `data/ingestion/yfinance.py`: `YFinanceSource` — `Ticker.history(period="max",
  auto_adjust=False, actions=False)` serialised to a CSV with header
  `Date,Open,High,Low,Close,Adj Close,Volume` so the raw cache stays text;
  `_history()` is the single network call (monkeypatched in tests); US and HK
  (`yfinance_suffix` in `markets.yaml`, numeric HK codes zero-padded to
  `0700.HK`); rows without a price are dropped in `parse`. Registered first in
  `SOURCES`; `default_source_name()` is now `"yfinance"` unconditionally —
  Tiingo stays reachable with `--source tiingo`, Stooq with `--source stooq
  --offline` on a browser download. `yfinance>=1.7` added to dependencies
  (pulls pandas, already present via `exchange_calendars`).
- `reporting/export.py`: `P0Dump` + `write_p0_dump(dump, dir)` writing
  `run.csv`, `bars.csv` (OHLCV, `available_at`, `tr`, `atr20`),
  `candidates.csv` (every `CandidateLevel`, meta columns flattened,
  `level_atr`, `distance_atr`, and the `zone_id` it landed in — blank when its
  cluster contained the spot or fell outside the 4-per-side cut),
  `zones.csv` (report rows + probabilities), `triples.csv` (the τ set),
  `paths.csv` (one row per path × step). `sr p0 --dump DIR` calls it;
  `P0Result` now carries `candidates`, `paths`, `n_paths`, `seed`, `lookback`
  (`n_candidates` became a property).
- Formula comments: `levels/atr.py`, `levels/generators/structure.py`,
  `levels/generators/round.py`, `levels/cluster.py`, `simulate/monte_carlo.py`,
  `data/bars.py`, `data/ingestion/loader.py`, `data/calendars.py` quote the
  §3.6 / §2.4 formulas in their docstrings and mark the implementing lines
  (`# ATR_t = ((n−1)·ATR_{t−1} + TR_t)/n`, `# x_i − x_first > ε`,
  `# H_j = C_{j−1}·τ.h`, …). `NaiveClusterer`'s docstring no longer argues
  with the design: §3.6.4 now states the diameter rule as the rule.
- `docs/SR_Technical_Document.md`: D2, D4 rewritten (spine = yfinance, its
  split-adjustment caveat, the Tiingo finding); §2.1/§2.2/§2.4–§2.7 catalogue
  and trees; §3.2–§3.5 module rows (`yfinance.py`, `export.py`, `load_bars`
  signature with `now`); §3.6.4 step 2 reworded as the rule plus a dated
  fix note (also records the zone overlap of `2 × 0.1·ATR` from half-width
  padding); §3.7 test list; §3.8 all boxes ticked incl. the live gate; P1–P6
  references to the Stooq spine renamed (`YFinanceIngestor`, `yfinance_daily`,
  `^GSPC`). `CLAUDE.md` (state, commands, load-bearing tests, standing
  decision, new repository rule on formula comments), `README.md`,
  `.env.example` (`TIINGO_API_KEY` now optional).

**Deviations from the design, and why.**

1. D4 changed from Stooq to yfinance on the user's instruction; CLAUDE.md's
   "yfinance is dev-only" line is superseded. The source boundary
   (`RawSource`) is unchanged, so swapping the spine again is one class.
2. §3.6.4 keeps the diameter rule from 2026-09-18; the wording in the doc is
   now the rule itself rather than an implementation note.

**Related files.** `pyproject.toml`, `uv.lock`, `.env.example`, `README.md`,
`CLAUDE.md`, `src/sr_agent/config/{markets.yaml,loader.py}`,
`src/sr_agent/data/{bars.py,calendars.py}`,
`src/sr_agent/data/ingestion/{yfinance.py,loader.py}`,
`src/sr_agent/levels/{atr.py,cluster.py,generators/structure.py,generators/round.py}`,
`src/sr_agent/simulate/monte_carlo.py`, `src/sr_agent/reporting/export.py`,
`src/sr_agent/cli.py`, `tests/**`, `docs/SR_Technical_Document.md`.

**Tests.** 63 tests, 59 offline (`uv run pytest`, ~2 s), 4 integration.

- New: `test_ingestion.py::test_yfinance_symbol_parse_and_csv_round_trip`
  (symbol mapping incl. `700 → 0700.HK`, parser, `fetch()` on a monkeypatched
  pandas history in New York and Hong Kong tz, header check),
  `::test_yfinance_empty_history_is_an_error`,
  `::test_bars_hide_the_partial_bar_of_an_open_session` (11:30 NY hides the
  bar, the close itself shows it, past `as_of` unaffected),
  `::test_load_bars_passes_now_through`;
  `test_calendars.py::test_is_session_covers_old_histories_and_never_raises`;
  `test_cli.py::test_dump_csvs_reproduce_the_report_offline` — from the six
  CSVs alone it re-derives `TR_t` and the Wilder recursion, checks every
  candidate is point-in-time and in ATR units, recomputes each zone's
  center/L/U/side/diameter from the members named in `candidates.csv`, and
  recomputes `P(touch)` from `paths.csv` with the §2.4 touch rule — matching
  `zones.csv` exactly; `test_config.py::test_markets` covers
  `yfinance_suffix`. Integration: `test_yfinance_history[AAPL-US]`,
  `[700-HK]`.
- Changed: `test_default_source_follows_token` → `test_default_source_is_yfinance`
  (the token no longer selects the source).
- Removed: none. `ruff check`, `ruff format --check`, `mypy` clean.
- Live gate: `uv run sr p0 AAPL` on yfinance, 2026-09-19 — exit 0, 11 534
  bars, 140 candidates, 8 zones (4 S / 4 R), `0.205 ≤ P(touch) ≤ 0.897`,
  1.49 s; spot 336.13 / ATR 7.4408 agree with the Tiingo run of 2026-09-18
  (7.4405). `uv run pytest -m integration`: yfinance US + HK pass (HK
  surfaced two Yahoo rows with `high < low` on `0700.HK`, 2009-12-31 and
  2010-01-15 — kept raw, noted in §2.5 for the P1 DQ score; the live test
  tolerates ≤ 0.1 % such rows), Tiingo skipped without a token, Stooq xfail.

---

## 2026-09-18 — P0 walking skeleton: `sr p0 TICKER` end to end

**Goal.** BUILD-PLAN §12 P0 / SR_Technical_Document §3: one ticker, daily
bars, swing + round-number generators, naive clustering, bootstrap Monte Carlo
`P(touch)`, printed report. Gate: it runs. This is the first code in the
repository; before it there were only `docs/`.

**Implementation.**

- Project: `pyproject.toml` (hatchling, `sr` console script), `uv` env pinned
  to Python 3.11 (`.python-version`), `ruff` + `mypy --disallow-untyped-defs`
  + `pytest` + `hypothesis`. Package under `src/sr_agent/` (src-layout; import
  paths are the documented `sr_agent.*`). Every §2.2 package exists with an
  `__init__.py` so the layering test can name all six layers now.
- `config/`: `markets.yaml` (US/HK: calendar, close, lag, tick, price limit,
  Stooq suffix, round multipliers) and `thresholds.yaml` (BUILD-PLAN frozen
  constants under a `frozen:` list, P0 initial constants under `p0:`); `loader.py`
  reads them via `importlib.resources`, cached.
- `data/`: `bars.py` (`Bars.from_frame` enforces the column set and the
  availability filter `available_at ≤ as_of` on construction — there is no
  other way to build one); `calendars.py` (`next_sessions`, exact per-session
  `session_close_utc`, `is_session` over `exchange_calendars`);
  `ingestion/` split into `base.py` (`RawSource`: `symbol/fetch/parse`),
  `cache.py` (immutable `data/raw/{source}/{SYMBOL}/{fetch_date}.csv`; same-day
  re-fetch is a no-op, a bad response never touches disk), `stooq.py`,
  `tiingo.py`, `loader.py` (`load_bars`: cache-or-fetch → parse → cut rows
  after `as_of` → stamp `available_at = session close + lag`, with the
  configured standard-time close as a warned fallback for dates the calendar
  does not know).
- `levels/`: `atr.py` (Wilder ATR, §3.6.1), `generators/base.py`
  (`CandidateLevel`, `LevelGenerator`, `ALWAYS_AVAILABLE`), `generators/structure.py`
  (`SwingGenerator`, §3.6.2 — `available_at` is the close of the confirming
  bar `t+m`, not the swing bar), `generators/round.py` (`RoundNumberGenerator`,
  §3.6.3 — ladders `e/m` plus the half-step, each rung emitted once at its
  coarsest step with `meta.rank`), `zone.py` (`Zone`), `cluster.py`
  (`Clusterer`, `NaiveClusterer`).
- `simulate/monte_carlo.py`: `PathSimulator` interface with `p_touch`,
  `p_low_below`, `p_high_above`; `BootstrapPathSimulator` (bar-triple bootstrap
  over the last 500 sessions, `numpy.random.default_rng(seed)`, vectorised).
- `reporting/render.py`: `render_report` (string) + `print_report`.
- `cli.py`: `run_p0(bars, n_paths, seed)` is the pure pipeline; `sr p0` adds
  `--as-of --seed --paths --source --offline --data-dir` and loads `.env`.
  Exit 1 with `error: …` on a missing cache, bad source or too little history.
- `.env.example` (`TIINGO_API_KEY`, `SR_DATA_DIR`); `.gitignore` now covers
  `data/` and `mlruns/`.

**Deviations from the design, and why.**

1. *Stooq is not scriptable any more.* Every Stooq host (`stooq.com`,
   `stooq.pl`, `static.stooq.com`) answers the CSV URL with a JavaScript
   proof-of-work page since (at least) 2026-09. Solving that programmatically
   would be circumventing an anti-bot check, so we do not. Instead ingestion is
   source-pluggable: `StooqSource` still parses the CSV format (a browser
   download dropped into `data/raw/stooq/AAPL.US/YYYY-MM-DD.csv` works, and the
   parser names the challenge page in its error), and `TiingoSource` (Tier-0
   free tier, `TIINGO_API_KEY`, US only, unadjusted columns) is the default
   whenever a token is set. Recorded against D4 and §3.4/§3.5 in the technical
   document. P1 must revisit the price spine (D4) with this in mind.
2. *Naive clustering uses a diameter rule, not a gap rule.* §3.6.4's
   "new cluster when `x_i − x_{i−1} > ε`" is single linkage; the round-number
   ladder (rungs 0.1–0.3 ATR apart) chains into one cluster that contains the
   spot and is dropped, so the first end-to-end run printed support zones only.
   Now a cluster starts anew when `x_i − x_first > ε`. The §3.7 test semantics
   ("0.4 ATR apart merge, 0.6 do not") are unchanged; every zone's span is
   bounded by ε. Side effect to carry into P2: the ladder tiles ±3 ATR in
   ≈0.6-ATR, single-family zones. Technical document §3.6.4 updated.
3. `Bars.atr20()` from the class diagram is `levels/atr.py:atr20(bars)` —
   L1 must not know about levels.
4. `load_bars` lives in `data/ingestion/loader.py`, not `stooq.py`, because
   there are two sources.

**Related files.** `pyproject.toml`, `.python-version`, `uv.lock`,
`.env.example`, `.gitignore`, `src/sr_agent/**`, `tests/**`, `CLAUDE.md`,
`README.md`, `docs/SR_Technical_Document.md` (§1 D4, §2.2, §3.4, §3.5, §3.6.4,
§3.7, §3.8), `HISTORY.md`.

**Tests.** 55 tests, 53 run offline by default (`uv run pytest`), 2 are
`@pytest.mark.integration` (live Tiingo, live Stooq status) and opt-in.

- The five §3.7 gate tests: `test_atr.py` (hand-computed true ranges, the
  n=3 seed/recursion by hand, n=20 against an independent loop implementation
  on a 25-bar fixture), `test_swings.py` (zig-zag with known peaks/troughs
  per `k`; `available_at > formed_at` close; confirmation time grows with `k`;
  large `k` rejected on a small amplitude; the ±6-ATR cut), `test_round.py`
  (`P = 182.4` → `{175, 180, 185, 190}` and every half-dollar inside ±3 ATR,
  170/195 excluded, rank/source per rung, Hypothesis property on `rungs_within`),
  `test_cluster.py` (0.4 merges / 0.6 does not; geometry, sides and ids; spot
  cluster dropped and 4-per-side cap; dense-ladder no-chaining; Hypothesis
  property: zones cover their members, never contain spot, span ≤ ε),
  `test_mc.py` (seeded byte-identity; shapes and H ≥ C ≥ L; day-1 ratios are
  historical ratios; zone containing spot → `P(touch) = 1.0` on a gapless
  fixture; ±50 ATR → 0.0; interior probability nearby; lookback bounds).
- `test_cli.py`: the gate itself, offline, on a 600-session synthetic cache
  (exit 0, ≥1 S and ≥1 R, every `0 < P(touch) < 1`, < 10 s, window header),
  byte-identical replay with the same seed and different with another, clean
  errors for a cache miss and an unknown source, `run_p0` purity.
- `test_ingestion.py`: both parsers, the Stooq challenge page rejected with
  the manual-download hint, Tiingo US-only and token-before-network, default
  source follows the token, cache immutability across same-day/next-day
  fetches, bad response leaves no files, `pick_cache_file` ordering and
  fallback, `available_at` stamping across DST and for an unknown session,
  offline miss, fetch-once-then-cache, point-in-time cut, `Bars.from_frame`
  invariants. `test_calendars.py`: forecast window strictly after `as_of`,
  weekend/holiday skipping, DST closes for XNYS and XHKG.
- `test_config.py`: frozen constants equal BUILD-PLAN (permanent — change
  BUILD-PLAN first). `test_layering.py`: no L(n) → L(n+k) import edge
  (permanent — move the code, do not widen it).
- No obsolete tests (first change). `uv run ruff check` and `uv run mypy`
  are clean.
- Live `uv run sr p0 AAPL` run: done by the author on 2026-09-18 with
  Tiingo (9 246 bars, 8 zones, 1.91 s); §3.8's last box ticked in the
  2026-09-19 entry above.
