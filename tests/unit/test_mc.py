"""BootstrapPathSimulator (§3.6.5): determinism and the two P(touch) limits."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from sr_agent.levels.atr import atr_at_as_of
from sr_agent.levels.zone import Zone
from sr_agent.simulate.monte_carlo import CLOSE, HIGH, LOW, BootstrapPathSimulator, bar_triples
from tests.conftest import bars_from_ohlcv, synthetic_ohlcv


def zone(lower: float, upper: float, spot: float, atr: float, side: str = "support") -> Zone:
    c = (lower + upper) / 2
    return Zone("Z", side, lower, upper, c, (upper - lower) / atr, (c - spot) / atr)


def test_seeded_simulation_is_byte_identical(bars600) -> None:
    sim = BootstrapPathSimulator()
    a = sim.simulate(bars600, n_paths=2000, horizon=5, seed=0)
    b = sim.simulate(bars600, n_paths=2000, horizon=5, seed=0)
    assert a.tobytes() == b.tobytes()
    c = sim.simulate(bars600, n_paths=2000, horizon=5, seed=1)
    assert a.tobytes() != c.tobytes()


def test_shapes_and_bar_consistency(bars600) -> None:
    paths = BootstrapPathSimulator().simulate(bars600, n_paths=500, horizon=5, seed=0)
    assert paths.shape == (500, 5, 3)
    assert (paths[:, :, HIGH] >= paths[:, :, LOW]).all()
    assert (paths[:, :, LOW] <= paths[:, :, CLOSE]).all()
    assert (paths[:, :, CLOSE] <= paths[:, :, HIGH]).all()
    assert (paths > 0).all()


def test_first_session_starts_from_spot(bars600) -> None:
    triples = bar_triples(bars600, 500)
    paths = BootstrapPathSimulator().simulate(bars600, n_paths=200, horizon=5, seed=0)
    ratios = paths[:, 0, CLOSE] / bars600.spot
    # Every day-1 close ratio is one of the historical close ratios.
    assert np.isin(np.round(ratios, 12), np.round(triples[:, CLOSE], 12)).all()


def test_zone_containing_spot_has_p_touch_one(gapless_bars) -> None:
    spot, atr = gapless_bars.spot, atr_at_as_of(gapless_bars)
    paths = BootstrapPathSimulator().simulate(gapless_bars, n_paths=5000, horizon=5, seed=0)
    z = zone(spot - 0.05 * atr, spot + 0.05 * atr, spot, atr)
    assert BootstrapPathSimulator.p_touch(paths, z) == 1.0


def test_zone_50_atr_away_has_p_touch_zero(bars600) -> None:
    spot, atr = bars600.spot, atr_at_as_of(bars600)
    sim = BootstrapPathSimulator()
    paths = sim.simulate(bars600, n_paths=10000, horizon=5, seed=0)
    far_up = zone(spot + 50 * atr, spot + 50.5 * atr, spot, atr, "resistance")
    far_down = zone(spot - 50.5 * atr, spot - 50 * atr, spot, atr)
    assert sim.p_touch(paths, far_up) == 0.0
    assert sim.p_touch(paths, far_down) == 0.0
    assert sim.p_high_above(paths, far_up.upper) == 0.0
    assert sim.p_low_below(paths, far_down.lower) == 0.0


def test_nearby_zone_has_interior_probability(bars600) -> None:
    spot, atr = bars600.spot, atr_at_as_of(bars600)
    sim = BootstrapPathSimulator()
    paths = sim.simulate(bars600, n_paths=10000, horizon=5, seed=0)
    z = zone(spot - 1.2 * atr, spot - 1.0 * atr, spot, atr)
    p = sim.p_touch(paths, z)
    assert 0.0 < p < 1.0
    # A zone touched from above must have had a low below its upper edge.
    assert p <= sim.p_low_below(paths, z.upper) + 1e-12


def test_lookback_limits_triples() -> None:
    bars = bars_from_ohlcv(synthetic_ohlcv(120, seed=4))
    assert bar_triples(bars, 50).shape == (50, 3)
    assert bar_triples(bars, 500).shape == (119, 3)  # fewer bars than lookback: use all


def test_too_few_bars() -> None:
    bars = bars_from_ohlcv(synthetic_ohlcv(1, seed=4), as_of=date(2026, 9, 11))
    with pytest.raises(ValueError, match="at least 2 bars"):
        bar_triples(bars, 500)
