"""Tape providers: live quotes + historical candles for BTC/ETH (and other symbols).

Providers are pluggable. The default live provider hits Coinbase Exchange public endpoints
(no key). FileTape reads a JSON fixture for offline runs and tests. Every quote carries a
timestamp so the desk can compute lag (lag>20 = STALE).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class TapeError(RuntimeError):
    pass


@dataclass
class Quote:
    symbol: str
    price: float
    ts: float            # unix seconds of the quote itself
    source: str

    @property
    def lag_seconds(self) -> float:
        return max(0.0, time.time() - self.ts)


@dataclass
class Candle:
    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def date(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%Y-%m-%d")


class TapeProvider(Protocol):
    name: str
    def quote(self, symbol: str) -> Quote: ...
    def candles(self, symbol: str, granularity_s: int = 86400, limit: int = 300) -> list[Candle]: ...


_PRODUCTS = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "HYPE": None, "ZEC": "ZEC-USD"}


class CoinbaseTape:
    name = "coinbase-exchange-public"
    base = "https://api.exchange.coinbase.com"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def _get(self, path: str):
        req = urllib.request.Request(self.base + path, headers={"User-Agent": "dm-desk/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            raise TapeError(f"coinbase {path}: {e}") from e

    def quote(self, symbol: str) -> Quote:
        product = _PRODUCTS.get(symbol.upper(), f"{symbol.upper()}-USD")
        if not product:
            raise TapeError(f"no Coinbase product for {symbol}")
        d = self._get(f"/products/{product}/ticker")
        ts = datetime.fromisoformat(d["time"].replace("Z", "+00:00")).timestamp()
        return Quote(symbol.upper(), float(d["price"]), ts, self.name)

    def candles(self, symbol: str, granularity_s: int = 86400, limit: int = 300) -> list[Candle]:
        product = _PRODUCTS.get(symbol.upper(), f"{symbol.upper()}-USD")
        rows = self._get(f"/products/{product}/candles?granularity={granularity_s}")
        out = [Candle(ts=r[0], low=r[1], high=r[2], open=r[3], close=r[4], volume=r[5]) for r in rows]
        out.sort(key=lambda c: c.ts)
        return out[-limit:]


class FileTape:
    """JSON fixture: {"quotes": {"BTC": {"price": 86200, "ts": <unix>}}, "candles": {"BTC": [[ts,o,h,l,c,v], ...]}}"""
    name = "file"

    def __init__(self, path: str):
        self.path = path
        with open(path) as fh:
            self.data = json.load(fh)

    def quote(self, symbol: str) -> Quote:
        q = self.data.get("quotes", {}).get(symbol.upper())
        if not q:
            raise TapeError(f"no fixture quote for {symbol}")
        ts = q.get("ts") or time.time()
        return Quote(symbol.upper(), float(q["price"]), float(ts), f"file:{os.path.basename(self.path)}")

    def candles(self, symbol: str, granularity_s: int = 86400, limit: int = 300) -> list[Candle]:
        rows = self.data.get("candles", {}).get(symbol.upper(), [])
        return [Candle(*r) for r in rows][-limit:]


def make_tape(kind: str = "coinbase", path: str | None = None) -> TapeProvider:
    if kind == "coinbase":
        return CoinbaseTape()
    if kind == "file":
        if not path:
            raise ValueError("file tape needs --tape-file")
        return FileTape(path)
    raise ValueError(f"unknown tape kind {kind!r}")
