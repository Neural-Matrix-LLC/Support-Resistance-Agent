"""Fixed-width stdout report for `sr p0` (§3.4). No LLM, no persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sr_agent.levels.zone import Zone


@dataclass(frozen=True)
class ZoneProbabilities:
    p_touch: float
    p_low_below: float
    p_high_above: float


def render_report(
    ticker: str,
    market: str,
    as_of: date,
    last_session: date,
    spot: float,
    atr: float,
    window: list[date],
    zones: list[Zone],
    probs: dict[str, ZoneProbabilities],
    n_paths: int,
    seed: int,
    n_candidates: int,
) -> str:
    lines = [
        f"{ticker} ({market})  as_of={as_of}  last_session={last_session}",
        f"spot={spot:.2f}  ATR20={atr:.4f}  candidates={n_candidates}  "
        f"paths={n_paths}  seed={seed}",
        f"window: {window[0]} .. {window[-1]}  ({len(window)} sessions)",
        "",
        f"{'zone_id':<18}{'side':<11}{'L':>9}{'U':>9}{'center':>9}{'d/ATR':>7}"
        f"{'w/ATR':>7}{'src':>4}{'fam':>4}{'P(touch)':>9}{'P(L<L)':>8}{'P(H>U)':>8}  sources",
    ]
    if not zones:
        lines.append("(no zones: every cluster contains the spot or no candidates)")
    for z in zones:
        p = probs[z.zone_id]
        lines.append(
            f"{z.zone_id:<18}{z.side:<11}{z.lower:>9.2f}{z.upper:>9.2f}{z.center:>9.2f}"
            f"{z.distance_atr:>7.2f}{z.width_atr:>7.2f}{z.n_sources():>4d}{z.n_families():>4d}"
            f"{p.p_touch:>9.3f}{p.p_low_below:>8.3f}{p.p_high_above:>8.3f}  "
            + ",".join(z.sources())
        )
    return "\n".join(lines)


def print_report(*args: object, **kwargs: object) -> None:
    print(render_report(*args, **kwargs))  # type: ignore[arg-type]
