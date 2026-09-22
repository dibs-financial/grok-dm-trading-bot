"""Strategy packet: the only thing the desk hands to the user thread and to CrashForge.

A packet with a missing required field is not a packet. Any lock FAIL forces INTENT = DO NOT APPLY.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields

from . import config as C

INTENTS = ("APPLY", "WATCH ONLY", "DO NOT APPLY")
SIDES = ("LONG", "SHORT", "LEND", "BORROW", "LP")
CRASHFORGE_MUST_NOT = "ARM LIVE from this packet; silent-fire; rewrite locks; ADD to an already-LIVE row"
USER_ACTION = "APPLY or ignore. DM will not APPLY."
_ID_RE = re.compile(r"^DM-\d{8}-\d{2}$")


@dataclass
class DefiCheck:
    protocol: str = ""            # e.g. "Aave v3" or "spot BTC"
    version: str = ""
    chain: str = ""               # e.g. "Ethereum", "Base"; for spot: venue chain or "CEX"
    venue: str = ""
    paused_or_upgrading: bool | None = None      # None = unknown => UNPROVEN
    bad_debt_or_admin_key_or_unaudited: bool | None = None
    slippage_edge_fraction: float | None = None  # slippage / planned edge at hinted size
    current_rate: float | None = None            # borrow/lend rails only
    rate_kill: float | None = None               # rate at which the idea dies
    is_borrow_lend: bool = False
    custody_path: str = ""                       # wallet / lending market / LP
    gas_mev_net_fraction: float | None = None    # (gas + MEV) / expected net
    settlement_seconds: float | None = None      # confirmation time vs lag>20


@dataclass
class HistoryEvidence:
    timeframe: str = ""
    n: int = 0
    hit_before_invalidate: int = 0
    last_dates: list[str] = field(default_factory=list)


@dataclass
class LiveCheck:
    timestamp: str = ""           # America/Chicago, inside this scan window
    source: str = ""
    level_still_present: bool | None = None
    liquidity_at_size: bool | None = None
    traded_through_without_reload: bool | None = None


@dataclass
class Packet:
    packet_id: str = ""
    intent: str = ""
    rail: str = ""
    asset: str = ""
    venue: str = ""
    side: str = ""
    entry: float | None = None
    entry_band: tuple[float, float] | None = None
    trigger: str = ""              # observable if-then
    trigger_family: str = ""       # for novelty, e.g. "btc-50wk-ma-reclaim"
    invalidation: float | None = None
    invalidation_condition: str = ""
    time_stop: str = ""            # ISO datetime America/Chicago
    target: float | None = None
    rr: float | None = None        # planned R:R after slippage + gas
    size_hint_pct_defi_sleeve: float | None = None
    lock_check: dict[str, str] = field(default_factory=dict)
    defi: DefiCheck = field(default_factory=DefiCheck)
    correlation: str = ""          # add / independent / doubles existing beta
    correlation_note: str = ""
    history: HistoryEvidence = field(default_factory=HistoryEvidence)
    live: LiveCheck = field(default_factory=LiveCheck)
    novelty_ledger_id: str = ""    # nearest ledger id, or "NONE (ledger empty)"
    novelty_reason: str = ""
    advisory_risk: str = ""
    drive_latest: str = ""         # "Drive latest: <file + date>"

    # ---- validation ---------------------------------------------------------------
    def missing_fields(self) -> list[str]:
        m: list[str] = []
        if not _ID_RE.match(self.packet_id or ""):
            m.append("PACKET ID")
        if self.intent not in INTENTS:
            m.append("INTENT")
        if not self.rail:
            m.append("RAIL")
        if not self.asset or not self.venue:
            m.append("ASSET / VENUE")
        if self.side not in SIDES:
            m.append("SIDE")
        if self.entry is None and self.entry_band is None:
            m.append("ENTRY")
        if not self.trigger or not self.trigger_family:
            m.append("TRIGGER")
        if self.invalidation is None and not self.invalidation_condition:
            m.append("INVALIDATION")
        if not self.time_stop:
            m.append("TIME STOP / EXPIRY")
        if self.target is None or self.rr is None:
            m.append("TARGET / R:R")
        if self.size_hint_pct_defi_sleeve is None:
            m.append("SIZE HINT")
        if set(self.lock_check) != set(C.LOCK_NAMES):
            m.append("LOCK CHECK")
        d = self.defi
        if not (d.protocol and d.chain and d.custody_path):
            m.append("DEFI CHECK")
        if self.correlation not in ("add", "independent", "doubles existing beta"):
            m.append("CORRELATION")
        if not self.history.timeframe:
            m.append("HISTORY")
        if not (self.live.timestamp and self.live.source):
            m.append("LIVE CHECK")
        if not (self.novelty_ledger_id and self.novelty_reason):
            m.append("NOVELTY")
        if not self.advisory_risk:
            m.append("ADVISORY RISK")
        if not self.drive_latest:
            m.append("DRIVE LATEST")
        return m

    def is_wrapper(self) -> bool:
        blob = f"{self.rail} {self.asset} {self.venue}".upper()
        return any(re.search(rf"\b{re.escape(t)}\b", blob) for t in C.WRAPPER_TOKENS)

    def enforce_intent(self) -> None:
        """Any lock FAIL => INTENT = DO NOT APPLY. Never the other way round."""
        if any(v == "FAIL" for v in self.lock_check.values()) and self.intent == "APPLY":
            self.intent = "DO NOT APPLY"
        if self.intent == "APPLY" and self.correlation == "doubles existing beta":
            self.intent = "WATCH ONLY"

    def entry_text(self) -> str:
        if self.entry_band:
            return f"{self.entry_band[0]:,.2f}-{self.entry_band[1]:,.2f}"
        return f"{self.entry:,.2f}" if self.entry is not None else ""

    # ---- rendering ----------------------------------------------------------------
    def render(self) -> str:
        d, h, l = self.defi, self.history, self.live
        locks = " / ".join(f"{k} {v}" for k, v in self.lock_check.items())
        inval = f"{self.invalidation:,.2f}" if self.invalidation is not None else self.invalidation_condition
        if self.invalidation is not None and self.invalidation_condition:
            inval += f" ({self.invalidation_condition})"
        defi = (f"{d.protocol} {d.version} {d.chain}".strip()
                + f" | pause/bad-debt: {'no' if d.paused_or_upgrading is False and d.bad_debt_or_admin_key_or_unaudited is False else 'UNKNOWN/YES'}"
                + f" | slippage: {d.slippage_edge_fraction:.0%} of edge" if d.slippage_edge_fraction is not None else " | slippage: UNKNOWN")
        defi += (f" | rate-kill: {d.current_rate}->{d.rate_kill}" if d.is_borrow_lend else " | rate-kill: n/a")
        defi += f" | custody: {d.custody_path}"
        defi += (f" | gas/MEV: {d.gas_mev_net_fraction:.0%} of net" if d.gas_mev_net_fraction is not None else " | gas/MEV: UNKNOWN")
        defi += (f" | stale-risk: settle {d.settlement_seconds:.0f}s vs {C.LAG_STALE_S}s" if d.settlement_seconds is not None else " | stale-risk: UNKNOWN")
        lines = [
            f"PACKET ID: {self.packet_id}",
            f"INTENT: {self.intent}",
            f"RAIL: {self.rail}",
            f"ASSET / VENUE: {self.asset} / {self.venue}",
            f"SIDE: {self.side}",
            f"ENTRY: {self.entry_text()}",
            f"TRIGGER: {self.trigger}",
            f"INVALIDATION: {inval}",
            f"TIME STOP / EXPIRY: {self.time_stop}",
            f"TARGET / R:R: {self.target:,.2f} / {self.rr:.2f}:1" if self.target is not None and self.rr is not None else "TARGET / R:R: ",
            f"SIZE HINT: {self.size_hint_pct_defi_sleeve}% of DeFi sleeve only",
            f"LOCK CHECK: {locks}",
            "  each PASS or FAIL. Any FAIL => INTENT = DO NOT APPLY",
            f"DEFI CHECK: {defi}",
            f"CORRELATION: vs BTC GTC @${C.BTC_GTC:,.0f}, Desk R {C.DESK_R}, HOLD {'+'.join(C.HOLD_BOOK)} — {self.correlation}"
            + (f" ({self.correlation_note})" if self.correlation_note else ""),
            f"HISTORY: {h.timeframe}, n={h.n}, hit-before-invalidate={h.hit_before_invalidate}, last 3: {', '.join(h.last_dates[-3:])}",
            f"LIVE CHECK: {l.timestamp} {C.TZ}, {l.source}, level present={l.level_still_present}, liquidity at size={l.liquidity_at_size}",
            f"NOVELTY: not a copy of ledger #{self.novelty_ledger_id} because {self.novelty_reason}",
            f"ADVISORY RISK: {self.advisory_risk}",
            f"CRASHFORGE MUST NOT: {CRASHFORGE_MUST_NOT}",
            f"USER ACTION: {USER_ACTION}",
            f"{self.drive_latest}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_band"] = list(self.entry_band) if self.entry_band else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Packet":
        d = dict(d)
        for k, sub in (("defi", DefiCheck), ("history", HistoryEvidence), ("live", LiveCheck)):
            if isinstance(d.get(k), dict):
                d[k] = sub(**d[k])
        if d.get("entry_band"):
            d["entry_band"] = tuple(d["entry_band"])
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
