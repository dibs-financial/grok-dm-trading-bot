"""EOD review block (weekdays 16:00 America/Chicago). Cap 12 lines. Not a strategy slot."""
from __future__ import annotations

from dataclasses import dataclass

from . import config as C

TAPE_VS_PLAN = ("HIT", "MISS", "NO-TRIGGER", "INVALIDATED", "EXPIRED", "none")
PACKET_STATES = ("none", "posted", "applied-by-user", "ignored")


@dataclass
class EodInput:
    date: str
    gameplan_posted: bool
    scans_done: int
    scans_expected: int
    silence_kept: bool
    packet: str = "none"
    tape_vs_plan: str = "none"
    lesson: str = "no packet; nothing to score beyond process"
    seed: str = ""
    p0_process_miss: bool = False
    p1_packet_quality: str = "n/a"
    p2_outcome: str = "n/a"
    applied: bool = False


def render(e: EodInput) -> str:
    assert e.packet in PACKET_STATES, e.packet
    assert e.tape_vs_plan in TAPE_VS_PLAN, e.tape_vs_plan
    p2 = e.p2_outcome if e.applied else "n/a (not applied — no P&L theater)"
    lines = [
        f"EOD [{e.date}]",
        f"PROCESS: 6:45 posted {'Y' if e.gameplan_posted else 'N'} | 4h scans completed {e.scans_done}/{e.scans_expected} | silence rule kept {'Y' if e.silence_kept else 'N'}",
        f"PACKET: {e.packet}",
        f"TAPE vs PLAN: {e.tape_vs_plan}",
        f"LESSON: {_one_sentence(e.lesson)}",
        f"SEED TOMORROW: {e.seed or 'watch the latest memo levels; no pre-written strategy'}",
        f"SCORE: P0 process miss {'YES' if e.p0_process_miss else 'no'} | P1 packet quality {e.p1_packet_quality} | P2 outcome {p2}",
        "  Outcome never outranks process. No P&L theater if you did not APPLY.",
    ]
    assert len(lines) <= C.EOD_MAX_LINES
    return "\n".join(lines)


def _one_sentence(s: str) -> str:
    s = " ".join(s.split())
    for sep in (". ", "; "):
        if sep in s:
            s = s.split(sep)[0] + "."
            break
    return s[:220]
