"""CSV dump of every intermediate of a P0 run, so each formula in §3.6 can be
re-derived offline in a spreadsheet or notebook (`sr p0 TICKER --dump DIR`).

Files written into `DIR` (one run = one directory; all UTF-8, comma-separated):

  bars.csv        session, OHLCV, available_at, tr (§3.6.1 TR_t), atr20 (ATR_t)
  candidates.csv  every CandidateLevel with its meta columns, level_atr = level/ATR₂₀,
                  distance_atr = (level − spot)/ATR₂₀, and zone_id (blank when the
                  cluster contained the spot or was beyond the 4-per-side cut)
  zones.csv       the report rows: geometry, provenance counts, P(touch), P(L<L), P(H>U)
  triples.csv     τ_s = (H_s/C_{s−1}, L_s/C_{s−1}, C_s/C_{s−1}) the bootstrap draws from
  paths.csv       the simulated bars, one row per (path, step): high, low, close
  run.csv         one row: ticker, market, as_of, last_session, spot, atr20, n_paths, seed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

from sr_agent.data.bars import Bars
from sr_agent.levels.atr import atr20, true_range
from sr_agent.levels.generators.base import CandidateLevel
from sr_agent.levels.zone import Zone
from sr_agent.reporting.render import ZoneProbabilities
from sr_agent.simulate.monte_carlo import CLOSE, HIGH, LOW, bar_triples

_META_COLUMNS = ("k", "confirm_sessions", "atr_at_formation", "step", "rank")


@dataclass(frozen=True)
class P0Dump:
    """Everything `run_p0` computed, in the order the pipeline produced it."""

    bars: Bars
    atr: float
    candidates: list[CandidateLevel]
    zones: list[Zone]
    probs: dict[str, ZoneProbabilities]
    paths: np.ndarray
    lookback: int
    n_paths: int
    seed: int
    files: tuple[str, ...] = field(
        default=("run.csv", "bars.csv", "candidates.csv", "zones.csv", "triples.csv", "paths.csv")
    )


def bars_frame(bars: Bars) -> pl.DataFrame:
    df = bars.df
    tr = true_range(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())
    return df.with_columns(pl.Series("tr", tr, dtype=pl.Float64), atr20(bars))


def candidates_frame(
    candidates: list[CandidateLevel], zones: list[Zone], atr: float, spot: float
) -> pl.DataFrame:
    zone_of = {id(c): z.zone_id for z in zones for c in z.provenance}
    rows = [
        {
            "level": c.level,
            "lower": c.lower,
            "upper": c.upper,
            "source": c.source,
            "family": c.family,
            "timeframe": c.timeframe,
            "formed_at": c.formed_at,
            "available_at": c.available_at,
            "level_atr": c.level / atr,
            "distance_atr": (c.level - spot) / atr,
            "zone_id": zone_of.get(id(c), ""),
            **{m: c.meta.get(m) for m in _META_COLUMNS},
        }
        for c in sorted(candidates, key=lambda c: c.level)
    ]
    schema: dict[str, pl.DataType] = {
        "level": pl.Float64(),
        "lower": pl.Float64(),
        "upper": pl.Float64(),
        "source": pl.Utf8(),
        "family": pl.Utf8(),
        "timeframe": pl.Utf8(),
        "formed_at": pl.Date(),
        "available_at": pl.Datetime("us", "UTC"),
        "level_atr": pl.Float64(),
        "distance_atr": pl.Float64(),
        "zone_id": pl.Utf8(),
        "k": pl.Float64(),
        "confirm_sessions": pl.Int64(),
        "atr_at_formation": pl.Float64(),
        "step": pl.Float64(),
        "rank": pl.Int64(),
    }
    return pl.DataFrame(rows, schema=schema)


def zones_frame(zones: list[Zone], probs: dict[str, ZoneProbabilities]) -> pl.DataFrame:
    rows = [
        {
            "zone_id": z.zone_id,
            "side": z.side,
            "lower": z.lower,
            "upper": z.upper,
            "center": z.center,
            "distance_atr": z.distance_atr,
            "width_atr": z.width_atr,
            "n_sources": z.n_sources(),
            "n_families": z.n_families(),
            "p_touch": probs[z.zone_id].p_touch,
            "p_low_below": probs[z.zone_id].p_low_below,
            "p_high_above": probs[z.zone_id].p_high_above,
            "sources": ",".join(z.sources()),
        }
        for z in zones
    ]
    schema: dict[str, pl.DataType] = {
        "zone_id": pl.Utf8(),
        "side": pl.Utf8(),
        "lower": pl.Float64(),
        "upper": pl.Float64(),
        "center": pl.Float64(),
        "distance_atr": pl.Float64(),
        "width_atr": pl.Float64(),
        "n_sources": pl.Int64(),
        "n_families": pl.Int64(),
        "p_touch": pl.Float64(),
        "p_low_below": pl.Float64(),
        "p_high_above": pl.Float64(),
        "sources": pl.Utf8(),
    }
    return pl.DataFrame(rows, schema=schema)


def triples_frame(bars: Bars, lookback: int) -> pl.DataFrame:
    triples = bar_triples(bars, lookback)
    sessions = bars.df["session"].tail(triples.shape[0])
    return pl.DataFrame(
        {
            "session": sessions,
            "h_over_prev_close": triples[:, HIGH],
            "l_over_prev_close": triples[:, LOW],
            "c_over_prev_close": triples[:, CLOSE],
        }
    )


def paths_frame(paths: np.ndarray) -> pl.DataFrame:
    n_paths, horizon, _ = paths.shape
    return pl.DataFrame(
        {
            "path": np.repeat(np.arange(n_paths), horizon),
            "step": np.tile(np.arange(1, horizon + 1), n_paths),
            "high": paths[:, :, HIGH].ravel(),
            "low": paths[:, :, LOW].ravel(),
            "close": paths[:, :, CLOSE].ravel(),
        }
    )


def run_frame(dump: P0Dump) -> pl.DataFrame:
    b = dump.bars
    return pl.DataFrame(
        {
            "ticker": [b.ticker],
            "market": [b.market],
            "as_of": [b.as_of],
            "last_session": [b.last_session],
            "spot": [b.spot],
            "atr20": [dump.atr],
            "n_bars": [len(b)],
            "n_candidates": [len(dump.candidates)],
            "n_paths": [dump.n_paths],
            "seed": [dump.seed],
            "lookback": [dump.lookback],
        }
    )


def write_p0_dump(dump: P0Dump, out_dir: Path) -> list[Path]:
    """Write every file in `P0Dump.files` into `out_dir` (created if missing)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "run.csv": run_frame(dump),
        "bars.csv": bars_frame(dump.bars),
        "candidates.csv": candidates_frame(dump.candidates, dump.zones, dump.atr, dump.bars.spot),
        "zones.csv": zones_frame(dump.zones, dump.probs),
        "triples.csv": triples_frame(dump.bars, dump.lookback),
        "paths.csv": paths_frame(dump.paths),
    }
    written: list[Path] = []
    for name in dump.files:
        path = out_dir / name
        frames[name].write_csv(path)
        written.append(path)
    return written
