"""Hybrid-Solver: pattern atlas -> classical candidates -> QUBO selection -> desk Packet candidates.

Exposed to the desk as `EngineAdvisor` (an Advisor). The desk gate still decides.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config as C
from ..ledger import Ledger
from ..packet import DefiCheck, HistoryEvidence, Packet
from .guard import UniquenessGuard, jaccard
from .patterns import Atlas, LevelPattern, mine
from .qubo import SimulatedAnnealer, Solver, build_qubo
from .scanner import Scanner

TZ = ZoneInfo(C.TZ)


@dataclass
class Candidate:
    asset: str
    side: str
    rail: str
    entry: float
    invalidation: float
    target: float
    pattern_ids: list[str]
    cites: list[str]
    utility: float = 0.0
    novelty: float = 0.0
    features: dict = field(default_factory=dict)

    @property
    def rr(self) -> float:
        return abs(self.target - self.entry) / max(abs(self.entry - self.invalidation), 1e-9)

    @property
    def family(self) -> str:
        return f"{self.asset.lower()}-{self.side.lower()}-level-{int(self.entry)}"


def load_venues(path: str | None) -> dict:
    if path and os.path.exists(path):
        return json.load(open(path))
    return {}


def generate(atlas: Atlas, drive_rails: tuple[str, ...] = (), max_dist: float = 0.10, noise: float = 0.01,
             min_rr: float = C.MIN_RR, min_recurrence: int = 1) -> list[Candidate]:
    out: list[Candidate] = []
    by_asset: dict[str, list[LevelPattern]] = {}
    for lp in atlas.levels:
        by_asset.setdefault(lp.asset, []).append(lp)
    for asset, lps in by_asset.items():
        last = atlas.last_price.get(asset)
        if not last or asset not in ("BTC", "ETH"):
            continue
        levels = sorted({lp.level for lp in lps})
        for lp in lps:
            if lp.recurrence < min_recurrence or abs(lp.level - last) / last > max_dist:
                continue
            role = max(lp.role_counts, key=lp.role_counts.get)
            if role == "support" and lp.level <= last * 1.005:
                lower = [l for l in levels if l < lp.level * (1 - noise)]
                upper = [l for l in levels if l > lp.level]
                if not lower or not upper:
                    continue
                inval, target = max(lower), min(upper)
                c = Candidate(asset, "LONG", f"spot {asset}", lp.level, inval, target, [lp.id], lp.cites[-2:])
            elif role == "resistance" and "Hyperliquid perps" in drive_rails and lp.level >= last * 0.995:
                upper = [l for l in levels if l > lp.level * (1 + noise)]
                lower = [l for l in levels if l < lp.level]
                if not lower or not upper:
                    continue
                c = Candidate(asset, "SHORT", "Hyperliquid perps", lp.level, min(upper), max(lower), [lp.id], lp.cites[-2:])
            else:
                continue
            if c.rr < min_rr:
                continue
            c.features = {"recurrence": lp.recurrence, "held_rate": lp.held_rate, "rr": round(c.rr, 2),
                          "dist": round(abs(lp.level - last) / last, 4)}
            c.utility = min(1.0, 0.4 * lp.held_rate + 0.3 * min(lp.recurrence, 4) / 4 + 0.3 * min(c.rr, 4) / 4)
            out.append(c)
    return out


def novelty_scores(cands: list[Candidate], ledger: Ledger) -> None:
    for c in cands:
        best = 0.0
        for e in ledger.entries:
            if e.asset == c.asset and e.rail == c.rail:
                best = max(best, jaccard(c.family + " " + str(c.entry), e.trigger_family + " " + e.entry), 0.6 if e.trigger_family == c.family else 0.0)
        c.novelty = 1.0 - best


def select(cands: list[Candidate], solver: Solver, lam_novelty: float = 1.0, k: int = 3) -> list[Candidate]:
    if not cands:
        return []
    conflicts = [(i, j) for i in range(len(cands)) for j in range(i + 1, len(cands))
                 if cands[i].asset == cands[j].asset and cands[i].side == cands[j].side]
    Q = build_qubo([c.utility for c in cands], [c.novelty for c in cands], conflicts, lam_novelty=lam_novelty)
    ranked: list[Candidate] = []
    for _, bits in solver.solve(Q, k=k * 2):
        for i, b in enumerate(bits):
            if b and cands[i] not in ranked:
                ranked.append(cands[i])
    return ranked[:k]


def to_packet(c: Candidate, venues: dict, now: datetime, drive_latest: str, size_pct: float = 5.0, days: int = 5) -> Packet:
    venue_key = f"{c.rail}"
    v = venues.get(venue_key, {})
    defi = DefiCheck(protocol=v.get("protocol", c.rail), version=v.get("version", ""), chain=v.get("chain", ""), venue=v.get("venue", ""),
                     paused_or_upgrading=v.get("paused_or_upgrading"), bad_debt_or_admin_key_or_unaudited=v.get("bad_debt_or_admin_key_or_unaudited"),
                     slippage_edge_fraction=v.get("slippage_edge_fraction"), is_borrow_lend=bool(v.get("is_borrow_lend", False)),
                     current_rate=v.get("current_rate"), rate_kill=v.get("rate_kill"), custody_path=v.get("custody_path", ""),
                     gas_mev_net_fraction=v.get("gas_mev_net_fraction"), settlement_seconds=v.get("settlement_seconds"))
    comp = ">=" if c.side == "LONG" else "<="
    trigger = (f"if {c.asset} price {comp} {c.entry:,.0f} holds on a daily close (recurring {'support' if c.side == 'LONG' else 'resistance'} "
               f"{c.pattern_ids[0]}, seen {c.features.get('recurrence')}x, held-rate {c.features.get('held_rate', 0):.0%})")
    p = Packet(intent="APPLY", rail=c.rail, asset=c.asset, venue=v.get("venue", ""), side=c.side, entry=c.entry, trigger=trigger,
               trigger_family=c.family, invalidation=c.invalidation, time_stop=(now + timedelta(days=days)).isoformat(timespec="seconds"),
               target=c.target, rr=round(c.rr * (1 - (v.get("slippage_edge_fraction") or 0) - (v.get("gas_mev_net_fraction") or 0)), 2),
               size_hint_pct_defi_sleeve=size_pct, defi=defi, history=HistoryEvidence(timeframe="1D"),
               advisory_risk=f"pattern-atlas candidate; utility {c.utility:.2f}, novelty {c.novelty:.2f}; kills: macro shock that invalidates the level regime, ETF flow reversal, Drive memo after {drive_latest[-11:-1] if drive_latest else 'n/a'}",
               drive_latest=drive_latest)
    p.correlation = "doubles existing beta" if c.asset == "BTC" and c.side == "LONG" else "add"
    p.correlation_note = "engine candidate; " + ", ".join(c.cites)
    return p


class EngineAdvisor:
    """Advisor implementation: scan -> mine -> generate -> QUBO select -> guard -> Packet candidates."""
    name = "engine"

    def __init__(self, ledger: Ledger, data_dir: str | None = None, venues_path: str | None = None,
                 solver: Solver | None = None, drive_rails: tuple[str, ...] = (), size_pct: float = 5.0):
        self.ledger = ledger
        self.dir = data_dir or os.path.join(C.DATA_DIR, "engine")
        self.scanner = Scanner(data_dir=self.dir)
        self.venues = load_venues(venues_path or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "examples", "venues.json"))
        self.solver = solver or SimulatedAnnealer()
        self.drive_rails = drive_rails
        self.size_pct = size_pct
        self.last_report: dict = {}

    def propose(self, context: str) -> list[Packet]:
        now = datetime.now(TZ)
        res = self.scanner.scan()
        atlas = mine(res["store"])
        from .patterns import save
        save(atlas, os.path.join(self.dir, "atlas.json"))
        cands = generate(atlas, self.drive_rails)
        novelty_scores(cands, self.ledger)
        guard = UniquenessGuard(self.ledger)
        drive_line = next((l for l in context.splitlines() if l.startswith("Drive latest:")), f"Drive latest: knowledge.json ({atlas.as_of})")
        out: list[Packet] = []
        rejected: list[str] = []
        lam = 1.0
        for attempt in range(2):
            for c in select(cands, self.solver, lam_novelty=lam):
                p = to_packet(c, self.venues, now, drive_line, self.size_pct)
                v = guard.check(p, c.pattern_ids, now.date(), live_level_new=True, drive_evidence_newer=True)
                if v.accepted:
                    p.correlation_note += f"; fingerprint {v.fingerprint}; patterns {','.join(c.pattern_ids)}"
                    out.append(p)
                else:
                    rejected.append(f"{c.family}: {v.reason}")
            if out:
                break
            lam *= 2.0      # novelty deficit: re-anneal with stronger novelty weight, once
        self.last_report = {"candidates": len(cands), "selected": len(out), "rejected": rejected, "solver": self.solver.name, "as_of": atlas.as_of}
        return out
