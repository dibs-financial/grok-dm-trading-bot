"""Registry of the four desks and their shared contract.

knowledge  -> owns knowledge/ (the box). Ingest, extract, index. Never trades, never scores.
research   -> DM desk (Daily Plan v2). 4h scan, 6:45 game plan, 16:00 EOD. Advisory only; never APPLYs.
engine     -> KB strategy engine. Proposes candidates to the research desk. Never emits on its own.
execution  -> CrashForge operator. Fires only from operator-ARMED standing-order rows; locks outrank EV.

Shared: config.py (one clock, one lock set, one book), Sinks (user thread / desk log / handoff),
Ledger (append-only), the engine Bus, DATA_DIR.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as C

TZ = ZoneInfo(C.TZ)
DESKS = ("knowledge", "research", "engine", "execution")

SCHEDULE = [
    # (desk, HH:MM America/Chicago or 'every 4h', weekdays only?, what)
    ("knowledge", "every 4h", False, "Circle/Drive sync; ingest on arrival; rebuild indexes"),
    ("engine", "every 4h", False, "KB-Scanner delta -> pattern atlas -> links"),
    ("research", "every 4h", False, "scan: silent unless a trigger fires; heartbeat to desk log"),
    ("research", "06:45", True, "game plan to user thread; packet only if it clears the gate"),
    ("execution", "08:25", True, "pre-bell fire window: ARMED rows that match tape and pass all locks fire"),
    ("execution", "every 4h", False, "manage LIVE rows: target / invalidation / expiry -> flatten, log"),
    ("research", "16:00", True, "EOD review, 12 lines, no new strategy"),
]

MAY_NOT = {
    "knowledge": ["score or rank trades", "invent content for missing weeks", "store member PII"],
    "research": ["place trades", "ARM LIVE", "APPLY", "rewrite locks", "hand off wrappers", "invent a packet to fill the slot"],
    "engine": ["emit a packet without the research gate", "claim quantum hardware", "emit more than once per day"],
    "execution": ["fire from a desk packet that has no ARMED row", "override a hard lock with EV", "ADD to a LIVE row", "touch HOLD VTI+IBIT"],
}


def status_all(data_dir: str = C.DATA_DIR) -> dict:
    from .knowledge_desk import KnowledgeDesk
    from .execution import ExecutionDesk, StandingOrders
    from .ledger import Ledger
    import os
    kb = KnowledgeDesk(data_dir)
    ex = ExecutionDesk(tape=None, orders=StandingOrders(os.path.join(data_dir, "standing_orders.jsonl")), data_dir=data_dir)
    led = Ledger(os.path.join(data_dir, "ledger.jsonl"))
    return {"now": datetime.now(TZ).isoformat(timespec="minutes"), "knowledge": kb.heartbeat(), "execution": ex.heartbeat(),
            "research": f"ledger:{'present' if led.present else 'MISSING'} entries:{len(led.entries)} open:{len(led.open_packets())}",
            "engine": "runs inside research 6:45 when --advisor engine; standalone via `engine mine|solve|links`"}
