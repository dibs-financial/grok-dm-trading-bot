"""python3 -m dm_desk <command> [options]

Commands:
  scan        one 4h scan (silent unless a trigger fires; heartbeat to desk log)
  gameplan    weekday 6:45 game plan (+ packet only if it clears the gate)
  eod         weekday 16:00 EOD review
  run         wall-clock loop (scan / gameplan / eod forever)
  ledger      print the packet ledger
  outcome ID STATUS|OUTCOME   update a ledger row, e.g. outcome DM-20260922-01 applied-by-user
  check FILE  qualify candidate packets in a JSON file without posting (dry run)

Options:
  --tape coinbase|file  --tape-file PATH      (default coinbase)
  --drive knowledge|folder --drive-folder PATH (default knowledge)
  --advisor null|file|grok --candidates PATH   (default null)
  --locks PATH   JSON with vix, cii, spy_5d_return, arm_live_would_add, front_run_suspected
  --data-dir PATH   --force (run gameplan/eod even on weekend/holiday)  --quiet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from . import config as C
from .advisor import make_advisor
from .desk import Desk, Sinks, TZ
from .drive import make_drive
from .gate import qualify
from .ledger import Ledger
from .locks import LockInputs
from .packet import Packet
from .tape import make_tape


def _locks(path: str | None) -> LockInputs:
    if not path:
        return LockInputs()
    with open(path) as fh:
        return LockInputs(**json.load(fh))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dm_desk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--tape", default="coinbase")
    ap.add_argument("--tape-file")
    ap.add_argument("--drive", default="knowledge")
    ap.add_argument("--drive-folder")
    ap.add_argument("--advisor", default="null")
    ap.add_argument("--candidates")
    ap.add_argument("--locks")
    ap.add_argument("--data-dir", default=C.DATA_DIR)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.command == "ledger":
        for e in Ledger(f"{a.data_dir}/ledger.jsonl").entries:
            print(f"{e.id} {e.rail} {e.asset} {e.trigger_family} {e.intent} status={e.status} eod={e.outcome_eod} t5={e.outcome_t5}")
        return 0
    if a.command == "outcome":
        pid, val = a.args
        led = Ledger(f"{a.data_dir}/ledger.jsonl")
        led.update(pid, **({"status": val} if val in ("posted", "applied-by-user", "ignored", "killed") else {"outcome_eod": val}))
        print("updated", pid)
        return 0
    if a.command == "check":
        with open(a.args[0]) as fh:
            rows = json.load(fh)
        now = datetime.now(TZ)
        for r in rows:
            p = Packet.from_dict(r)
            g = qualify(p, scan_start=now - timedelta(hours=C.SCAN_INTERVAL_HOURS), now=now)
            print(f"{p.packet_id or '(no id)'}: {'PASS' if g.passed else 'FAIL'} — {g.reason_line()}")
        return 0

    try:
        tape = make_tape(a.tape, a.tape_file)
        drive = make_drive(a.drive, a.drive_folder)
    except Exception as e:  # noqa: BLE001
        print(f"PROBLEM: {e}", file=sys.stderr)
        tape, drive = None, None
    desk = Desk(drive=drive, tape=tape, advisor=make_advisor(a.advisor, a.candidates), sinks=Sinks(a.data_dir, echo=not a.quiet),
                lock_inputs=_locks(a.locks), data_dir=a.data_dir)
    if a.command == "scan":
        rep = desk.scan()
        print(rep.heartbeat if a.quiet else "")
    elif a.command == "gameplan":
        desk.gameplan(force=a.force)
    elif a.command == "eod":
        desk.eod(force=a.force)
    elif a.command == "run":
        from .scheduler import run
        run(desk)
    else:
        ap.error(f"unknown command {a.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
