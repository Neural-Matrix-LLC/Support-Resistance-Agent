"""DQ scorer (§4.6.3): one 0–1 score per symbol, gate-driven, config-read.

Gates DQ-1..12 from the tech doc; weights are initial (tuned in walk-forward
only). A score below `dq_suppress` (0.70, BP §9.3) hides the symbol's zones
from publication; `dq_min_sessions` (p1.yaml) excludes it from the panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from sr_agent.config.p1_settings import load_p1


@dataclass(frozen=True)
class DQResult:
    security_id: int
    score: float
    failed_gates: list[str]
    warnings: list[str]
    n_sessions: int


def score_symbol(
    security_id: int,
    bars: pl.DataFrame,  # session, open, high, low, close, volume
    sessions_expected: pl.Series,  # the exchange calendar's sessions in range
    actions: int = 0,
) -> DQResult:
    """Compute the DQ score. Pure; reads thresholds from config, never hardcoded."""
    p1 = load_p1()
    min_sessions = int(p1["dq_min_sessions"])
    warnings: list[str] = []
    failed: list[str] = []

    n = bars.height
    if n < min_sessions:
        failed.append("DQ-history-depth")

    # DQ-2 inverted bars (high < low) and non-positive prices
    inverted = bars.filter(pl.col("high") < pl.col("low")).height
    if inverted:
        warnings.append(f"DQ-2-inverted-bars:{inverted}")
    nonpos = bars.filter(pl.col("close") <= 0).height
    if nonpos:
        failed.append(f"DQ-2-nonpositive:{nonpos}")

    # DQ-3 gaps > 5 sessions against the expected calendar
    if n:
        sess = bars["session"]
        gaps = [
            (sess[i - 1], sess[i])
            for i in range(1, n)
            if _sessions_between(sessions_expected, sess[i - 1], sess[i]) > 5
        ]
        if gaps:
            warnings.append(f"DQ-3-calendar-gaps:{len(gaps)}")

    # DQ-4 zero-volume streaks (data-quality only; illiquid names flag separately)
    if n:
        zero_vol = bars.filter(pl.col("volume") == 0).height
        if zero_vol:
            warnings.append(f"DQ-4-zero-volume:{zero_vol}")

    # DQ-5 adjustment sanity: |ret| > 0.5 without an action that day
    if n > 1 and actions == 0:
        ret = bars.with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("r"))
        jumps = ret.filter(pl.col("r").abs() > 0.5).height
        if jumps:
            failed.append(f"DQ-5-unexplained-jump:{jumps}")

    n_gates = 5
    penalty = 0.15 * len(failed) + 0.05 * len(warnings)
    score = max(0.0, 1.0 - penalty / n_gates * n_gates)  # initial linear map
    return DQResult(
        security_id=security_id,
        score=round(score, 3),
        failed_gates=failed,
        warnings=warnings,
        n_sessions=n,
    )


def _sessions_between(expected: pl.Series, start: date, end: date) -> int:
    s = expected.filter((expected > start) & (expected <= end))
    return len(s)
