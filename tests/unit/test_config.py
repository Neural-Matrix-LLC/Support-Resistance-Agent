"""thresholds.yaml `frozen` keys must equal BUILD-PLAN; change BUILD-PLAN first."""

from sr_agent.config import load_market, load_thresholds, market_names

BUILD_PLAN_FROZEN = {
    "atr_window": 20,  # BP §7.1
    "horizon_sessions": 5,  # BP §7.1
    "delta_atr": 0.25,  # BP §7.1 δ
    "r_min_atr": 0.5,  # BP §7.1 R_min
    "dq_suppress": 0.7,  # BP §9.3
    "publish": {"p_touch": 0.60, "p_hold": 0.65, "confidence": 0.70, "dq": 0.80},  # BP §10.5
    "identity_match_atr": 0.25,  # BP §6.1
}


def test_frozen_constants_match_build_plan() -> None:
    t = load_thresholds()
    assert set(t["frozen"]) == set(BUILD_PLAN_FROZEN)
    for key, expected in BUILD_PLAN_FROZEN.items():
        assert t[key] == expected, key


def test_p0_initial_constants_present() -> None:
    p0 = load_thresholds()["p0"]
    assert p0["swing"]["k_atr"] == [0.5, 1.0, 1.5, 2.0]
    assert p0["naive_cluster"]["eps_atr"] == 0.5
    assert p0["mc"] == {"n_paths": 10000, "lookback": 500, "seed": 0}


def test_markets() -> None:
    assert market_names() == ["HK", "US"]
    us = load_market("US")
    assert (us.calendar, us.stooq_suffix, us.price_limit) == ("XNYS", ".US", None)
    assert us.yfinance_suffix == ""
    hk = load_market("HK")
    assert (hk.calendar, hk.stooq_suffix, hk.yfinance_suffix) == ("XHKG", ".HK", ".HK")
