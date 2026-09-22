import json, os, tempfile, time, unittest
from datetime import date

from dm_desk.engine.guard import UniquenessGuard, fingerprint, jaccard
from dm_desk.engine.patterns import mine
from dm_desk.engine.qubo import SimulatedAnnealer, build_qubo, energy
from dm_desk.engine.scanner import Scanner, Store
from dm_desk.engine.solver import EngineAdvisor, generate, select
from dm_desk.ledger import Ledger
from tests.helpers import good_packet

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class QuboTests(unittest.TestCase):
    def test_one_slot_and_best_pick(self):
        Q = build_qubo(utility=[0.2, 0.9, 0.5], novelty=[1.0, 1.0, 1.0], conflicts=[])
        best = SimulatedAnnealer(seed=1).solve(Q, k=1)[0]
        self.assertEqual(best[1], [0, 1, 0])
        self.assertLess(energy(Q, [0, 1, 0]), energy(Q, [1, 1, 0]))

    def test_novelty_bonus_flips_choice(self):
        Q = build_qubo(utility=[0.9, 0.6], novelty=[0.0, 1.0], conflicts=[], lam_novelty=1.0)
        self.assertEqual(SimulatedAnnealer(seed=2).solve(Q, k=1)[0][1], [0, 1])

    def test_conflict_penalty(self):
        Q = build_qubo(utility=[0.9, 0.9], novelty=[1, 1], conflicts=[(0, 1)], one_slot_penalty=0.0)
        self.assertLess(energy(Q, [1, 0]), energy(Q, [1, 1]))


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(os.path.join(tempfile.mkdtemp(), "ledger.jsonl")); self.led._write()

    def test_fingerprint_is_stable_and_bucketed(self):
        a, b = good_packet(), good_packet(entry=2705.0)      # same 1% bucket
        self.assertEqual(fingerprint(a, ["x"]), fingerprint(b, ["x"]))
        self.assertNotEqual(fingerprint(a, ["x"]), fingerprint(good_packet(entry=2900.0), ["x"]))

    def test_exact_and_daily_rejections(self):
        g = UniquenessGuard(self.led)
        p = good_packet()
        v = g.check(p, ["level:ETH:2700"], date(2026, 9, 23), live_level_new=True)
        self.assertTrue(v.accepted)
        self.led.add(p, "2026-09-21", fingerprint=v.fingerprint, body_hash=v.body_hash, pattern_ids=["level:ETH:2700"])
        v2 = g.check(good_packet(packet_id="DM-20260923-01"), ["level:ETH:2700"], date(2026, 9, 23))
        self.assertFalse(v2.accepted); self.assertIn("fingerprint", v2.reason)
        v3 = g.check(good_packet(packet_id="DM-20260922-02", entry=2900.0, trigger_family="other"), ["y"], date(2026, 9, 22))
        self.assertFalse(v3.accepted); self.assertIn("per day", v3.reason)

    def test_jaccard(self):
        self.assertGreater(jaccard("if ETH close > 2750 funding low", "if ETH close > 2750 funding low now"), 0.8)
        self.assertLess(jaccard("BTC support 60000", "ETH resistance 2950 flows"), 0.3)


class ScannerPatternTests(unittest.TestCase):
    def test_scan_is_idempotent(self):
        d = tempfile.mkdtemp()
        sc = Scanner(data_dir=d)
        first = sc.scan(); second = sc.scan()
        self.assertTrue(first["changed"]); self.assertFalse(second["changed"])
        self.assertGreater(len(first["store"].triples), 100)

    def test_atlas_from_real_kb(self):
        atlas = mine(Scanner(data_dir=tempfile.mkdtemp()).scan()["store"])
        ids = {l.id: l for l in atlas.levels}
        self.assertIn("level:BTC:60000", ids)
        self.assertGreaterEqual(ids["level:BTC:60000"].recurrence, 5)
        self.assertEqual(atlas.last_price["BTC"], 86200)
        self.assertGreater(len(atlas.catalyst_outcomes), 5)
        self.assertIsNotNone(atlas.extreme_fear_forward["avg_next2"])

    def test_generate_respects_rr_and_distance(self):
        atlas = mine(Scanner(data_dir=tempfile.mkdtemp()).scan()["store"])
        for c in generate(atlas):
            self.assertGreaterEqual(c.rr, 2.0)
            self.assertLessEqual(abs(c.entry - atlas.last_price[c.asset]) / atlas.last_price[c.asset], 0.10)
            self.assertEqual(c.side, "LONG")     # spot rails are long-only without a Drive-named perp rail


class EngineAdvisorTests(unittest.TestCase):
    def test_engine_proposes_and_desk_gate_decides(self):
        from dm_desk.desk import Desk, Sinks
        from dm_desk.drive import KnowledgeDrive
        from dm_desk.locks import LockInputs
        from dm_desk.tape import FileTape
        d = tempfile.mkdtemp()
        tape = json.load(open(os.path.join(REPO, "examples", "tape.json")))
        for q in tape["quotes"].values(): q["ts"] = time.time()
        tp = os.path.join(d, "tape.json"); json.dump(tape, open(tp, "w"))
        led = Ledger(os.path.join(d, "ledger.jsonl")); led._write()
        adv = EngineAdvisor(led, data_dir=os.path.join(d, "engine"), venues_path=os.path.join(REPO, "examples", "venues.json"))
        desk = Desk(drive=KnowledgeDrive(), tape=FileTape(tp), advisor=adv, sinks=Sinks(d, echo=False), ledger=led,
                    lock_inputs=LockInputs(vix=16, cii=0.2, spy_5d_return=0.01, arm_live_would_add=False, front_run_suspected=False), data_dir=d)
        text = desk.gameplan(force=True)
        self.assertTrue("PACKET: NONE" in text or "strategy_id: DM-" in text)
        self.assertGreaterEqual(adv.last_report["candidates"], 1)
        if "strategy_id" in text:
            self.assertIn("fingerprint:", text)
            self.assertNotIn("INTENT: APPLY", text.split("packet:")[1].split("steps:")[0]) if "doubles existing beta" in text else None
            self.assertEqual(len(Ledger(os.path.join(d, "ledger.jsonl")).entries), 1)
        # second run the same day: guard's one-per-day rule (if shipped) or still NONE — never a second ledger row
        desk.gameplan(force=True)
        self.assertLessEqual(len(Ledger(os.path.join(d, "ledger.jsonl")).entries), 1)
