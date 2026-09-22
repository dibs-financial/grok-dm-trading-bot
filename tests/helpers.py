"""Shared fixtures: a candidate packet that passes every gate item, and synthetic candles."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dm_desk import config as C
from dm_desk.packet import DefiCheck, HistoryEvidence, LiveCheck, Packet
from dm_desk.tape import Candle

TZ = ZoneInfo(C.TZ)


def now() -> datetime:
    return datetime.now(TZ)


def good_packet(**over) -> Packet:
    n = now()
    p = Packet(
        packet_id="DM-20260922-01", intent="APPLY", rail="spot ETH", asset="ETH", venue="Coinbase Exchange",
        side="LONG", entry=2700.0, trigger="if ETH daily close > 2750 with funding < 0.01%",
        trigger_family="eth-breakout-2750", invalidation=2600.0, time_stop=(n + timedelta(days=3)).isoformat(timespec="seconds"),
        target=2950.0, rr=2.3, size_hint_pct_defi_sleeve=10.0,
        lock_check={k: "PASS" for k in C.LOCK_NAMES},
        defi=DefiCheck(protocol="spot ETH", version="", chain="CEX", venue="Coinbase Exchange", paused_or_upgrading=False,
                       bad_debt_or_admin_key_or_unaudited=False, slippage_edge_fraction=0.05, custody_path="wallet",
                       gas_mev_net_fraction=0.02, settlement_seconds=5),
        correlation="add", correlation_note="ETH beta, not the BTC GTC zone",
        history=HistoryEvidence(timeframe="1D", n=4, hit_before_invalidate=3, last_dates=["2026-06-21", "2026-07-13", "2026-08-20"]),
        live=LiveCheck(timestamp=n.isoformat(timespec="seconds"), source="test", level_still_present=True, liquidity_at_size=True, traded_through_without_reload=False),
        novelty_ledger_id="DM-20260915-01", novelty_reason="new trigger family vs the last 5 sessions",
        advisory_risk="Trump-Xi breakdown Thursday; ETF flows flip negative",
        drive_latest="Drive latest: 2026-09-21_memo.pdf (2026-09-21)",
    )
    for k, v in over.items():
        setattr(p, k, v)
    return p


def candles(prices: list[float], start_ts: float | None = None, spread: float = 0.01) -> list[Candle]:
    t0 = start_ts or (time.time() - 86400 * len(prices))
    return [Candle(ts=t0 + i * 86400, open=p, high=p * (1 + spread), low=p * (1 - spread), close=p) for i, p in enumerate(prices)]
