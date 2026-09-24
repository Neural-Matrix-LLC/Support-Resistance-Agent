"""Read-only access to the YAML constants shipped inside the package.

L0: imports nothing from the rest of sr_agent. Every phase reads its constants
through these two functions so a value has exactly one home.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True)
class MarketConfig:
    """One row of markets.yaml."""

    name: str
    calendar: str
    currency: str
    close_utc: str
    bar_publication_lag_minutes: int
    tick_size: float | None
    price_limit: float | None
    stooq_suffix: str
    yfinance_suffix: str
    round_number_multipliers: tuple[int, ...]


def _read_yaml(filename: str) -> dict[str, Any]:
    text = resources.files("sr_agent.config").joinpath(filename).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{filename}: expected a mapping at top level")
    return data


@lru_cache(maxsize=1)
def load_thresholds() -> dict[str, Any]:
    """thresholds.yaml as a plain dict (cached; treat as read-only)."""
    return _read_yaml("thresholds.yaml")


@lru_cache(maxsize=1)
def _load_markets_raw() -> dict[str, Any]:
    return _read_yaml("markets.yaml")


def load_market(name: str) -> MarketConfig:
    """markets.yaml row for `name` (e.g. "US"), as a typed value object."""
    raw = _load_markets_raw()
    if name not in raw:
        raise KeyError(f"unknown market {name!r}; known: {sorted(raw)}")
    row = raw[name]
    return MarketConfig(
        name=name,
        calendar=row["calendar"],
        currency=row["currency"],
        close_utc=row["close_utc"],
        bar_publication_lag_minutes=int(row["bar_publication_lag_minutes"]),
        tick_size=row.get("tick_size"),
        price_limit=row.get("price_limit"),
        stooq_suffix=row["stooq_suffix"],
        yfinance_suffix=str(row.get("yfinance_suffix", "")),
        round_number_multipliers=tuple(int(m) for m in row["round_number_multipliers"]),
    )


def market_names() -> list[str]:
    return sorted(_load_markets_raw())
