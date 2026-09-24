"""`sr p0` end to end on a cached synthetic file — the P0 gate, offline."""

from __future__ import annotations

import re
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sr_agent.cli import app, run_p0
from sr_agent.data.ingestion import load_bars
from sr_agent.data.ingestion.stooq import StooqSource

runner = CliRunner()

ROW = re.compile(
    r"^(TEST-[SR]-P0-\d\d)\s+(support|resistance)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
    r"\s+(-?[\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)"
)


def _run(cached_stooq: Path, *extra: str):
    args = [
        "p0",
        "TEST",
        "--data-dir",
        str(cached_stooq),
        "--source",
        "stooq",
        "--offline",
        "--as-of",
        "2026-09-11",
        *extra,
    ]
    return runner.invoke(app, args)


def test_gate_exit_zero_with_support_and_resistance(cached_stooq: Path) -> None:
    t0 = time.perf_counter()
    result = _run(cached_stooq)
    elapsed = time.perf_counter() - t0
    assert result.exit_code == 0, result.output
    assert elapsed < 10.0
    rows = [ROW.match(line) for line in result.output.splitlines()]
    rows = [m for m in rows if m]
    sides = {m.group(2) for m in rows}
    assert {"support", "resistance"} <= sides
    for m in rows:
        p_touch = float(m.group(10))
        assert 0.0 < p_touch < 1.0, m.group(0)
        lower, upper, center = (float(m.group(i)) for i in (3, 4, 5))
        assert lower <= center <= upper
        assert (m.group(2) == "support") == (float(m.group(6)) < 0)
        assert int(m.group(8)) >= int(m.group(9)) >= 1
    assert "window: 2026-09-14 .. 2026-09-18  (5 sessions)" in result.output
    assert "seed=0" in result.output and "paths=10000" in result.output


def test_replay_is_byte_identical(cached_stooq: Path) -> None:
    a = _run(cached_stooq, "--paths", "3000")
    b = _run(cached_stooq, "--paths", "3000")
    strip = lambda s: "\n".join(line for line in s.splitlines() if not line.endswith("s"))  # noqa: E731
    assert a.exit_code == b.exit_code == 0
    assert strip(a.output) == strip(b.output)  # only the timing line may differ
    c = _run(cached_stooq, "--paths", "3000", "--seed", "7")
    assert "seed=7" in c.output and strip(c.output) != strip(a.output)


def test_missing_cache_offline_is_a_clean_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["p0", "NOPE", "--data-dir", str(tmp_path), "--source", "stooq", "--offline"]
    )
    assert result.exit_code == 1
    assert "error: no cached stooq file" in result.output


def test_unknown_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["p0", "X", "--data-dir", str(tmp_path), "--source", "nope"])
    assert result.exit_code == 1 and "unknown source" in result.output


def test_run_p0_is_pure_on_bars(cached_stooq: Path) -> None:
    bars = load_bars(
        "TEST", "US", date(2026, 9, 11), cached_stooq, source=StooqSource(), offline=True
    )
    r1 = run_p0(bars, n_paths=2000, seed=0)
    r2 = run_p0(bars, n_paths=2000, seed=0)
    assert r1.report == r2.report and r1.zones == r2.zones
    assert r1.n_candidates > 0 and set(r1.probs) == {z.zone_id for z in r1.zones}
    assert any(z.n_families() == 2 for z in r1.zones) or all(z.n_families() == 1 for z in r1.zones)


def test_dump_csvs_reproduce_the_report_offline(cached_stooq: Path, tmp_path: Path) -> None:
    """`--dump DIR` writes every intermediate; the §3.6 formulas re-derived from the
    CSVs alone must reproduce the report's zones and probabilities."""
    import polars as pl

    out = tmp_path / "dump"
    result = _run(cached_stooq, "--paths", "2000", "--dump", str(out))
    assert result.exit_code == 0, result.output
    assert f"dumped 6 files to {out}" in result.output
    names = {"run.csv", "bars.csv", "candidates.csv", "zones.csv", "triples.csv", "paths.csv"}
    assert {p.name for p in out.iterdir()} == names

    run = pl.read_csv(out / "run.csv").row(0, named=True)
    bars = pl.read_csv(out / "bars.csv", try_parse_dates=True)
    cands = pl.read_csv(out / "candidates.csv", try_parse_dates=True)
    zones = pl.read_csv(out / "zones.csv")
    triples = pl.read_csv(out / "triples.csv")
    paths = pl.read_csv(out / "paths.csv")
    spot, atr = float(run["spot"]), float(run["atr20"])

    # bars.csv: ATR₂₀ at as_of is the last row; TR_t = max(H−L, |H−C₋₁|, |L−C₋₁|)
    assert bars.height == run["n_bars"] and bars["atr20"][-1] == pytest.approx(atr)
    h, lo, c = (bars[k].to_numpy() for k in ("high", "low", "close"))
    tr_hand = max(h[5] - lo[5], abs(h[5] - c[4]), abs(lo[5] - c[4]))
    assert bars["tr"][5] == pytest.approx(tr_hand)
    assert bars["atr20"][20] == pytest.approx((19 * bars["atr20"][19] + bars["tr"][20]) / 20)

    # candidates.csv: point-in-time, ATR units, and the zone each one landed in
    assert cands.height == run["n_candidates"]
    assert (cands["available_at"] <= datetime(2026, 9, 11, 23, 59, 59, tzinfo=UTC)).all()
    assert (cands["level_atr"] - cands["level"] / atr).abs().max() < 1e-9
    assert set(cands["family"]) == {"A", "B"}
    assigned = cands.filter(pl.col("zone_id").is_not_null() & (pl.col("zone_id") != ""))
    assert set(assigned["zone_id"]) == set(zones["zone_id"])

    # zones.csv: geometry = §3.6.4 applied to the members named in candidates.csv
    for z in zones.iter_rows(named=True):
        members = assigned.filter(pl.col("zone_id") == z["zone_id"])
        assert members["level"].mean() == pytest.approx(z["center"])
        assert members["lower"].min() == pytest.approx(z["lower"])
        assert members["upper"].max() == pytest.approx(z["upper"])
        assert (members["level"].max() - members["level"].min()) / atr <= 0.5 + 1e-9
        assert not (z["lower"] <= spot <= z["upper"])
        assert (z["side"] == "support") == (z["center"] < spot)
        assert z["n_sources"] == members.height
        # P(touch) = mean over paths of 1[∃ j: L_j ≤ U and H_j ≥ L], from paths.csv
        touched = (
            paths.with_columns(
                ((pl.col("low") <= z["upper"]) & (pl.col("high") >= z["lower"])).alias("hit")
            )
            .group_by("path")
            .agg(pl.col("hit").any())
        )
        assert touched["hit"].mean() == pytest.approx(z["p_touch"])
    assert zones.height == sum(1 for line in result.output.splitlines() if ROW.match(line))

    # triples.csv / paths.csv: τ over the last 500 sessions; day 1 uses C_0 = spot
    assert triples.height == min(500, bars.height - 1) and paths.height == 2000 * 5
    day1 = paths.filter(pl.col("step") == 1)
    ratios = set((triples["c_over_prev_close"] * spot).round(6).to_list())
    assert all(round(v, 6) in ratios for v in day1["close"].to_list()[:50])
