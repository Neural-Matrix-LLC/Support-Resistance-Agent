"""NaiveClusterer (§3.6.4)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sr_agent.levels.cluster import NaiveClusterer
from sr_agent.levels.generators.base import ALWAYS_AVAILABLE, CandidateLevel


def lvl(
    level: float, source: str = "swing_high_k1", family: str = "A", half: float = 0.1
) -> CandidateLevel:
    return CandidateLevel(
        level=level,
        lower=level - half,
        upper=level + half,
        source=source,
        family=family,
        timeframe="1D",
        formed_at=date(2026, 1, 2),
        available_at=ALWAYS_AVAILABLE,
    )


def test_two_levels_0_4_atr_apart_merge_0_6_do_not() -> None:
    cl = NaiveClusterer()  # eps 0.5
    near = cl.cluster([lvl(90.0), lvl(90.4)], atr=1.0, spot=100.0)
    far = cl.cluster([lvl(90.0), lvl(90.6)], atr=1.0, spot=100.0)
    assert len(near) == 1 and near[0].n_sources() == 2
    assert len(far) == 2 and all(z.n_sources() == 1 for z in far)


def test_dense_ladder_does_not_chain_into_one_cluster() -> None:
    # Rungs 0.125 ATR apart across ±3 ATR: single linkage would give one cluster
    # containing the spot (and no zones); the diameter rule tiles it in ≤0.5-ATR groups.
    rungs = [lvl(97.0 + 0.125 * i, "round_0.5", "B") for i in range(49)]
    zones = NaiveClusterer(max_per_side=100).cluster(rungs, atr=1.0, spot=100.0)
    assert zones and {z.side for z in zones} == {"support", "resistance"}
    assert all(z.width_atr <= 0.5 + 0.2 + 1e-9 for z in zones)


def test_zone_geometry_and_side() -> None:
    zones = NaiveClusterer().cluster(
        [lvl(90.0, "swing_low_k1", "A"), lvl(90.3, "round_10", "B"), lvl(110.0, "swing_high_k1")],
        atr=2.0,
        spot=100.0,
        ticker="TEST",
    )
    s = next(z for z in zones if z.side == "support")
    r = next(z for z in zones if z.side == "resistance")
    assert s.zone_id == "TEST-S-P0-01" and r.zone_id == "TEST-R-P0-01"
    assert (s.lower, s.upper, s.center) == pytest.approx((89.9, 90.4, 90.15))
    assert s.distance_atr == pytest.approx((90.15 - 100.0) / 2.0)
    assert s.width_atr == pytest.approx(0.5 / 2.0)
    assert (
        s.n_sources() == 2 and s.n_families() == 2 and s.sources() == ["round_10", "swing_low_k1"]
    )
    assert r.distance_atr > 0


def test_cluster_containing_spot_is_dropped_and_sides_capped() -> None:
    levels = (
        [lvl(100.0), lvl(100.05)]
        + [lvl(100.0 - 2 * i) for i in range(1, 8)]
        + [lvl(100.0 + 2 * i) for i in range(1, 8)]
    )
    zones = NaiveClusterer().cluster(levels, atr=1.0, spot=100.0)
    assert not any(z.contains(100.0) for z in zones)
    assert sum(z.side == "support" for z in zones) == 4
    assert sum(z.side == "resistance" for z in zones) == 4
    dists = [abs(z.distance_atr) for z in zones]
    assert dists == sorted(dists)
    assert [z.zone_id for z in zones if z.side == "support"] == [f"S-P0-0{i}" for i in range(1, 5)]


def test_empty_input() -> None:
    assert NaiveClusterer().cluster([], atr=1.0, spot=100.0) == []


@settings(max_examples=200)
@given(
    st.lists(st.floats(min_value=50.0, max_value=150.0), min_size=1, max_size=40),
    st.floats(min_value=0.5, max_value=5.0),
)
def test_zones_cover_members_and_never_contain_spot(levels: list[float], atr: float) -> None:
    spot = 100.0
    zones = NaiveClusterer(max_per_side=1000).cluster([lvl(x) for x in levels], atr=atr, spot=spot)
    for z in zones:
        assert not z.contains(spot)
        assert all(z.lower <= c.level <= z.upper for c in z.provenance)
        assert (z.side == "support") == (z.center < spot)
        span = z.provenance[-1].level - z.provenance[0].level
        assert span / atr <= 0.5 + 1e-9  # diameter rule: no chaining
