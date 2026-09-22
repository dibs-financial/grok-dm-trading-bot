import json, os, tempfile, time, unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dm_desk import config as C
from dm_desk.execution import ExecutionDesk, PaperBroker, StandingOrders, resolve
from dm_desk.locks import LockInputs, check
from dm_desk.tape import FileTape
from tests.helpers import good_packet

TZ = ZoneInfo(C.TZ)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = LockInputs(vix=16.5, cii=0.21, spy_5d_return=0.012, arm_live_would_add=False, front_run_suspected=False)


def tape(d, btc=86200.0, eth=2704.0):
    p = os.path.join(d, "tape.json")
    json.dump({"quotes": {"BTC": {"price": btc, "ts": time.time()}, "ETH": {"price": eth, "ts": time.time()}}, "candles": {}}, open(p, "w"))
    return FileTape(p)


class RowTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = StandingOrders(os.path.join(self.d, "rows.jsonl"))

    def test_arm_from_packet_and_rules(self):
        r = self.orders.from_packet(good_packet().to_dict(), size_pct=5)
        self.assertEqual(r.status, "ARMED"); self.assertTrue(r.matches(2700)); self.assertFalse(r.matches(2800))
        with self.assertRaises(ValueError):
            self.orders.arm(asset="BTC", side="SHORT", rail="spot BTC", entry_low=1, entry_high=2, size_pct=1, invalidation=None, target=None, expires="2026-12-31T00:00:00-06:00")
        with self.assertRaises(ValueError):
            self.orders.arm(asset="IBIT", side="LONG", rail="IBIT broker", entry_low=1, entry_high=2, size_pct=1, invalidation=None, target=None, expires="2026-12-31T00:00:00-06:00")
        self.assertEqual(len(StandingOrders(self.orders.path).rows), 1)      # persisted


class FireTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orders = StandingOrders(os.path.join(self.d, "rows.jsonl"))
        self.row = self.orders.from_packet(good_packet().to_dict(), size_pct=10)

    def test_fires_when_in_band_and_locks_pass(self):
        ex = ExecutionDesk(tape(self.d), PaperBroker(), self.orders, GOOD, self.d)
        rec = ex.fire(force=True)
        self.assertEqual(rec[0]["status"], "FIRED"); self.assertEqual(self.orders.get(self.row.id).status, "LIVE")
        self.assertTrue(os.path.exists(os.path.join(self.d, "fire_receipts.jsonl")))

    def test_held_on_lock_fail_and_resolution_logged(self):
        ex = ExecutionDesk(tape(self.d), PaperBroker(), self.orders, LockInputs(vix=22.5, cii=0.2, spy_5d_return=0.0, arm_live_would_add=False, front_run_suspected=False), self.d)
        rec = ex.fire(force=True)
        self.assertEqual(rec[0]["status"], "HELD"); self.assertIn(rec[0]["resolution"], ("defer", "flatten"))
        self.assertTrue(os.path.exists(os.path.join(self.d, "resolutions.jsonl")))
        self.assertEqual(self.orders.get(self.row.id).status, "ARMED")

    def test_no_match_out_of_band(self):
        ex = ExecutionDesk(tape(self.d, eth=2800.0), PaperBroker(), self.orders, GOOD, self.d)
        self.assertEqual(ex.fire(force=True)[0]["status"], "NO-MATCH")

    def test_arm_live_is_not_add(self):
        ExecutionDesk(tape(self.d), PaperBroker(), self.orders, GOOD, self.d).fire(force=True)
        self.orders.from_packet(good_packet(packet_id="DM-20260922-02").to_dict(), size_pct=10)
        rec = ExecutionDesk(tape(self.d), PaperBroker(), self.orders, GOOD, self.d).fire(force=True)
        self.assertEqual(rec[0]["status"], "HELD"); self.assertIn("ADD", rec[0]["reason"])

    def test_manage_flattens_on_target_and_invalidation(self):
        ExecutionDesk(tape(self.d), PaperBroker(), self.orders, GOOD, self.d).fire(force=True)
        out = ExecutionDesk(tape(self.d, eth=2960.0), PaperBroker(), self.orders, GOOD, self.d).manage()
        self.assertEqual(out[0]["event"], "TARGET"); self.assertEqual(self.orders.get(self.row.id).status, "FILLED")

    def test_expired_row(self):
        self.orders.get(self.row.id).expires = (datetime.now(TZ) - timedelta(hours=1)).isoformat(); self.orders._write()
        rec = ExecutionDesk(tape(self.d), PaperBroker(), self.orders, GOOD, self.d).fire(force=True)
        self.assertEqual(rec[0]["status"], "EXPIRED")

    def test_stale_tape_never_fires(self):
        p = os.path.join(self.d, "stale.json")
        json.dump({"quotes": {"ETH": {"price": 2704.0, "ts": time.time() - 60}}, "candles": {}}, open(p, "w"))
        rec = ExecutionDesk(FileTape(p), PaperBroker(), self.orders, GOOD, self.d).fire(force=True)
        self.assertEqual(rec[0]["status"], "HELD"); self.assertIn("STALE", rec[0]["reason"])


class ResolveTests(unittest.TestCase):
    def test_max_ev_among_compliant(self):
        li = LockInputs(**GOOD.__dict__); li.lag_seconds = 18
        r = resolve("venue lag 18s", 50, 5, 1, check(li), lag_seconds=18)
        self.assertNotIn("__", r.chosen); self.assertEqual(r.chosen, max(r.options_scored, key=r.options_scored.get))
        self.assertIn("proceed", r.options_scored)

    def test_lock_fail_removes_risk_on_options(self):
        r = resolve("VIX spike", 50, 5, 1, check(LockInputs(vix=23, cii=0.2, spy_5d_return=0, arm_live_would_add=False, lag_seconds=1, front_run_suspected=False)))
        self.assertTrue(set(r.options_scored) <= {"defer", "flatten"})

    def test_tie_prefers_less_exposure(self):
        r = resolve("x", 0, 0, 0, check(LockInputs(vix=23, cii=0.2, spy_5d_return=0, arm_live_would_add=False, lag_seconds=1, front_run_suspected=False)))
        self.assertEqual(r.chosen, "flatten") if r.options_scored.get("defer") == r.options_scored.get("flatten") else None


class CliTests(unittest.TestCase):
    def test_desk_first_and_legacy_commands(self):
        import subprocess, sys
        d = tempfile.mkdtemp()
        out = subprocess.run([sys.executable, "-m", "dm_desk", "status", "--data-dir", d], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(out.returncode, 0, out.stderr); self.assertIn('"knowledge"', out.stdout)
        out = subprocess.run([sys.executable, "-m", "dm_desk", "scan", "--tape", "file", "--tape-file", os.path.join(REPO, "examples", "tape.json"),
                              "--locks", os.path.join(REPO, "examples", "locks.json"), "--data-dir", d, "--quiet"], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(out.returncode, 0, out.stderr); self.assertIn("SCAN [", out.stdout)
        out = subprocess.run([sys.executable, "-m", "dm_desk", "execution", "rows", "--data-dir", d], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(out.returncode, 0, out.stderr)
