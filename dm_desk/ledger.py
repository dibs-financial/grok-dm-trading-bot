"""Local ledger of posted packets: id, date, rail, trigger family, INTENT, outcome at EOD / T+5.

Novelty and 'learn from prior misses' read this first. If the ledger file is missing the desk
says so and does not claim novelty.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date as _date

from . import config as C
from .packet import Packet

OUTCOMES = ("HIT", "MISS", "NO-TRIGGER", "INVALIDATED", "EXPIRED", "none")
STATUSES = ("posted", "applied-by-user", "ignored", "killed")


@dataclass
class LedgerEntry:
    id: str
    date: str
    rail: str
    asset: str
    trigger_family: str
    intent: str
    entry: str = ""
    invalidation: str = ""
    size_hint: float | None = None
    drive_date: str = ""
    status: str = "posted"
    outcome_eod: str = "none"
    outcome_t5: str = "none"
    lesson: str = ""
    packet: dict = field(default_factory=dict)
    fingerprint: str = ""
    body_hash: str = ""
    pattern_ids: list[str] = field(default_factory=list)
    kb_citations: list[str] = field(default_factory=list)


@dataclass
class NoveltyVerdict:
    nearest_id: str
    is_copy: bool
    line: str


class Ledger:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(C.DATA_DIR, "ledger.jsonl")
        self.present = os.path.exists(self.path)
        self.entries: list[LedgerEntry] = []
        if self.present:
            with open(self.path) as fh:
                for line in fh:
                    if line.strip():
                        self.entries.append(LedgerEntry(**json.loads(line)))

    def _write(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            for e in self.entries:
                fh.write(json.dumps(e.__dict__) + "\n")
        self.present = True

    def next_id(self, day: _date) -> str:
        prefix = f"DM-{day:%Y%m%d}-"
        n = sum(1 for e in self.entries if e.id.startswith(prefix)) + 1
        return f"{prefix}{n:02d}"

    def add(self, p: Packet, drive_date: str, fingerprint: str = "", body_hash: str = "",
            pattern_ids: list[str] | None = None, kb_citations: list[str] | None = None) -> LedgerEntry:
        pk = p.to_dict()
        pk["fingerprint"], pk["body_hash"] = fingerprint, body_hash
        e = LedgerEntry(id=p.packet_id, date=p.packet_id[3:11], rail=p.rail, asset=p.asset,
                        trigger_family=p.trigger_family, intent=p.intent, entry=p.entry_text(),
                        invalidation=str(p.invalidation or p.invalidation_condition),
                        size_hint=p.size_hint_pct_defi_sleeve, drive_date=drive_date, packet=pk,
                        fingerprint=fingerprint, body_hash=body_hash, pattern_ids=pattern_ids or [],
                        kb_citations=kb_citations or [])
        self.entries.append(e)
        self._write()
        return e

    def get(self, pid: str) -> LedgerEntry | None:
        return next((e for e in self.entries if e.id == pid), None)

    def update(self, pid: str, **kw) -> LedgerEntry:
        e = self.get(pid)
        if not e:
            raise KeyError(pid)
        for k, v in kw.items():
            if k in ("status",) and v not in STATUSES:
                raise ValueError(v)
            if k in ("outcome_eod", "outcome_t5") and v not in OUTCOMES:
                raise ValueError(v)
            setattr(e, k, v)
        self._write()
        return e

    def open_packets(self) -> list[LedgerEntry]:
        return [e for e in self.entries if e.status in ("posted", "applied-by-user") and e.outcome_eod in ("none", "NO-TRIGGER")]

    def recent_sessions(self, n: int = C.NOVELTY_WINDOW_SESSIONS) -> list[LedgerEntry]:
        days = sorted({e.date for e in self.entries}, reverse=True)[:n]
        return [e for e in self.entries if e.date in days]

    def misses(self) -> list[LedgerEntry]:
        return [e for e in self.entries if e.outcome_eod in ("MISS", "INVALIDATED") or e.outcome_t5 in ("MISS", "INVALIDATED")]

    def novelty(self, p: Packet, *, live_level_new: bool, regime_changed: bool,
                drive_evidence_newer: bool, prior_miss_changes_plan: bool) -> NoveltyVerdict:
        """Copy = same rail + asset + trigger family in the last 5 sessions with only wording changed.
        Allowed variant = same family with at least one of the four 'new' conditions true."""
        if not self.present:
            return NoveltyVerdict("NONE (ledger missing)", False,
                                  "ledger file is missing — novelty cannot be claimed; say so")
        same = [e for e in self.recent_sessions() if e.rail == p.rail and e.asset == p.asset
                and e.trigger_family == p.trigger_family]
        if not same:
            nearest = max(self.entries, key=lambda e: e.date).id if self.entries else "NONE (ledger empty)"
            return NoveltyVerdict(nearest, False, "new rail/asset/trigger family vs the last 5 sessions")
        nearest = max(same, key=lambda e: e.date).id
        reasons = [r for r, ok in (("live level not in the last packet", live_level_new),
                                   ("regime change since the last packet", regime_changed),
                                   ("Drive evidence dated after the last packet", drive_evidence_newer),
                                   ("a prior miss changed invalidation or size", prior_miss_changes_plan)) if ok]
        if reasons:
            return NoveltyVerdict(nearest, False, reasons[0])
        return NoveltyVerdict(nearest, True, "same rail + asset + trigger family with only wording changed")
