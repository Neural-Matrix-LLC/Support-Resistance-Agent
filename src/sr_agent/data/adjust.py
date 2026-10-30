"""Point-in-time adjuster (§4.6.1): traded prices in, split-adjusted out on read.

Raw convention (measured 2026-09-24, confirmed by the AAL 2010 evidence):
the first load of a symbol is split-rescaled, later rows are traded prices.
With per-row load dates (Fin-Lambda `load_audit` from 2026-10-06; §4.6.1
inference before that), the adjustment factor folds only the actions whose
ex-date is strictly after the row's own load date:

    raw_t = Close_t · Π_{t < ex_u ≤ L_t} r_u

so the stored close is reconstructed from the traded price by dividing out
exactly the events that happened between the session and the load.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl


@dataclass(frozen=True)
class CorporateAction:
    ex_date: date
    action_type: str  # split | bonus | dividend | special_dividend | rights | spinoff | delist
    ratio: float      # split ratio (new/old); dividends use cash_amount instead
    cash_amount: float = 0.0


def split_factor(action: CorporateAction) -> float:
    """The r_u of the doc formula raw_t = Close_t · Π r_u: a 2:1 split stores
    half the pre-split traded price, so recovering raw MULTIPLIES by ratio."""
    if action.action_type in ("split", "bonus", "spinoff"):
        return action.ratio
    return 1.0


def cash_dividend_factor(close: float, action: CorporateAction) -> float:
    """Cash dividend r_u: stored = raw × (1 − d/close) → raw = stored / (1−d/close),
    i.e. the factor MULTIPLIES by 1/(1 − d/close) (> 1)."""
    if action.action_type not in ("dividend", "special_dividend", "rights") or close <= 0:
        return 1.0
    denom = 1.0 - action.cash_amount / close
    if denom <= 1e-12:  # a ≥100 % dividend is a data error, not an adjustment
        raise ValueError(f"dividend {action.cash_amount} vs close {close}: factor collapse")
    return 1.0 / denom


def adjust_frame(
    bars: pl.DataFrame,
    actions: list[CorporateAction],
    load_dates: dict[date, date],  # session → the load date that made it visible
) -> pl.DataFrame:
    """Return `raw` (traded) prices: P_t = Close_stored,t · Π_{t<ex_u≤L_t} F_u.

    `bars` needs session/open/high/low/close/volume + the per-row load date.
    Dividends apply to close only; splits apply to all four prices. The frame
    must be sorted ascending by session. Deterministic; pure (no I/O).
    """
    if bars.is_empty():
        return bars
    actions_sorted = sorted(actions, key=lambda a: a.ex_date)
    out = bars.with_columns(
        pl.col("open").alias("raw_open"),
        pl.col("high").alias("raw_high"),
        pl.col("low").alias("raw_low"),
        pl.col("close").alias("raw_close"),
    )
    sessions = out["session"].to_list()
    closes = out["close"].to_list()
    raw_open: list[float] = []
    raw_high: list[float] = []
    raw_low: list[float] = []
    raw_close: list[float] = []
    for i, (s, c) in enumerate(zip(sessions, closes, strict=True)):
        load = load_dates.get(s, s)
        f_split = 1.0
        f_cash = 1.0
        for a in actions_sorted:
            if s < a.ex_date <= load:  # strictly after the session, at/before load
                f_split *= split_factor(a)
                f_cash *= cash_dividend_factor(c, a)
        f = f_split * f_cash
        if f == 0.0:
            raise ValueError(f"adjustment factor collapsed to 0 at {s}")
        # raw = stored · f (see split_factor/cash_dividend_factor docstrings)
        raw_open.append(out["open"][i] * f)
        raw_high.append(out["high"][i] * f)
        raw_low.append(out["low"][i] * f)
        raw_close.append(c * f)
    return out.with_columns(
        pl.Series("raw_open", raw_open, dtype=pl.Float64),
        pl.Series("raw_high", raw_high, dtype=pl.Float64),
        pl.Series("raw_low", raw_low, dtype=pl.Float64),
        pl.Series("raw_close", raw_close, dtype=pl.Float64),
    )


def adjusted_to_latest(bars: pl.DataFrame, actions: list[CorporateAction]) -> pl.DataFrame:
    """`bar_daily_adj_latest` semantics: total-return adjusted to the newest
    action. NOT point-in-time; excluded from PITStore (§4.6.1)."""
    if bars.is_empty():
        return bars
    factor = pl.lit(1.0)
    for a in sorted(actions, key=lambda x: x.ex_date):
        if a.action_type in ("split", "bonus", "spinoff"):
            factor = factor / max(split_factor(a), 1e-12)
        elif a.action_type in ("dividend", "special_dividend", "rights"):
            # multiplicative close-relative on each ex-date session
            pass  # handled per-row below
    out = bars.with_columns(pl.when(pl.col("close") > 0).then(factor).otherwise(1.0).alias("_f"))
    return out.with_columns(
        (pl.col("close") * pl.col("_f")).alias("adj_close"),
        (pl.col("open") * pl.col("_f")).alias("adj_open"),
    ).drop("_f")
