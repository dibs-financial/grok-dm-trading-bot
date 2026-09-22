"""Strategy-Emitter: wrap a gate-passed packet in the daily strategy template (docs/KB_STRATEGY_ENGINE.md §5)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..packet import Packet


def render(p: Packet, fingerprint: str, pattern_ids: list[str], nearest_id: str, distance: float) -> str:
    cites = sorted({c for c in (p.correlation_note + " " + p.drive_latest).split() if c.startswith("[DM")} | {p.drive_latest.split("(")[0].strip()})
    lines = [
        f"strategy_id: {p.packet_id}",
        f"date_utc: {datetime.now(timezone.utc):%Y-%m-%d}",
        f"fingerprint: {fingerprint}",
        f"pattern_ids: [{', '.join(pattern_ids)}]",
        f"kb_citations: [{', '.join(cites)}]",
        f"thesis: {p.side} {p.asset} on {p.rail} at {p.entry_text()} if the trigger prints; invalidation {p.invalidation}; target {p.target}.",
        "packet:",
    ] + ["  " + l for l in p.render().splitlines()] + [
        "steps:",
        f"  1. precondition check: {p.drive_latest}; locks {', '.join(f'{k} {v}' for k, v in p.lock_check.items())}; live level present={p.live.level_still_present}",
        f"  2. venue + custody: {p.venue or p.defi.venue or 'UNSET'} / {p.defi.custody_path or 'UNSET'}; size {p.size_hint_pct_defi_sleeve}% of DeFi sleeve; limit order at {p.entry_text()}",
        f"  3. trigger monitor: {p.trigger}",
        f"  4. invalidation order placed with the entry at {p.invalidation}",
        f"  5. time stop: cancel unfilled / close if no trigger by {p.time_stop}",
        "  6. ledger update at EOD and T+5 (outcome_eod / outcome_t5)",
        f"novelty: nearest ledger #{nearest_id or 'NONE'}; fingerprint distance {1 - distance:.2f}; {p.novelty_reason}",
        "USER ACTION: APPLY or ignore. DM will not APPLY. CrashForge must not silent-fire.",
    ]
    return "\n".join(lines)
