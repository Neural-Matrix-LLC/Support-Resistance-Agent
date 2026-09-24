"""`sr` command line. P0: `sr p0 TICKER` wires loader → ATR → generators →
clusterer → Monte Carlo → report."""

from __future__ import annotations

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
    """Keep `sr p0 ...` as a subcommand even while it is the only one."""


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
