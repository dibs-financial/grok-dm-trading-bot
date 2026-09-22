"""CrashForge hard-lock precheck. Read-only. Fail closed: an unknown input is a FAIL for packets.

Locks: VIX22 / CII0.08 / SPY5d-4% / ARM LIVE!=ADD / lag>20=STALE / front-run invalid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C


@dataclass
class LockInputs:
    vix: float | None = None
    cii: float | None = None
    spy_5d_return: float | None = None          # e.g. -0.031 for -3.1%
    arm_live_would_add: bool | None = False      # True if the idea would ADD to an already-LIVE row
    lag_seconds: float | None = None             # tape / settlement lag
    front_run_suspected: bool | None = False


@dataclass
class LockResult:
    results: dict[str, str] = field(default_factory=dict)   # lock name -> PASS | FAIL | WARN
    reasons: list[str] = field(default_factory=list)

    @property
    def any_fail(self) -> bool:
        return any(v == "FAIL" for v in self.results.values())

    @property
    def status(self) -> str:
        """OK | WARN | FAIL — for the heartbeat 'locks:' field."""
        if self.any_fail:
            return "FAIL"
        if any(v == "WARN" for v in self.results.values()):
            return "WARN"
        return "OK"

    def render(self) -> str:
        return " / ".join(f"{k}:{v}" for k, v in self.results.items())


def check(i: LockInputs) -> LockResult:
    r = LockResult()

    def put(name: str, verdict: str, why: str = "") -> None:
        r.results[name] = verdict
        if why:
            r.reasons.append(f"{name}: {why}")

    if i.vix is None:
        put("VIX22", "FAIL", "VIX unknown (fail closed)")
    elif i.vix >= C.VIX_LOCK:
        put("VIX22", "FAIL", f"VIX {i.vix:.2f} >= {C.VIX_LOCK}")
    elif i.vix >= C.VIX_WARN:
        put("VIX22", "WARN", f"VIX {i.vix:.2f} approaching {C.VIX_LOCK}")
    else:
        put("VIX22", "PASS")

    if i.cii is None:
        put("CII0.08", "FAIL", "CII unknown (fail closed)")
    elif i.cii <= C.CII_LOCK:
        put("CII0.08", "FAIL", f"CII {i.cii:.3f} <= {C.CII_LOCK}")
    elif i.cii <= C.CII_WARN:
        put("CII0.08", "WARN", f"CII {i.cii:.3f} approaching {C.CII_LOCK}")
    else:
        put("CII0.08", "PASS")

    if i.spy_5d_return is None:
        put("SPY5d-4%", "FAIL", "SPY 5d return unknown (fail closed)")
    elif i.spy_5d_return <= C.SPY5D_LOCK:
        put("SPY5d-4%", "FAIL", f"SPY 5d {i.spy_5d_return:+.2%} <= {C.SPY5D_LOCK:.0%}")
    elif i.spy_5d_return <= C.SPY5D_WARN:
        put("SPY5d-4%", "WARN", f"SPY 5d {i.spy_5d_return:+.2%} approaching {C.SPY5D_LOCK:.0%}")
    else:
        put("SPY5d-4%", "PASS")

    if i.arm_live_would_add is None or i.arm_live_would_add:
        put("ARM LIVE!=ADD", "FAIL", "idea would ADD to an already-LIVE row (or unknown)")
    else:
        put("ARM LIVE!=ADD", "PASS")

    if i.lag_seconds is None:
        put("lag>20=STALE", "FAIL", "lag unknown (fail closed)")
    elif i.lag_seconds > C.LAG_STALE_S:
        put("lag>20=STALE", "FAIL", f"lag {i.lag_seconds:.0f}s > {C.LAG_STALE_S}s = STALE")
    elif i.lag_seconds > C.LAG_WARN_S:
        put("lag>20=STALE", "WARN", f"lag {i.lag_seconds:.0f}s > {C.LAG_WARN_S}s")
    else:
        put("lag>20=STALE", "PASS")

    if i.front_run_suspected is None or i.front_run_suspected:
        put("front-run invalid", "FAIL", "front-run suspected (or unknown)")
    else:
        put("front-run invalid", "PASS")
    return r
