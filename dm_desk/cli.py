"""python3 -m dm_desk <desk> <command> [options]

Desks:
  knowledge  status | ingest PATH | sync --spaces "A,B" [--profile v1|v2]
  research   scan | gameplan | eod | run | ledger | outcome ID STATUS|OUTCOME | check FILE
  engine     scan | mine | solve | links
  execution  rows | arm --from-packet ID [--size PCT] | arm --asset A --side LONG --rail "spot BTC" --low X --high Y --size PCT --expires ISO
             fire | manage | resolve --issue TEXT --edge BPS [--slippage BPS] [--gas BPS] | cancel ID
  status     one line per desk

Options (shared):
  --tape coinbase|file  --tape-file PATH      --drive knowledge|folder --drive-folder PATH
  --advisor null|file|grok|engine --candidates PATH   --locks PATH   --broker paper|robinhood
  --data-dir PATH   --force   --quiet

Legacy single-word commands (scan, gameplan, eod, run, ledger, outcome, check) map to the research desk.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from . import config as C
from .locks import LockInputs

LEGACY = {"scan", "gameplan", "eod", "run", "ledger", "outcome", "check"}


def _locks(path: str | None) -> LockInputs:
    if not path:
        return LockInputs()
    with open(path) as fh:
        return LockInputs(**json.load(fh))


def _tape_drive(a):
    from .drive import make_drive
    from .tape import make_tape
    try:
        return make_tape(a.tape, a.tape_file), make_drive(a.drive, a.drive_folder)
    except Exception as e:  # noqa: BLE001
        print(f"PROBLEM: {e}", file=sys.stderr)
        return None, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dm_desk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("desk")
    ap.add_argument("command", nargs="?")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--tape", default="coinbase"); ap.add_argument("--tape-file")
    ap.add_argument("--drive", default="knowledge"); ap.add_argument("--drive-folder")
    ap.add_argument("--advisor", default="null"); ap.add_argument("--candidates")
    ap.add_argument("--locks"); ap.add_argument("--broker", default="paper")
    ap.add_argument("--data-dir", default=C.DATA_DIR); ap.add_argument("--force", action="store_true"); ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--spaces", default=""); ap.add_argument("--profile", default="v2")
    ap.add_argument("--from-packet"); ap.add_argument("--asset"); ap.add_argument("--side"); ap.add_argument("--rail")
    ap.add_argument("--low", type=float); ap.add_argument("--high", type=float); ap.add_argument("--size", type=float); ap.add_argument("--expires")
    ap.add_argument("--issue", default="manual"); ap.add_argument("--edge", type=float, default=50.0)
    ap.add_argument("--slippage", type=float, default=5.0); ap.add_argument("--gas", type=float, default=1.0)
    a = ap.parse_args(argv)

    desk, cmd = a.desk, a.command
    if desk in LEGACY:                       # legacy: `dm_desk scan` == `dm_desk research scan`
        if cmd is not None:
            a.args = [cmd] + a.args
        desk, cmd = "research", desk
    import os
    data = a.data_dir
    os.makedirs(data, exist_ok=True)

    if desk == "status":
        from .desks import status_all
        print(json.dumps(status_all(data), indent=1)); return 0

    if desk == "knowledge":
        from .knowledge_desk import KnowledgeDesk
        kd = KnowledgeDesk(data)
        if cmd == "status":
            print(json.dumps(kd.status(), indent=1))
        elif cmd == "ingest":
            print(kd.ingest(a.args[0]))
        elif cmd == "sync":
            try:
                print(json.dumps(kd.sync_circle([s for s in a.spaces.split(",") if s.strip()], profile=a.profile), indent=1))
            except Exception as e:  # noqa: BLE001
                print(f"PROBLEM: Circle unavailable — {e}", file=sys.stderr); return 2
        else:
            ap.error("knowledge: status | ingest PATH | sync")
        return 0

    if desk == "engine":
        from .engine.scanner import Scanner
        from .engine.patterns import mine, save
        stage = cmd or "scan"
        eng_dir = os.path.join(data, "engine")
        res = Scanner(data_dir=eng_dir).scan()
        print(f"scan: changed={res['changed']} delta={ {k: len(v) for k, v in res['delta'].items()} } triples={len(res['store'].triples)}")
        if stage == "links":
            from .engine.links import build
            for n in sorted(build(), key=lambda n: -n.priority)[:10]:
                print(f"{n.cite} priority={n.priority:.3f} novelty={n.novelty:.2f} linkage={n.linkage:.2f} links={n.links}")
        if stage in ("mine", "solve"):
            atlas = mine(res["store"]); save(atlas, os.path.join(eng_dir, "atlas.json"))
            print(f"atlas: as_of={atlas.as_of} levels={len(atlas.levels)} motifs={len(atlas.motifs)} catalysts={len(atlas.catalyst_outcomes)} last={atlas.last_price}")
            for l in [l for l in atlas.levels if l.recurrence >= 2][:8]:
                print(f"  {l.id} recurrence={l.recurrence} held={l.held} failed={l.failed} roles={l.role_counts} aliases={l.aliases}")
        if stage == "solve":
            from .engine.solver import EngineAdvisor
            from .ledger import Ledger
            led = Ledger(os.path.join(data, "ledger.jsonl"))
            if not led.present:
                led._write()
            adv = EngineAdvisor(led, data_dir=eng_dir, venues_path=a.candidates)
            for p in adv.propose(""):
                print("--- candidate ---"); print(p.render())
            print("report:", json.dumps(adv.last_report, indent=1))
        return 0

    if desk == "execution":
        from .execution import ExecutionDesk, PaperBroker, RobinhoodBroker, StandingOrders, resolve
        from .desk import Sinks
        from .locks import check as lock_check
        orders = StandingOrders(os.path.join(data, "standing_orders.jsonl"))
        if cmd == "rows":
            for r in orders.rows:
                print(f"{r.id} {r.status} {r.side} {r.asset} {r.rail} band=[{r.entry_low:,.2f},{r.entry_high:,.2f}] size={r.size_pct}% exp={r.expires} packet={r.packet_id}")
            return 0
        if cmd == "arm":
            if a.from_packet:
                from .ledger import Ledger
                e = Ledger(os.path.join(data, "ledger.jsonl")).get(a.from_packet)
                if not e:
                    print(f"no packet {a.from_packet} on ledger", file=sys.stderr); return 2
                row = orders.from_packet(e.packet, size_pct=a.size)
            else:
                row = orders.arm(asset=a.asset, side=a.side, rail=a.rail, entry_low=a.low, entry_high=a.high, size_pct=a.size,
                                 invalidation=None, target=None, expires=a.expires)
            print(f"ARMED {row.id} {row.side} {row.asset} {row.rail} band=[{row.entry_low:,.2f},{row.entry_high:,.2f}] size={row.size_pct}% exp={row.expires}")
            return 0
        if cmd == "cancel":
            orders.set_status(a.args[0], "CANCELLED"); print("CANCELLED", a.args[0]); return 0
        if cmd == "resolve":
            li = _locks(a.locks); li.lag_seconds = li.lag_seconds if li.lag_seconds is not None else 1.0
            print(json.dumps(resolve(a.issue, a.edge, a.slippage, a.gas, lock_check(li)).__dict__, indent=1)); return 0
        tape, _ = _tape_drive(a)
        broker = PaperBroker() if a.broker == "paper" else RobinhoodBroker()
        ex = ExecutionDesk(tape, broker, orders, _locks(a.locks), data, Sinks(data, echo=not a.quiet))
        if cmd == "fire":
            print(json.dumps(ex.fire(force=a.force), indent=1))
        elif cmd == "manage":
            print(json.dumps(ex.manage(), indent=1))
        else:
            ap.error("execution: rows | arm | cancel ID | fire | manage | resolve")
        return 0

    if desk == "research":
        from .advisor import make_advisor
        from .desk import Desk, Sinks, TZ
        from .ledger import Ledger
        if cmd == "ledger":
            for e in Ledger(os.path.join(data, "ledger.jsonl")).entries:
                print(f"{e.id} {e.rail} {e.asset} {e.trigger_family} {e.intent} status={e.status} eod={e.outcome_eod} t5={e.outcome_t5}")
            return 0
        if cmd == "outcome":
            pid, val = a.args
            Ledger(os.path.join(data, "ledger.jsonl")).update(pid, **({"status": val} if val in ("posted", "applied-by-user", "ignored", "killed") else {"outcome_eod": val}))
            print("updated", pid); return 0
        if cmd == "check":
            from .gate import qualify
            from .packet import Packet
            now = datetime.now(TZ)
            for r in json.load(open(a.args[0])):
                p = Packet.from_dict(r); g = qualify(p, scan_start=now - timedelta(hours=C.SCAN_INTERVAL_HOURS), now=now)
                print(f"{p.packet_id or '(no id)'}: {'PASS' if g.passed else 'FAIL'} — {g.reason_line()}")
            return 0
        tape, drive = _tape_drive(a)
        desk_obj = Desk(drive=drive, tape=tape, advisor=make_advisor(a.advisor, a.candidates), sinks=Sinks(data, echo=not a.quiet),
                        lock_inputs=_locks(a.locks), data_dir=data)
        if cmd == "scan":
            rep = desk_obj.scan(); print(rep.heartbeat if a.quiet else "")
        elif cmd == "gameplan":
            desk_obj.gameplan(force=a.force)
        elif cmd == "eod":
            desk_obj.eod(force=a.force)
        elif cmd == "run":
            from .scheduler import run
            from .execution import ExecutionDesk, PaperBroker, StandingOrders
            ex = ExecutionDesk(tape, PaperBroker() if a.broker == "paper" else None, StandingOrders(os.path.join(data, "standing_orders.jsonl")), _locks(a.locks), data, desk_obj.sinks)
            run(desk_obj, execution=ex)
        else:
            ap.error("research: scan | gameplan | eod | run | ledger | outcome | check")
        return 0
    ap.error(f"unknown desk {desk!r}; see --help")
    return 2


if __name__ == "__main__":
    sys.exit(main())
