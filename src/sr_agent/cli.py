"""`sr` command line. P0: `sr p0 TICKER` wires loader → ATR → generators →
clusterer → Monte Carlo → report."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
from dotenv import load_dotenv

from sr_agent.config import load_market, load_thresholds
from sr_agent.data.bars import Bars
from sr_agent.data.calendars import next_sessions
from sr_agent.data.ingestion import SOURCES, default_source_name, load_bars, make_source
from sr_agent.levels.atr import atr_at_as_of
from sr_agent.levels.cluster import NaiveClusterer
from sr_agent.levels.generators.base import CandidateLevel
from sr_agent.levels.generators.round import RoundNumberGenerator
from sr_agent.levels.generators.structure import SwingGenerator
from sr_agent.levels.zone import Zone
from sr_agent.reporting.export import P0Dump, write_p0_dump
from sr_agent.reporting.render import ZoneProbabilities, render_report
from sr_agent.simulate.monte_carlo import BootstrapPathSimulator

app = typer.Typer(help="Support & Resistance agent", no_args_is_help=True)

DEFAULT_DATA_DIR = Path(os.environ.get("SR_DATA_DIR", "data"))


@dataclass(frozen=True)
class P0Result:
    bars: Bars
    atr: float
    candidates: list[CandidateLevel]
    zones: list[Zone]
    probs: dict[str, ZoneProbabilities]
    paths: np.ndarray
    n_paths: int
    seed: int
    lookback: int
    report: str

    @property
    def n_candidates(self) -> int:
        return len(self.candidates)

    def dump(self) -> P0Dump:
        return P0Dump(
            bars=self.bars,
            atr=self.atr,
            candidates=self.candidates,
            zones=self.zones,
            probs=self.probs,
            paths=self.paths,
            lookback=self.lookback,
            n_paths=self.n_paths,
            seed=self.seed,
        )


def run_p0(bars: Bars, n_paths: int, seed: int) -> P0Result:
    """The deterministic P0 pipeline on already-loaded bars (no I/O)."""
    thresholds = load_thresholds()
    horizon = int(thresholds["horizon_sessions"])
    as_of = bars.as_of
    atr = atr_at_as_of(bars)
    candidates = SwingGenerator().generate(bars, as_of) + RoundNumberGenerator().generate(
        bars, as_of
    )
    zones = NaiveClusterer().cluster(candidates, atr=atr, spot=bars.spot, ticker=bars.ticker)
    sim = BootstrapPathSimulator()
    paths = sim.simulate(bars, n_paths=n_paths, horizon=horizon, seed=seed)
    probs = {
        z.zone_id: ZoneProbabilities(
            p_touch=sim.p_touch(paths, z),
            p_low_below=sim.p_low_below(paths, z.lower),
            p_high_above=sim.p_high_above(paths, z.upper),
        )
        for z in zones
    }
    window = next_sessions(load_market(bars.market).calendar, as_of, horizon)
    report = render_report(
        bars.ticker,
        bars.market,
        as_of,
        bars.last_session,
        bars.spot,
        atr,
        window,
        zones,
        probs,
        n_paths,
        seed,
        len(candidates),
    )
    return P0Result(
        bars=bars,
        atr=atr,
        candidates=candidates,
        zones=zones,
        probs=probs,
        paths=paths,
        n_paths=n_paths,
        seed=seed,
        lookback=sim.lookback,
        report=report,
    )


@app.callback()
def _root() -> None:
    """`sr p0` (P0) · `sr mysql` / `sr cache` / `sr status` (P1 Stage A)."""


mysql_app = typer.Typer(help="MySQL extractor: audit, ingest (M0/M2)")
app.add_typer(mysql_app, name="mysql")


@mysql_app.command("audit")
def mysql_audit_cmd(
    data_dir: Annotated[Path, typer.Option(help="cache root; $SR_DATA_DIR")] = DEFAULT_DATA_DIR,
    offline_from: Annotated[Path | None, typer.Option(help="re-print a saved audit JSON")] = None,
) -> None:
    """M0: measure what the upstream MySQL holds (§4.5.1); saves a JSON audit."""
    from sr_agent.data.p1_ops import mysql_audit

    results = mysql_audit(data_dir, offline_from)
    for k, v in results.items():
        typer.echo(f"{k:24} {json.dumps(v, default=str)[:160]}")
    if results.get("ok") is False:
        raise typer.Exit(code=4)  # audit ran but queries failed (DB unreachable)


@mysql_app.command("ingest")
def mysql_ingest_cmd(
    symbols: Annotated[list[str], typer.Argument(help="tickers to extract")],
    data_dir: Annotated[Path, typer.Option(help="cache root")] = DEFAULT_DATA_DIR,
    table: Annotated[str, typer.Option(help="configured table key")] = "histdailyprice7",
    start: Annotated[str, typer.Option(help="YYYY-MM-DD")] = "2000-01-01",
    end: Annotated[str | None, typer.Option(help="YYYY-MM-DD; default today")] = None,
) -> None:
    """M2: per-symbol SELECTs → immutable raw extracts (never the read path)."""
    from sr_agent.data.p1_ops import mysql_ingest

    counts = mysql_ingest(list(symbols), data_dir, table, start, end)
    typer.echo(
        f"extracted {counts['symbols']} symbols, {counts['rows']} rows → {data_dir}/raw/mysql/"
    )


cache_app = typer.Typer(help="Cache rebuild + catalogue (M7)")
app.add_typer(cache_app, name="cache")


@cache_app.command("rebuild")
def cache_rebuild_cmd(
    table: Annotated[str, typer.Argument(help="e.g. histdailyprice7")],
    data_dir: Annotated[Path, typer.Option(help="cache root")] = DEFAULT_DATA_DIR,
    partition_by: Annotated[str, typer.Option(help="comma-separated partition cols")] = "Symbol",
) -> None:
    """Fold raw extracts → deterministic Parquet partitions → catalogue view."""
    from sr_agent.data.p1_ops import cache_rebuild

    res = cache_rebuild(data_dir, table, [p for p in partition_by.split(",") if p])
    sha = str(res["sha256"])
    typer.echo(f"{res['table']}: {res['rows']} rows, sha256 {sha[:12]}")


@app.command()
def status(
    data_dir: Annotated[Path, typer.Option(help="cache root")] = DEFAULT_DATA_DIR,
) -> None:
    """M8: freshness + manifest digests; exit 3 when stale (watchdog hook)."""
    from sr_agent.data.p1_ops import status as p1_status

    out = p1_status(data_dir)
    typer.echo(json.dumps(out, indent=2, default=str))
    if not out.get("ok", False):
        raise typer.Exit(code=3)



@app.command()
def p0(
    ticker: Annotated[str, typer.Argument(help="e.g. AAPL")],
    market: Annotated[str, typer.Option(help="markets.yaml key")] = "US",
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD; default today")] = None,
    seed: Annotated[int | None, typer.Option(help="MC seed")] = None,
    paths: Annotated[int | None, typer.Option(help="MC paths")] = None,
    data_dir: Annotated[Path, typer.Option(help="cache root; $SR_DATA_DIR")] = DEFAULT_DATA_DIR,
    source: Annotated[
        str | None,
        typer.Option(help=f"raw source {sorted(SOURCES)}; default {default_source_name()}"),
    ] = None,
    offline: Annotated[bool, typer.Option(help="never download; cache only")] = False,
    dump: Annotated[
        Path | None,
        typer.Option(help="write bars/candidates/zones/triples/paths CSVs into this directory"),
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False,
) -> None:
    """P0 walking skeleton: zones + bootstrap P(touch) for one ticker, printed."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    mc = load_thresholds()["p0"]["mc"]
    seed = int(mc["seed"]) if seed is None else seed
    paths = int(mc["n_paths"]) if paths is None else paths
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    t0 = time.perf_counter()
    try:
        bars = load_bars(
            ticker,
            market,
            as_of_date,
            data_dir,
            source=make_source(source or default_source_name()),
            offline=offline,
        )
        result = run_p0(bars, n_paths=paths, seed=seed)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.report)
    if dump is not None:
        written = write_p0_dump(result.dump(), dump)
        typer.echo(f"\ndumped {len(written)} files to {dump}")
    typer.echo(f"\n{len(bars)} bars, {time.perf_counter() - t0:.2f}s")


def main() -> None:
    load_dotenv()  # .env in cwd, if any; never committed (see .env.example)
    app()


if __name__ == "__main__":
    main()
