"""Analog counting for gate item 7: 'at least 3 analogous prior events on the same instrument /
timeframe, with hit-target-before-invalidation count'. Deterministic, candle-based.

An analog = a prior candle whose range touched the entry level (within `tolerance`), after which
we walk forward and record whether target or invalidation printed first (or neither within
`horizon` candles).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tape import Candle


@dataclass
class AnalogResult:
    n: int = 0
    hit_before_invalidate: int = 0
    invalidated_first: int = 0
    unresolved: int = 0
    dates: list[str] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.hit_before_invalidate / self.n if self.n else 0.0


def count_analogs(candles: list[Candle], entry: float, target: float, invalidation: float,
                  side: str = "LONG", tolerance: float = 0.005, horizon: int = 20,
                  min_gap: int = 5, exclude_last: int = 1) -> AnalogResult:
    """side LONG: target > entry > invalidation. SHORT: mirrored. exclude_last skips the live bar(s)."""
    res = AnalogResult()
    lo, hi = entry * (1 - tolerance), entry * (1 + tolerance)
    last_i = -10**9
    end = len(candles) - exclude_last
    for i in range(end):
        c = candles[i]
        if not (c.low <= hi and c.high >= lo) or i - last_i < min_gap:
            continue
        last_i = i
        res.n += 1
        res.dates.append(c.date)
        outcome = "unresolved"
        for j in range(i + 1, min(end, i + 1 + horizon)):
            f = candles[j]
            if side == "LONG":
                hit, inv = f.high >= target, f.low <= invalidation
            else:
                hit, inv = f.low <= target, f.high >= invalidation
            if hit and inv:
                outcome = "invalidated"      # same-bar ambiguity resolves against the idea
                break
            if hit:
                outcome = "hit"; break
            if inv:
                outcome = "invalidated"; break
        if outcome == "hit":
            res.hit_before_invalidate += 1
        elif outcome == "invalidated":
            res.invalidated_first += 1
        else:
            res.unresolved += 1
    return res
