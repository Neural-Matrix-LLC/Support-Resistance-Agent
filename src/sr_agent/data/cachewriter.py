"""CacheWriter (§4.4, D6): deterministic Parquet cache under `data/lake/`.

The cache is a PURE FUNCTION of `data/raw/` + `curated/`: `rebuild(table)`
folds every raw extract in (extract_date, source, object) order and rewrites
one partition at a time. No network, no R2, no MySQL — those only produce
raw extracts. Determinism (§4.6.8): fixed fold order, no timestamps in the
data, row-group size fixed, Polars/Arrow write options fixed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

# The fold order is lexicographic over the triple (extract_date, source, object)
# — raw files are named raw/{source}/{object}/{extract_date}.csv.


@dataclass(frozen=True)
class RebuildResult:
    table: str
    partitions: int
    rows: int
    sha256: str  # over the folded frame's CSV serialization; stability check


def _fold_key(path: Path) -> tuple[str, str, str]:
    extract_date = path.stem
    obj = path.parent.name
    source = path.parent.parent.name
    return (extract_date, source, obj)


def fold_raw(raw_dir: Path, table: str) -> pl.DataFrame:
    """Fold every raw extract for `table` into one frame, in fold order.

    Later extract dates win (keep='last' after sorting) — a restatement in a
    newer file supersedes the older row for the same key.
    """
    base = raw_dir / "mysql" / table
    if not base.exists():
        raise FileNotFoundError(f"no raw extracts for {table} under {base}")
    files = sorted(base.glob("*/*.csv"), key=_fold_key)
    if not files:
        raise FileNotFoundError(f"{base}: no extract files")
    frames = [pl.read_csv(f) for f in files]
    combined = pl.concat(frames, how="vertical")
    key_cols = [c for c in ("Symbol", "Date") if c in combined.columns]
    if key_cols:
        combined = (
            combined.with_row_index("_fold_idx")
            .sort(key_cols + ["_fold_idx"])
            .unique(subset=key_cols, keep="last", maintain_order=True)
            .drop("_fold_idx")
        )
    return combined.sort(key_cols or combined.columns)


def write_partitions(
    frame: pl.DataFrame, lake_dir: Path, table: str, partition_by: list[str]
) -> list[Path]:
    """Hive-partitioned Parquet; one partition rewrite is atomic (tmp → replace)."""
    out_dir = lake_dir / table
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if partition_by and all(c in frame.columns for c in partition_by):
        groups = frame.partition_by(partition_by, as_dict=True)
        for key, g in groups.items():
            parts = key if isinstance(key, tuple) else (key,)
            sub = out_dir
            for col, val in zip(partition_by, parts, strict=False):
                sub = sub / f"{col}={val}"
            sub.mkdir(parents=True, exist_ok=True)
            target = sub / "data.parquet"
            tmp = target.with_suffix(".parquet.tmp")
            g.write_parquet(tmp, compression="zstd", statistics=True)
            tmp.replace(target)
            written.append(target)
    else:
        target = out_dir / "data.parquet"
        tmp = target.with_suffix(".parquet.tmp")
        frame.write_parquet(tmp, compression="zstd", statistics=True)
        tmp.replace(target)
        written.append(target)
    return written


def frame_sha(frame: pl.DataFrame) -> str:
    csv_text = frame.write_csv()
    return hashlib.sha256(csv_text.encode()).hexdigest()


def rebuild(
    raw_dir: Path, lake_dir: Path, table: str, partition_by: list[str] | None = None
) -> RebuildResult:
    """Fold raw → write partitions → record a local manifest. Deterministic."""
    frame = fold_raw(raw_dir, table)
    written = write_partitions(frame, lake_dir, table, partition_by or [])
    manifest_dir = lake_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    digest = frame_sha(frame)
    (manifest_dir / f"{table}.json").write_text(
        json.dumps(
            {
                "table": table,
                "rows": frame.height,
                "partitions": len(written),
                "sha256": digest,
                "rebuilt_from": [str(p) for p in (raw_dir / "mysql" / table).glob("*/*.csv")],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return RebuildResult(table=table, partitions=len(written), rows=frame.height, sha256=digest)


def refresh_catalog(catalog: Path | str, lake_dir: Path, table: str) -> None:
    """(Re)create the DuckDB view over the table's Parquet tree."""
    con = __import__("duckdb").connect(str(catalog))
    try:
        glob = str((lake_dir / table / "**" / "*.parquet").resolve())
        con.execute(
            f"CREATE OR REPLACE VIEW {table} AS "
            f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    finally:
        con.close()
