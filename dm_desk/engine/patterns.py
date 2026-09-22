"""Pattern-Miner: rebuild a compact, cited pattern atlas from the full KB store."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .scanner import Store


@dataclass
class LevelPattern:
    asset: str
    level: float
    role_counts: dict[str, int]
    dates: list[str]
    cites: list[str]
    held: int = 0
    failed: int = 0
    aliases: list[float] = field(default_factory=list)   # raw level values collapsed into this canonical entry

    @property
    def recurrence(self) -> int:
        return len(self.dates)

    @property
    def held_rate(self) -> float:
        n = self.held + self.failed
        return self.held / n if n else 0.5

    @property
    def id(self) -> str:
        return f"level:{self.asset}:{int(self.level)}"


@dataclass
class Atlas:
    as_of: str
    levels: list[LevelPattern] = field(default_factory=list)
    regime_sequence: list[dict] = field(default_factory=list)
    motifs: dict[str, int] = field(default_factory=dict)
    extreme_fear_forward: dict = field(default_factory=dict)
    catalyst_outcomes: list[dict] = field(default_factory=list)
    hike_odds_vs_btc: dict = field(default_factory=dict)
    last_price: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict:
        d = self.__dict__.copy()
        d["levels"] = [dict(l.__dict__, id=l.id, recurrence=l.recurrence, held_rate=l.held_rate) for l in self.levels]
        return d


def _bucket_fg(v) -> str:
    if v is None: return "na"
    return "extreme-fear" if v <= 25 else "fear" if v <= 45 else "neutral" if v <= 55 else "greed"


def _bucket_odds(v) -> str:
    if v is None: return "na"
    return "hike-likely" if v >= 0.5 else "hike-live" if v >= 0.3 else "hold"


def mine(store: Store, level_tolerance: float = 0.004) -> Atlas:
    atlas = Atlas(as_of=store.as_of)
    snaps = sorted(store.series, key=lambda s: s["date"])
    price_by_date = {s["date"]: {"BTC": s.get("btc"), "ETH": s.get("eth")} for s in snaps}
    dates = [s["date"] for s in snaps]

    # --- level recurrence and held/failed ------------------------------------------------
    groups: dict[str, list[LevelPattern]] = defaultdict(list)
    for r in sorted(store.levels, key=lambda r: r["date"]):
        for role in ("support", "resistance"):
            for lv in r[role]:
                if not isinstance(lv, (int, float)):
                    continue
                g = groups[r["asset"]]
                match = next((p for p in g if abs(p.level - lv) / lv <= level_tolerance), None)
                if match:
                    if float(lv) != match.level and float(lv) not in match.aliases:
                        match.aliases.append(float(lv))
                    match.role_counts[role] = match.role_counts.get(role, 0) + 1
                    if r["date"] not in match.dates:
                        match.dates.append(r["date"]); match.cites.append(r["cite"])
                else:
                    g.append(LevelPattern(r["asset"], float(lv), {role: 1}, [r["date"]], [r["cite"]]))
    for asset, g in groups.items():
        for p in g:
            for d in p.dates:
                if d not in dates: continue
                i = dates.index(d)
                if i + 1 >= len(dates): continue
                p0, p1 = price_by_date[d].get(asset), price_by_date[dates[i + 1]].get(asset)
                if p0 is None or p1 is None: continue
                role = max(p.role_counts, key=p.role_counts.get)
                broke = (role == "support" and p1 < p.level) or (role == "resistance" and p1 > p.level)
                if broke: p.failed += 1
                else: p.held += 1
        atlas.levels.extend(sorted(g, key=lambda p: (-p.recurrence, p.level)))
    if snaps:
        atlas.last_price = {k: v for k, v in price_by_date[dates[-1]].items() if v is not None}

    # --- regime sequence + motifs ---------------------------------------------------------
    prev_btc = None
    for s in snaps:
        btc = s.get("btc")
        direction = "na" if prev_btc is None or btc is None else ("up" if btc > prev_btc else "down")
        atlas.regime_sequence.append({"date": s["date"], "fg": _bucket_fg(s.get("fear_greed")),
                                      "odds": _bucket_odds(s.get("sept_hike_prob")), "btc_dir": direction, "cite": s["cite"]})
        prev_btc = btc if btc is not None else prev_btc
    states = [f"{r['fg']}/{r['btc_dir']}" for r in atlas.regime_sequence]
    motifs: Counter = Counter()
    for n in (2, 3):
        for i in range(len(states) - n + 1):
            motifs[" -> ".join(states[i:i + n])] += 1
    atlas.motifs = {k: v for k, v in motifs.most_common(12) if v >= 2}

    # --- extreme fear forward returns -----------------------------------------------------
    fwd1, fwd2 = [], []
    for i, s in enumerate(snaps):
        if s.get("fear_greed") is not None and s["fear_greed"] <= 25 and s.get("btc"):
            if i + 1 < len(snaps) and snaps[i + 1].get("btc"): fwd1.append(snaps[i + 1]["btc"] / s["btc"] - 1)
            if i + 2 < len(snaps) and snaps[i + 2].get("btc"): fwd2.append(snaps[i + 2]["btc"] / s["btc"] - 1)
    atlas.extreme_fear_forward = {"n": len(fwd1), "avg_next": sum(fwd1) / len(fwd1) if fwd1 else None,
                                  "avg_next2": sum(fwd2) / len(fwd2) if fwd2 else None,
                                  "positive_next2_rate": (sum(1 for x in fwd2 if x > 0) / len(fwd2)) if fwd2 else None}

    # --- catalyst -> outcome ---------------------------------------------------------------
    keys = ("CPI", "NFP", "FOMC", "PCE", "ETF", "Jackson Hole", "CLARITY", "MOU", "hike")
    for ev in sorted(store.timeline, key=lambda e: e["date"]):
        tag = next((k for k in keys if k.lower() in ev["event"].lower()), None)
        if not tag: continue
        before = [s for s in snaps if s["date"] <= ev["date"] and s.get("btc")]
        after = [s for s in snaps if s["date"] > ev["date"] and s.get("btc")]
        if before and after:
            atlas.catalyst_outcomes.append({"date": ev["date"], "tag": tag, "event": ev["event"][:80],
                                            "btc_next": round(after[0]["btc"] / before[-1]["btc"] - 1, 4), "cite": ev["cite"]})

    # --- hike odds vs BTC direction -------------------------------------------------------
    agg: dict[str, list[float]] = defaultdict(list)
    for i in range(1, len(snaps)):
        o, b0, b1 = snaps[i - 1].get("sept_hike_prob"), snaps[i - 1].get("btc"), snaps[i].get("btc")
        if o is not None and b0 and b1:
            agg[_bucket_odds(o)].append(b1 / b0 - 1)
    atlas.hike_odds_vs_btc = {k: {"n": len(v), "avg_next": sum(v) / len(v)} for k, v in agg.items()}
    return atlas


def save(atlas: Atlas, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(atlas.to_json(), open(path, "w"), indent=1)
