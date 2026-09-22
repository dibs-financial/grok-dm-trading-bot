"""End-to-end: scan / gameplan / eod against offline fixtures in a temp data dir."""
import json, os, tempfile, time, unittest
from datetime import timedelta

from dm_desk.advisor import FileAdvisor, NullAdvisor
from dm_desk.desk import Desk, Sinks
from dm_desk.drive import KnowledgeDrive
from dm_desk.locks import LockInputs
from dm_desk.tape import FileTape
from tests.helpers import now

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(REPO, "examples")
GOOD_LOCKS = LockInputs(vix=16.5, cii=0.21, spy_5d_return=0.012, arm_live_would_add=False, front_run_suspected=False)


def fresh_tape(path):
    """Copy the example tape but stamp quotes 'now' and push the ETH time stop into the future."""
    d = json.load(open(os.path.join(EX, "tape.json")))
    for q in d["quotes"].values():
        q["ts"] = time.time()
    json.dump(d, open(path, "w"))
    return FileTape(path)


def fresh_candidates(path):
    rows = json.load(open(os.path.join(EX, "candidates.json")))
    for r in rows:
        r["time_stop"] = (now() + timedelta(days=3)).isoformat(timespec="seconds")
    json.dump(rows, open(path, "w"))
    return FileAdvisor(path)


class DeskE2E(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tape = fresh_tape(os.path.join(self.dir, "tape.json"))
        self.sinks = Sinks(self.dir, echo=False)

    def read(self, name):
        p = os.path.join(self.dir, name)
        return open(p).read() if os.path.exists(p) else ""

    def test_scan_is_silent_and_heartbeats(self):
        desk = Desk(drive=KnowledgeDrive(), tape=self.tape, advisor=NullAdvisor(), sinks=self.sinks, lock_inputs=GOOD_LOCKS, data_dir=self.dir)
        rep = desk.scan()
        self.assertTrue(rep.heartbeat.startswith("SCAN ["))
        self.assertIn("Drive:2026-09-21", rep.heartbeat)
        self.assertIn("locks:OK", rep.heartbeat)
        self.assertEqual(self.read("user_thread.log"), "")            # nothing to the user
        self.assertIn("silence kept", self.read("desk.log"))

    def test_unknown_locks_fail_closed_and_no_packet(self):
        desk = Desk(drive=KnowledgeDrive(), tape=self.tape, advisor=fresh_candidates(os.path.join(self.dir, "c.json")),
                    sinks=self.sinks, lock_inputs=LockInputs(), data_dir=self.dir)
        text = desk.gameplan(force=True)
        self.assertIn("PACKET: NONE", text)
        self.assertIn("lock precheck FAIL", text)
        self.assertEqual(self.read("crashforge_handoff.log"), "")

    def test_gameplan_ships_defi_packet_and_rejects_wrapper(self):
        desk = Desk(drive=KnowledgeDrive(), tape=self.tape, advisor=fresh_candidates(os.path.join(self.dir, "c.json")),
                    sinks=self.sinks, lock_inputs=GOOD_LOCKS, data_dir=self.dir)
        text = desk.gameplan(force=True)
        self.assertIn("PACKET ID: DM-", text)
        self.assertIn("RAIL: spot ETH", text)
        self.assertNotIn("RAIL: IBIT", self.read("crashforge_handoff.log"))
        self.assertIn("[READY]", self.read("user_thread.log"))
        self.assertIn("Drive latest:", text)
        self.assertIn("DM will not APPLY", self.read("crashforge_handoff.log"))
        led = self.read("ledger.jsonl")
        self.assertIn('"trigger_family": "eth-breakout-2750"', led)

    def test_wrapper_only_yields_packet_none(self):
        rows = json.load(open(os.path.join(EX, "candidates.json")))[1:]
        p = os.path.join(self.dir, "w.json"); json.dump(rows, open(p, "w"))
        desk = Desk(drive=KnowledgeDrive(), tape=self.tape, advisor=FileAdvisor(p), sinks=self.sinks, lock_inputs=GOOD_LOCKS, data_dir=self.dir)
        text = desk.gameplan(force=True)
        self.assertIn("PACKET: NONE", text)
        self.assertIn("wrapper", text)

    def test_eod_after_packet(self):
        desk = Desk(drive=KnowledgeDrive(), tape=self.tape, advisor=fresh_candidates(os.path.join(self.dir, "c.json")),
                    sinks=self.sinks, lock_inputs=GOOD_LOCKS, data_dir=self.dir)
        desk.gameplan(force=True)
        text = desk.eod(force=True)
        self.assertTrue(text.startswith("EOD ["))
        self.assertIn("PACKET: posted", text)
        self.assertIn("6:45 posted Y", text)
        self.assertIn("no P&L theater", text)
        self.assertLessEqual(len(text.splitlines()), 12)

    def test_drive_unavailable_is_problem(self):
        class Down(KnowledgeDrive):
            def __init__(self): pass
            def latest(self): 
                from dm_desk.drive import DriveUnavailable; raise DriveUnavailable("mount gone")
            def new_since(self, d): return []
            def watched_levels(self, assets=("BTC","ETH")): return []
            def latest_line(self): 
                from dm_desk.drive import DriveUnavailable; raise DriveUnavailable("mount gone")
        desk = Desk(drive=Down(), tape=self.tape, advisor=NullAdvisor(), sinks=self.sinks, lock_inputs=GOOD_LOCKS, data_dir=self.dir)
        rep = desk.scan()
        self.assertTrue(any("Drive unread" in p for p in rep.problems))
        self.assertIn("Drive:UNREAD", rep.heartbeat)
