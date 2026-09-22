"""Execution desk (CrashForge operator).

Owns the Agentic book's execution. Fires only from standing-order rows the operator ARMED in advance;
never from a desk packet directly. Hard locks outrank every EV number. Every fire and every autonomous
resolution is one ledger line. Brokers are adapters: PaperBroker records fills at tape; RobinhoodBroker
is a stub that refuses until credentials and an approved integration exist.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from . import config as C
from .locks import LockInputs, LockResult, check as lock_check
from .tape import Quote, TapeError, TapeProvider

TZ = ZoneInfo(C.TZ)
ROW_STATUSES = ("ARMED", "LIVE", "FILLED", "CANCELLED", "EXPIRED")
FIRE_WINDOW = (8, 25)          # pre-bell fire window, America/Chicago


# ---- standing orders ---------------------------------------------------------------------
@dataclass
class StandingOrder:
    id: str
    asset: str
    side: str                      # LONG | SHORT (spot rails: LONG only)
    rail: str
    entry_low: float
    entry_high: float
    size_pct: float                # % of DeFi sleeve
    invalidation: float | None
    target: float | None
    expires: str                   # ISO datetime America/Chicago
    packet_id: str = ""
    status: str = "ARMED"
    armed_by: str = "operator"
    armed_at: str = ""
    fills: list[dict] = field(default_factory=list)

    def matches(self, price: float) -> bool:
        return self.entry_low <= price <= self.entry_high


class StandingOrders:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(C.DATA_DIR, "standing_orders.jsonl")
        self.rows: list[StandingOrder] = []
        if os.path.exists(self.path):
            for line in open(self.path):
                if line.strip():
                    self.rows.append(StandingOrder(**json.loads(line)))

    def _write(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            for r in self.rows:
                fh.write(json.dumps(asdict(r)) + "\n")

    def arm(self, **kw) -> StandingOrder:
        """The operator's single advance action. This is the 'APPLY'. No per-trade click after this."""
        row = StandingOrder(id=kw.pop("id", f"LIVE-{len(self.rows) + 1:03d}"), armed_at=datetime.now(TZ).isoformat(timespec="seconds"), **kw)
        if row.side not in ("LONG", "SHORT"):
            raise ValueError("side must be LONG or SHORT")
        if row.rail.lower().startswith("spot") and row.side != "LONG":
            raise ValueError("spot rails are long-only")
        if any(t in row.rail.upper() for t in C.WRAPPER_TOKENS):
            raise ValueError("wrapper rails cannot be armed on the DeFi sleeve")
        self.rows.append(row)
        self._write()
        return row

    def get(self, rid: str) -> StandingOrder | None:
        return next((r for r in self.rows if r.id == rid), None)

    def set_status(self, rid: str, status: str) -> StandingOrder:
        assert status in ROW_STATUSES, status
        r = self.get(rid)
        if not r:
            raise KeyError(rid)
        r.status = status
        self._write()
        return r

    def armed(self) -> list[StandingOrder]:
        return [r for r in self.rows if r.status == "ARMED"]

    def live_for(self, asset: str, side: str) -> list[StandingOrder]:
        return [r for r in self.rows if r.status == "LIVE" and r.asset == asset and r.side == side]

    def from_packet(self, packet: dict, size_pct: float | None = None, band_pct: float = 0.005) -> StandingOrder:
        e = packet.get("entry")
        if e is None and packet.get("entry_band"):
            lo, hi = packet["entry_band"]
        else:
            lo, hi = e * (1 - band_pct), e * (1 + band_pct)
        return self.arm(asset=packet["asset"], side=packet["side"], rail=packet["rail"], entry_low=lo, entry_high=hi,
                        size_pct=size_pct or packet["size_hint_pct_defi_sleeve"], invalidation=packet.get("invalidation"),
                        target=packet.get("target"), expires=packet["time_stop"], packet_id=packet["packet_id"])


# ---- brokers -----------------------------------------------------------------------------
class Broker(Protocol):
    name: str
    def place(self, row: StandingOrder, price: float, size_pct: float) -> dict: ...
    def flatten(self, row: StandingOrder, price: float) -> dict: ...


class PaperBroker:
    name = "paper"

    def place(self, row: StandingOrder, price: float, size_pct: float) -> dict:
        return {"broker": self.name, "order_id": f"paper-{uuid.uuid4().hex[:8]}", "fill": price, "size_pct": size_pct, "status": "FILLED"}

    def flatten(self, row: StandingOrder, price: float) -> dict:
        return {"broker": self.name, "order_id": f"paper-{uuid.uuid4().hex[:8]}", "fill": price, "size_pct": -row.size_pct, "status": "FLAT"}


class RobinhoodBroker:
    """Stub. Live routing needs operator credentials and an approved integration; nothing is implemented here."""
    name = "robinhood"

    def __init__(self):
        if not os.environ.get("RH_APPROVED_INTEGRATION"):
            raise RuntimeError("RobinhoodBroker not configured: set up the approved integration first (RH_APPROVED_INTEGRATION)")

    def place(self, row, price, size_pct):
        raise NotImplementedError("live routing not implemented")

    def flatten(self, row, price):
        raise NotImplementedError("live routing not implemented")


# ---- EV resolver ------------------------------------------------------------------------------
ISSUE_OPTIONS = {
    # option: (p_fill multiplier, edge multiplier, extra_cost_bps, exposure)
    "proceed": (1.00, 1.00, 0.0, 1.0),
    "resize": (1.00, 0.50, 0.0, 0.5),
    "reroute": (0.90, 0.95, 8.0, 1.0),
    "defer": (0.60, 0.80, 0.0, 0.0),
    "flatten": (1.00, 0.00, 5.0, 0.0),
}


@dataclass
class Resolution:
    issue: str
    options_scored: dict[str, float]
    chosen: str
    ev: float
    locks: str
    note: str
    ts: str = ""


def resolve(issue: str, edge_bps: float, slippage_bps: float, gas_bps: float, locks: LockResult,
            lag_seconds: float | None = None, adds_to_live: bool = False) -> Resolution:
    """Score lock-compliant options on EV and pick the maximum. Tie -> less exposure. No option -> flatten."""
    stale_pen = 0.0 if lag_seconds is None or lag_seconds <= C.LAG_WARN_S else min(edge_bps, 20.0)
    scored: dict[str, float] = {}
    for name, (pf, em, extra, _exp) in ISSUE_OPTIONS.items():
        if locks.any_fail and name in ("proceed", "resize", "reroute"):
            continue                                   # a lock FAIL removes every option that keeps risk on
        if adds_to_live and name in ("proceed", "reroute"):
            continue                                   # ARM LIVE != ADD
        if lag_seconds is not None and lag_seconds > C.LAG_STALE_S and name in ("proceed", "resize"):
            continue                                   # STALE tape cannot fire
        scored[name] = round(pf * (edge_bps * em) - slippage_bps - gas_bps - extra - stale_pen, 3)
    if not scored:
        scored = {"flatten": 0.0}
    best = max(scored.values())
    ties = [n for n, v in scored.items() if v == best]
    chosen = min(ties, key=lambda n: ISSUE_OPTIONS[n][3])
    return Resolution(issue, scored, chosen, best, locks.render(), "max EV among lock-compliant options; tie -> less exposure",
                      datetime.now(TZ).isoformat(timespec="seconds"))


# ---- the desk ---------------------------------------------------------------------------------
class ExecutionDesk:
    name = "execution"

    def __init__(self, tape: TapeProvider | None, broker: Broker | None = None, orders: StandingOrders | None = None,
                 lock_inputs: LockInputs | None = None, data_dir: str = C.DATA_DIR, sinks=None):
        self.tape, self.broker = tape, broker or PaperBroker()
        self.orders = orders or StandingOrders(os.path.join(data_dir, "standing_orders.jsonl"))
        self.lock_inputs = lock_inputs or LockInputs()
        self.dir = data_dir
        self.sinks = sinks
        os.makedirs(data_dir, exist_ok=True)

    def _log(self, name: str, row: dict) -> None:
        with open(os.path.join(self.dir, name), "a") as fh:
            fh.write(json.dumps(row) + "\n")

    def _locks(self, quotes: dict[str, Quote]) -> LockResult:
        li = LockInputs(**self.lock_inputs.__dict__)
        if quotes:
            li.lag_seconds = max(q.lag_seconds for q in quotes.values())
        return lock_check(li)

    def heartbeat(self) -> str:
        armed, live = len(self.orders.armed()), sum(1 for r in self.orders.rows if r.status == "LIVE")
        return f"EXEC [{datetime.now(TZ):%H:%M} {C.TZ}] | armed:{armed} | live:{live} | broker:{self.broker.name}"

    def fire(self, now: datetime | None = None, force: bool = False) -> list[dict]:
        """Pre-bell fire window. Zero per-trade clicks: every ARMED row that matches tape and passes all locks fires."""
        now = now or datetime.now(TZ)
        receipts: list[dict] = []
        if not force and (now.weekday() >= 5 or now.strftime("%Y-%m-%d") in C.US_MARKET_HOLIDAYS):
            self._log("fire_receipts.jsonl", {"ts": now.isoformat(), "event": "window skipped (weekend/holiday)"})
            return receipts
        quotes: dict[str, Quote] = {}
        for r in self.orders.armed():
            if r.asset not in quotes and self.tape is not None:
                try:
                    quotes[r.asset] = self.tape.quote(r.asset)
                except TapeError as e:
                    receipts.append({"row_id": r.id, "status": "SKIPPED", "reason": f"tape: {e}"})
        for r in self.orders.armed():
            q = quotes.get(r.asset)
            rec = {"ts": now.isoformat(timespec="seconds"), "row_id": r.id, "packet_id": r.packet_id, "asset": r.asset, "side": r.side,
                   "rail": r.rail, "size_pct": r.size_pct}
            if datetime.fromisoformat(r.expires) <= now:
                self.orders.set_status(r.id, "EXPIRED"); rec.update(status="EXPIRED"); receipts.append(rec); continue
            if q is None:
                rec.update(status="SKIPPED", reason="no quote"); receipts.append(rec); continue
            locks = self._locks({r.asset: q})
            adds = bool(self.orders.live_for(r.asset, r.side))
            rec["lock_check"] = locks.render()
            if locks.any_fail or adds:
                res = resolve("lock FAIL or ADD at fire", edge_bps=50, slippage_bps=5, gas_bps=1, locks=locks, lag_seconds=q.lag_seconds, adds_to_live=adds)
                self._log("resolutions.jsonl", asdict(res))
                rec.update(status="HELD", reason="ADD to LIVE row" if adds else "; ".join(locks.reasons), resolution=res.chosen)
                receipts.append(rec); continue
            if not r.matches(q.price):
                rec.update(status="NO-MATCH", price=q.price, band=[r.entry_low, r.entry_high]); receipts.append(rec); continue
            fill = self.broker.place(r, q.price, r.size_pct)
            r.fills.append(fill); self.orders.set_status(r.id, "LIVE")
            rec.update(status="FIRED", price=q.price, fill=fill, ev=round(((r.target or q.price) - q.price) / q.price * 1e4, 1) if r.side == "LONG" else None)
            receipts.append(rec)
        for rec in receipts:
            self._log("fire_receipts.jsonl", rec)
        if self.sinks and any(x.get("status") == "FIRED" for x in receipts):
            self.sinks.user("READY", "FIRE RECEIPTS " + json.dumps([x for x in receipts if x.get("status") == "FIRED"]))
        return receipts

    def manage(self, now: datetime | None = None) -> list[dict]:
        """Every scan: LIVE rows are checked for invalidation / target / expiry and flattened autonomously."""
        now = now or datetime.now(TZ)
        out = []
        for r in [x for x in self.orders.rows if x.status == "LIVE"]:
            try:
                q = self.tape.quote(r.asset) if self.tape else None
            except TapeError:
                q = None
            if not q:
                continue
            hit = r.target is not None and ((r.side == "LONG" and q.price >= r.target) or (r.side == "SHORT" and q.price <= r.target))
            inv = r.invalidation is not None and ((r.side == "LONG" and q.price <= r.invalidation) or (r.side == "SHORT" and q.price >= r.invalidation))
            exp = datetime.fromisoformat(r.expires) <= now
            if hit or inv or exp:
                res = self.broker.flatten(r, q.price)
                self.orders.set_status(r.id, "FILLED")
                rec = {"ts": now.isoformat(timespec="seconds"), "row_id": r.id, "event": "TARGET" if hit else "INVALIDATION" if inv else "EXPIRY", "price": q.price, "flatten": res}
                self._log("fire_receipts.jsonl", rec); out.append(rec)
        return out
