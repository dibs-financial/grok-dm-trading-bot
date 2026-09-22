"""Uniqueness-Guard: fingerprint + body-hash + near-duplicate + one-per-day checks against the ledger."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date as _date

from ..ledger import Ledger
from ..packet import Packet


def _bucket(v: float | None, pct: float = 0.01) -> str:
    """Log-scale bucket: values within ~pct of each other share a bucket."""
    if v is None or v <= 0:
        return "na"
    import math
    return str(int(math.log(v) / math.log1p(pct)))


def fingerprint(p: Packet, pattern_ids: list[str]) -> str:
    core = {"rail": p.rail.lower(), "asset": p.asset.upper(), "side": p.side, "family": p.trigger_family,
            "entry": _bucket(p.entry if p.entry is not None else (sum(p.entry_band) / 2 if p.entry_band else None)),
            "inval": _bucket(p.invalidation), "patterns": sorted(pattern_ids)}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:24]


def body_hash(p: Packet) -> str:
    return hashlib.sha256(p.render().encode()).hexdigest()[:24]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$%.\-]+", text.lower()) if len(t) > 2}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


@dataclass
class GuardVerdict:
    accepted: bool
    reason: str
    nearest_id: str = ""
    similarity: float = 0.0
    fingerprint: str = ""
    body_hash: str = ""


class UniquenessGuard:
    def __init__(self, ledger: Ledger, tau: float = 0.8, window_days: int | None = None):
        self.ledger, self.tau, self.window_days = ledger, tau, window_days

    def check(self, p: Packet, pattern_ids: list[str], today: _date, *, live_level_new: bool = False,
              regime_changed: bool = False, drive_evidence_newer: bool = False, prior_miss_changes_plan: bool = False) -> GuardVerdict:
        fp, bh = fingerprint(p, pattern_ids), body_hash(p)
        day = f"{today:%Y%m%d}"
        if any(e.date == day and e.status != "killed" for e in self.ledger.entries):
            return GuardVerdict(False, "one accepted emission per day already on ledger", fingerprint=fp, body_hash=bh)
        nearest, best = "", 0.0
        for e in self.ledger.entries:
            pk = e.packet or {}
            if pk.get("fingerprint") == fp:
                return GuardVerdict(False, "exact fingerprint match", e.id, 1.0, fp, bh)
            if pk.get("body_hash") == bh:
                return GuardVerdict(False, "exact body hash match", e.id, 1.0, fp, bh)
            sim = jaccard(p.trigger + " " + p.advisory_risk + " " + p.rail + " " + p.asset,
                          str(pk.get("trigger", "")) + " " + str(pk.get("advisory_risk", "")) + " " + e.rail + " " + e.asset)
            if sim > best:
                nearest, best = e.id, sim
        if best >= self.tau:
            return GuardVerdict(False, f"semantic near-duplicate of {nearest} (jaccard {best:.2f} >= {self.tau})", nearest, best, fp, bh)
        nv = self.ledger.novelty(p, live_level_new=live_level_new, regime_changed=regime_changed,
                                 drive_evidence_newer=drive_evidence_newer, prior_miss_changes_plan=prior_miss_changes_plan)
        if nv.is_copy:
            return GuardVerdict(False, "same rail+asset+trigger family in last 5 sessions with no allowed-variant condition", nv.nearest_id, best, fp, bh)
        p.novelty_ledger_id, p.novelty_reason = nv.nearest_id, nv.line
        return GuardVerdict(True, "unique", nearest or nv.nearest_id, best, fp, bh)
