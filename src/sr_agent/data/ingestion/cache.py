"""Immutable raw cache: `{data_dir}/raw/{source}/{SYMBOL}/{fetch_date}.csv` (§2.6, §3.5).

Files are never overwritten (design-fixed §44): a re-fetch on the same day is a
no-op and a fetch on a later day adds a new file. `pick_cache_file` prefers the
newest file with fetch_date <= as_of and falls back to the newest file at all —
a later download still contains the earlier history, and `Bars` enforces
point-in-time on rows regardless of which file they came from.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sr_agent.data.ingestion.base import RawSource

log = logging.getLogger(__name__)


def cache_dir(data_dir: Path, source: str, symbol: str) -> Path:
    return data_dir / "raw" / source / symbol


def cached_files(folder: Path) -> list[tuple[date, Path]]:
    out: list[tuple[date, Path]] = []
    for p in folder.glob("*.csv"):
        try:
            out.append((date.fromisoformat(p.stem), p))
        except ValueError:
            continue
    return sorted(out)


def pick_cache_file(folder: Path, as_of: date) -> Path | None:
    files = cached_files(folder)
    if not files:
        return None
    eligible = [p for d, p in files if d <= as_of]
    return eligible[-1] if eligible else files[-1][1]


def fetch_to_cache(
    source: RawSource, symbol: str, data_dir: Path, today: date | None = None
) -> Path:
    """Download once for `today`; an existing file for that day is left untouched."""
    folder = cache_dir(data_dir, source.name, symbol)
    target = folder / f"{(today or date.today()).isoformat()}.csv"
    if target.exists():
        return target
    text = source.fetch(symbol)  # validated by the source; a bad answer never touches disk
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    log.info("%s: cached %s -> %s", source.name, symbol, target)
    return target
