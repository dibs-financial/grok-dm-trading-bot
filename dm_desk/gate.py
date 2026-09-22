"""Qualification gate: all 13 items must pass or the packet does not ship. Fail closed.

`qualify()` never mutates the market view; it only decides. It does set INTENT to DO NOT APPLY
on any lock FAIL and to WATCH ONLY when the idea doubles existing crypto beta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config as C
from .packet import Packet


@dataclass
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    near_miss: bool = False      # P1: exactly one soft failure

    def reason_line(self) -> str:
        return "; ".join(self.failures) if self.failures else "all 13 gate items passed"


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def qualify(p: Packet, *, drive_rails: tuple[str, ...] = (), scan_start: datetime | None = None,
            now: datetime | None = None, noise_fraction: float = 0.01) -> GateResult:
    f: list[str] = []

    # 1 (first, always). A TradFi wrapper is never a packet, whatever else is filled in.
    if p.is_wrapper():
        return GateResult(False, ["1 rail is a TradFi wrapper (IBIT/VTI/ETF/broker) — study it for levels, do not hand it off"])

    # 0. Not a packet at all if any required field is missing.
    missing = p.missing_fields()
    if missing:
        return GateResult(False, [f"missing required field(s): {', '.join(missing)}"])

    # 1. Rail is DeFi-native; never a wrapper.
    allowed = tuple(C.DEFI_RAILS) + tuple(drive_rails)
    if not any(p.rail.lower().startswith(r.lower()) for r in allowed):
        f.append(f"1 rail {p.rail!r} is not DeFi-native or Drive-named (allowed: {', '.join(allowed)})")
    if p.rail.lower().startswith("aave") and not (p.defi.version and p.defi.chain):
        f.append("1 Aave rail needs version + chain")

    # 2. Exact venue + asset + side + entry number or tight band.
    if p.entry_band and p.entry_band[1] <= p.entry_band[0]:
        f.append("2 entry band malformed")
    if p.entry_band and (p.entry_band[1] - p.entry_band[0]) / p.entry_band[0] > 0.02:
        f.append("2 entry band wider than 2% — a vibe, not a number")

    # 3. Trigger is an observable if-then.
    t = p.trigger.lower()
    if not (("if" in t or "when" in t or ">" in t or "<" in t or ">=" in t or "<=" in t)
            and any(k in t for k in ("price", "close", "utiliz", "funding", "tvl", "liquidation", "rate", "$", "%", "ma", "ema", "flow"))):
        f.append("3 trigger is not an observable if-then on price/utilization/funding/TVL/liquidation")

    # 4. Invalidation farther from entry than normal noise.
    e = p.entry if p.entry is not None else sum(p.entry_band) / 2
    if _num(p.invalidation):
        dist = abs(e - p.invalidation) / e
        if dist < noise_fraction:
            f.append(f"4 invalidation {dist:.2%} from entry is inside normal noise ({noise_fraction:.0%})")
        if p.side == "LONG" and p.invalidation >= e or p.side == "SHORT" and p.invalidation <= e:
            f.append("4 invalidation is on the wrong side of entry")

    # 5. Time stop must be a real future time.
    try:
        ts = datetime.fromisoformat(p.time_stop)
        ref = now or datetime.now(ts.tzinfo)
        if ts <= ref:
            f.append("5 time stop already passed")
        if ts - ref > timedelta(days=30):
            f.append("5 time stop more than 30 days out — effectively open-ended")
    except ValueError:
        f.append("5 time stop is not an ISO datetime")

    # 6. R:R >= MIN_RR after slippage + gas.
    if p.rr is None or p.rr < C.MIN_RR:
        f.append(f"6 planned R:R {p.rr} < {C.MIN_RR}:1 after slippage + gas")
    if _num(p.target) and _num(p.invalidation) and e:
        raw_rr = abs(p.target - e) / max(abs(e - p.invalidation), 1e-9)
        if p.rr and p.rr > raw_rr * 1.05:
            f.append(f"6 stated R:R {p.rr:.2f} exceeds geometric R:R {raw_rr:.2f} from entry/target/invalidation")

    # 7. History: n >= MIN_HISTORY_N with hit count.
    h = p.history
    if h.n < C.MIN_HISTORY_N:
        f.append(f"7 history n={h.n} < {C.MIN_HISTORY_N} = UNPROVEN")
    if h.hit_before_invalidate > h.n:
        f.append("7 history hit count exceeds sample")

    # 8. Live check inside this scan window; level still present; liquidity at size.
    l = p.live
    try:
        lts = datetime.fromisoformat(l.timestamp)
        if scan_start and lts < scan_start:
            f.append("8 live check timestamp is from a previous scan window")
    except ValueError:
        f.append("8 live check timestamp is not an ISO datetime")
    if l.level_still_present is not True:
        f.append("8 level not confirmed present on live tape")
    if l.liquidity_at_size is not True:
        f.append("8 liquidity/slippage at hinted size not confirmed")
    if l.traded_through_without_reload:
        f.append("8 level already traded through and did not reload — dead")

    # 9. Lock precheck: any FAIL => DO NOT APPLY (enforced), and never ship an APPLY with a FAIL.
    p.enforce_intent()
    if any(v == "FAIL" for v in p.lock_check.values()):
        f.append("9 lock precheck FAIL (" + ", ".join(k for k, v in p.lock_check.items() if v == "FAIL") + ") — INTENT forced to DO NOT APPLY")

    # 10. Book correlation stated; no second-entry narrative inside the GTC zone.
    if p.asset.upper() == "BTC" and p.side == "LONG" and _num(e) and abs(e - C.BTC_GTC) / C.BTC_GTC < 0.01:
        f.append(f"10 entry sits inside the existing BTC GTC zone @${C.BTC_GTC:,.0f} — no second-entry narrative")

    # 11. Size hint is % of DeFi sleeve only.
    s = p.size_hint_pct_defi_sleeve
    if not _num(s) or s <= 0 or s > 100:
        f.append("11 size hint must be a % of the DeFi sleeve (0-100]")
    if any(tok in (p.correlation_note + p.advisory_risk).upper() for tok in ("SELL VTI", "SELL IBIT", "TRIM VTI", "TRIM IBIT", "REPLACE VTI", "REPLACE IBIT")):
        f.append("11 packet touches HOLD VTI+IBIT — that book is CrashForge's lane")

    # 12. Novelty line names the nearest ledger id (or says the ledger is missing).
    if p.novelty_ledger_id.startswith("NONE (ledger missing)"):
        f.append("12 ledger missing — novelty cannot be claimed")
    if "only wording changed" in p.novelty_reason:
        f.append("12 copy of a ledger entry from the last 5 sessions")

    # 13. DeFi checklist — fail closed.
    d = p.defi
    if d.paused_or_upgrading is not False:
        f.append("13 pause/upgrade status unknown or true => UNPROVEN")
    if d.bad_debt_or_admin_key_or_unaudited is not False:
        f.append("13 bad-debt/admin-key/unaudited unknown or true => UNPROVEN")
    if d.slippage_edge_fraction is None or d.slippage_edge_fraction > C.SLIPPAGE_MAX_EDGE_FRACTION:
        f.append(f"13 slippage unknown or eats >{C.SLIPPAGE_MAX_EDGE_FRACTION:.0%} of edge")
    if d.is_borrow_lend and (d.current_rate is None or d.rate_kill is None):
        f.append("13 borrow/lend rail needs current rate and rate-kill")
    if d.gas_mev_net_fraction is None or d.gas_mev_net_fraction >= C.GAS_MAX_NET_FRACTION:
        f.append(f"13 gas+MEV unknown or >= {C.GAS_MAX_NET_FRACTION:.0%} of expected net")
    if d.settlement_seconds is None or d.settlement_seconds > C.LAG_STALE_S:
        if p.intent == "APPLY":
            f.append(f"13 settlement can exceed {C.LAG_STALE_S}s => not LIVE-eligible")
    if any(w in d.custody_path.upper() for w in C.WRAPPER_TOKENS):
        f.append("13 custody path wraps into a TradFi product")

    return GateResult(not f, f, near_miss=(len(f) == 1))
