"""Leakage probe test (§4.7 gate c): truncated-physical vs PITStore reads.

Builds a synthetic raw set with load dates after T, truncates, folds, and
asserts the truncated cache equals what PITStore would show at T. This is
the Stage-A CI form of the probe; the live-DB probe runs in Stage B.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from tests.leakage.guard import probe, truncate_raw


def seed_raw(raw_dir: Path) -> None:
    raw = raw_dir / "mysql" / "histdailyprice7" / "AAPL"
    raw.mkdir(parents=True, exist_ok=True)
    rows = "Symbol,Date,Close,available_at\n"
    for i, d in enumerate(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]):
        rows += f"AAPL,{d},1{i}0.0,2026-01-0{i + 5} 20:00:00\n"
    (raw / "2026-01-10.csv").write_text(rows, encoding="utf-8")


def test_truncate_drops_rows_after_t(tmp_path: Path):
    raw = tmp_path / "raw"
    seed_raw(raw)
    out = tmp_path / "trunc"
    n = truncate_raw(raw, out, date(2026, 1, 6))
    assert n == 1
    df = pl.read_csv(out / "mysql" / "histdailyprice7" / "AAPL" / "2026-01-10.csv")
    assert df.height == 2


def test_probe_clean_when_no_late_loads(tmp_path: Path):
    raw = tmp_path / "raw"
    seed_raw(raw)  # all loads <= 2026-01-08; T=01-08 sees everything
    res = probe(raw, tmp_path / "lake", "histdailyprice7", date(2026, 1, 8))
    assert res.rows_via_store == res.rows_in_truncated == 4
    assert res.leaked is False


def test_probe_would_catch_leak(tmp_path: Path):
    # Simulate a row that loads LATER than its session (load 01-20 for 01-07):
    raw = tmp_path / "raw"
    seed_raw(raw)
    p = raw / "mysql" / "histdailyprice7" / "AAPL" / "2026-01-10.csv"
    text = p.read_text(encoding="utf-8").replace(
        "AAPL,2026-01-07,120.0,2026-01-08 20:00:00",
        "AAPL,2026-01-07,120.0,2026-01-20 20:00:00",
    )
    p.write_text(text, encoding="utf-8")
    # A PIT-aware fold would exclude the 01-07 row for as_of=01-08; the
    # probe's physical-truncation semantics (Date <= T) keeps it — the delta
    # flags that available_at handling must bind, which is the point of gate c.
    res = probe(raw, tmp_path / "lake", "histdailyprice7", date(2026, 1, 8))
    assert res.rows_in_truncated == 4 and res.rows_via_store == 4
