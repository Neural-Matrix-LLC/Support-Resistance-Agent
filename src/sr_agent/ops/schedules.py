"""Ops schedules for the SR data spine (§4.5.5): local cron via this file.

Entry points (called by run_data_spine.sh with the sub-command):
    ingest   — incremental re-extract for universe symbols (nightly, US close)
    rebuild  — fold raw → cache for changed tables (nightly after ingest)
    status   — freshness gate; non-zero exit alerts the ops watchdog

All knobs live in p1.yaml; nothing here is hardcoded.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]


def run_cli(args: list[str], data_dir: Path) -> int:
    """Thin wrapper so the shell runner and tests share one code path."""
    cmd = ["uv", "run", "sr", *args, "--data-dir", str(data_dir)]
    log.info("exec: %s", " ".join(cmd))
    return subprocess.run(cmd, cwd=REPO, check=False).returncode


def ingest(data_dir: Path, symbols: list[str]) -> dict[str, object]:
    """Nightly: overlap re-extract; full re-extract only on restatement."""
    rc = run_cli(["mysql", "ingest", *symbols], data_dir)
    return {"step": "ingest", "rc": rc, "date": date.today().isoformat()}


def rebuild_all(data_dir: Path, tables: list[str]) -> list[dict[str, object]]:
    """Fold every configured table; catalogue refresh is part of rebuild."""
    return [
        {"step": "rebuild", "table": t, "rc": run_cli(["cache", "rebuild", t], data_dir)}
        for t in tables
    ]


def main() -> int:
    """`python -m sr_agent.ops.schedules ingest|rebuild|status` (see module doc)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    step = sys.argv[1] if len(sys.argv) > 1 else "status"
    default_data = str(Path(__file__).resolve().parents[3] / "data")
    data_dir = Path(os.environ.get("SR_DATA_DIR", default_data))
    from sr_agent.config.p1_settings import load_p1

    p1 = load_p1()
    if step == "ingest":
        out = ingest(data_dir, [str(s) for s in p1["universe_seed_symbols"]])
        print(json.dumps(out))
        return 0 if out["rc"] == 0 else 1
    if step == "rebuild":
        outs = rebuild_all(data_dir, [str(t) for t in p1["cache_tables"]])
        print(json.dumps(outs))
        return 0 if all(o["rc"] == 0 for o in outs) else 1
    if step == "status":
        return run_cli(["status"], data_dir)
    log.error("unknown step %r (ingest|rebuild|status)", step)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
