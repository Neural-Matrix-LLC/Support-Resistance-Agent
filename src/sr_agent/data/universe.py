"""Universe: point-in-time membership from curated CSVs (D5, §4.6.4).

`curated/index_membership.csv` is git-tracked and hand-verified; the builder
turns it into `security_master` / `symbol_map` / `universe_membership`. Every
row must carry a source_url and security_id — the loader refuses otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

MEMBERSHIP_COLUMNS = (
    "index_name",
    "ticker_at_time",
    "security_id",
    "cik_or_hkex_code",
    "start_date",
    "end_date",
    "source_url",
    "evidence_grade",
)


class UniverseError(ValueError):
    """The curated file is malformed or a required field is missing."""


@dataclass(frozen=True)
class MembershipRow:
    index_name: str
    ticker_at_time: str
    security_id: int
    cik_or_hkex_code: str
    start_date: date
    end_date: date | None
    source_url: str
    evidence_grade: str


def load_membership(curated_dir: Path) -> list[MembershipRow]:
    """Read + validate `index_membership.csv`; overlaps within one index fail."""
    path = curated_dir / "index_membership.csv"
    if not path.exists():
        return []
    df = pl.read_csv(path)
    missing = [c for c in MEMBERSHIP_COLUMNS if c not in df.columns]
    if missing:
        raise UniverseError(f"{path}: missing columns {missing}")
    rows: list[MembershipRow] = []
    for r in df.iter_rows(named=True):
        if not r["source_url"] or r["security_id"] in (None, ""):
            raise UniverseError(f"{path}: row without source_url/security_id: {r}")
        rows.append(
            MembershipRow(
                index_name=str(r["index_name"]),
                ticker_at_time=str(r["ticker_at_time"]),
                security_id=int(r["security_id"]),
                cik_or_hkex_code=str(r["cik_or_hkex_code"] or ""),
                start_date=date.fromisoformat(str(r["start_date"])),
                end_date=date.fromisoformat(str(r["end_date"])) if r["end_date"] else None,
                source_url=str(r["source_url"]),
                evidence_grade=str(r["evidence_grade"]),
            )
        )
    _check_no_overlap(rows)
    return rows


def _check_no_overlap(rows: list[MembershipRow]) -> None:
    by_index: dict[str, list[MembershipRow]] = {}
    for r in rows:
        by_index.setdefault(r.index_name, []).append(r)
    for idx, rs in by_index.items():
        # Same ticker twice at once is an error; different tickers may share an id
        # (ticker reuse over time → two ids is the normal case).
        seen: dict[str, list[tuple[date, date | None]]] = {}
        for r in rs:
            key = f"{r.security_id}:{r.ticker_at_time}"
            for s, e in seen.get(key, []):
                new_s, new_e = r.start_date, r.end_date or date.max
                if new_s <= (e or date.max) and new_e >= s:
                    raise UniverseError(
                        f"{idx}: overlapping membership for {r.ticker_at_time} "
                        f"(security {r.security_id}): {s}..{e} vs {new_s}..{r.end_date or date.max}"
                    )
            seen.setdefault(key, []).append((r.start_date, r.end_date))


def members_at(
    rows: list[MembershipRow], index_name: str, as_of: date
) -> list[MembershipRow]:
    """Point-in-time members: start ≤ as_of < end (open end = still a member)."""
    return sorted(
        (
            r
            for r in rows
            if r.index_name == index_name
            and r.start_date <= as_of
            and (r.end_date is None or as_of < r.end_date)
        ),
        key=lambda r: r.ticker_at_time,
    )


def build_security_master(rows: list[MembershipRow]) -> pl.DataFrame:
    """Distinct security ids with first-seen/last-seen intervals (deterministic)."""
    if not rows:
        return pl.DataFrame(
            schema={"security_id": pl.Int64, "first_seen": pl.Date, "last_seen": pl.Date}
        )
    seen: dict[int, list[MembershipRow]] = {}
    for r in rows:
        seen.setdefault(r.security_id, []).append(r)
    out = []
    for sid, rs in sorted(seen.items()):
        starts = [r.start_date for r in rs]
        ends = [r.end_date for r in rs if r.end_date]
        out.append(
            {
                "security_id": sid,
                "first_seen": min(starts),
                "last_seen": max(ends) if ends else None,
            }
        )
    return pl.DataFrame(out).sort("security_id")
