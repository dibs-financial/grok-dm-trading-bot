"""Constants for the DM desk. Every number here is quoted from docs/DM_DAILY_PLAN_v2.md.

Tunables the plan explicitly marks as tunable (MIN_RR, MIN_HISTORY_N) can be overridden
with environment variables DM_MIN_RR and DM_MIN_HISTORY_N. Hard locks are NOT tunable here:
the desk never rewrites CrashForge locks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

TZ = "America/Chicago"

# --- CrashForge hard locks (read-only for this desk) -------------------------------
VIX_LOCK = 22.0          # VIX22
VIX_WARN = 20.0          # approach
CII_LOCK = 0.08          # CII0.08 (lock when CII <= 0.08)
CII_WARN = 0.10          # approach
SPY5D_LOCK = -0.04       # SPY 5-day return <= -4%
SPY5D_WARN = -0.03       # approach
LAG_STALE_S = 20         # lag>20 = STALE
LAG_WARN_S = 15          # approach
LOCK_NAMES = ("VIX22", "CII0.08", "SPY5d-4%", "ARM LIVE!=ADD", "lag>20=STALE", "front-run invalid")

# --- Qualification gate -------------------------------------------------------------
MIN_RR = float(os.environ.get("DM_MIN_RR", "2.0"))
MIN_HISTORY_N = int(os.environ.get("DM_MIN_HISTORY_N", "3"))
NOVELTY_WINDOW_SESSIONS = 5
SLIPPAGE_MAX_EDGE_FRACTION = 0.25    # slippage eating >25% of edge => silent
GAS_MAX_NET_FRACTION = 0.20          # gas+MEV >= 20% of expected net => drop
LEVEL_PROXIMITY_P1 = 0.01            # watched level inside 1% with no packet => P1

# --- Book context the desk respects ------------------------------------------------
BTC_GTC = 77716.0
DESK_R = "KEEP"
HOLD_BOOK = ("VTI", "IBIT")

# --- Rails ---------------------------------------------------------------------------
DEFI_RAILS = ("spot BTC", "spot ETH", "Aave v3")
WRAPPER_TOKENS = ("IBIT", "VTI", "ETF", "ETN", "GBTC", "FBTC", "ARKB", "BITB", "HODL", "BTCO",
                  "ETHA", "FETH", "ETHE", "THYP", "BHYP", "HYPG", "ZCSH", "MSTR", "STRC", "BROKER")

# --- Schedule ------------------------------------------------------------------------
SCAN_INTERVAL_HOURS = 4
GAMEPLAN_TIME = (6, 45)
EOD_TIME = (16, 0)
EOD_MAX_LINES = 12
DRIVE_DOWN_P0_HOURS = 2
DRIVE_FAIL_SCANS_PROBLEM = 3

# NYSE full-day holidays, 2026. Extend as needed.
US_MARKET_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}

DATA_DIR = os.environ.get("DM_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


@dataclass
class Book:
    btc_gtc: float = BTC_GTC
    desk_r: str = DESK_R
    hold: tuple[str, ...] = HOLD_BOOK
    extra_defi_rails: tuple[str, ...] = field(default_factory=tuple)  # rails named in latest Drive memo
