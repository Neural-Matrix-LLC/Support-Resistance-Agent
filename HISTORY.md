# HISTORY

Every code, configuration, or architectural change to this repository, in
reverse-chronological order. See `CLAUDE.md` for the rule this file follows.

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
