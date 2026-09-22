"""Candidate generation. The advisor PROPOSES; the gate DECIDES.

  NullAdvisor  - proposes nothing (default). The desk stays silent unless a trigger fires.
  FileAdvisor  - loads candidate packets from a JSON file (a human or another tool wrote them).
  GrokAdvisor  - asks an OpenAI-compatible chat endpoint (xAI Grok by default) to draft candidate
                 packets as JSON from the Drive context pack + tape. Needs XAI_API_KEY. Optional.

No advisor output is ever posted without passing dm_desk.gate.qualify().
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

from .packet import Packet

SYSTEM_PROMPT = """You are the DM research desk described in DM Daily Plan v2. Advisory only.
Propose at most 2 candidate strategy packets as a JSON list, or an empty list if the tape does not
support a trade. Rails must be DeFi-native (spot BTC, spot ETH, Aave v3 <chain>, or a venue named
in the Drive memo). Never IBIT/VTI/ETF/wrappers. Never touch HOLD VTI+IBIT or the BTC GTC @$77716.
Every candidate must be a complete Packet object with numeric entry/target/invalidation, an
observable if-then trigger, an ISO time_stop, rr after slippage+gas, size_hint_pct_defi_sleeve,
trigger_family, and advisory_risk. Do not invent history or live checks: leave history.n = 0 and
live.level_still_present = null; the desk fills those from data. Do not invent to fill a slot."""


class Advisor(Protocol):
    name: str
    def propose(self, context: str) -> list[Packet]: ...


class NullAdvisor:
    name = "null"
    def propose(self, context: str) -> list[Packet]:
        return []


class FileAdvisor:
    name = "file"
    def __init__(self, path: str):
        self.path = path
    def propose(self, context: str) -> list[Packet]:
        with open(self.path) as fh:
            rows = json.load(fh)
        return [Packet.from_dict(r) for r in rows]


class GrokAdvisor:
    name = "grok"

    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None, timeout: float = 60.0):
        self.model = model or os.environ.get("XAI_MODEL", "grok-4")
        self.base_url = (base_url or os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("GrokAdvisor needs XAI_API_KEY")

    def propose(self, context: str) -> list[Packet]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": context + "\n\nReturn ONLY a JSON list of Packet objects."}],
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            content = json.load(r)["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        if start < 0 or end < 0:
            return []
        try:
            rows = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return []
        return [Packet.from_dict(r) for r in rows if isinstance(r, dict)]


def make_advisor(kind: str = "null", path: str | None = None) -> Advisor:
    if kind == "null":
        return NullAdvisor()
    if kind == "file":
        if not path:
            raise ValueError("file advisor needs --candidates")
        return FileAdvisor(path)
    if kind == "grok":
        return GrokAdvisor()
    if kind == "engine":
        from .engine.solver import EngineAdvisor
        from .ledger import Ledger
        import os
        from . import config as C
        return EngineAdvisor(Ledger(os.path.join(C.DATA_DIR, "ledger.jsonl")), venues_path=path)
    raise ValueError(f"unknown advisor kind {kind!r}")
