import os, tempfile, unittest
from dm_desk import config as C
from dm_desk.eod import EodInput, render
from dm_desk.history import count_analogs
from dm_desk.ledger import Ledger
from tests.helpers import candles, good_packet


class HistoryTests(unittest.TestCase):
    def test_counts_hits_and_invalidations(self):
        # touch 100 three times: first -> 120 (hit), second -> 90 (invalidated), third -> unresolved
        prices = [100, 110, 120, 105, 100, 95, 90, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 200]
        res = count_analogs(candles(prices), entry=100, target=120, invalidation=90, side="LONG", min_gap=2, horizon=6)
        self.assertEqual(res.n, 3)
        self.assertEqual(res.hit_before_invalidate, 1)
        self.assertEqual(res.invalidated_first, 1)
        self.assertEqual(res.unresolved, 1)

    def test_excludes_live_bar(self):
        res = count_analogs(candles([50, 60, 100]), entry=100, target=120, invalidation=90)
        self.assertEqual(res.n, 0)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ledger.jsonl")

    def test_missing_ledger_cannot_claim_novelty(self):
        led = Ledger(self.path)
        self.assertFalse(led.present)
        v = led.novelty(good_packet(), live_level_new=True, regime_changed=False, drive_evidence_newer=False, prior_miss_changes_plan=False)
        self.assertIn("missing", v.nearest_id)

    def test_copy_vs_variant(self):
        led = Ledger(self.path)
        p = good_packet(); led.add(p, "2026-09-21")
        q = good_packet(packet_id="DM-20260923-01")
        v = led.novelty(q, live_level_new=False, regime_changed=False, drive_evidence_newer=False, prior_miss_changes_plan=False)
        self.assertTrue(v.is_copy); self.assertEqual(v.nearest_id, "DM-20260922-01")
        v = led.novelty(q, live_level_new=True, regime_changed=False, drive_evidence_newer=False, prior_miss_changes_plan=False)
        self.assertFalse(v.is_copy); self.assertIn("live level", v.line)

    def test_ids_and_outcomes(self):
        led = Ledger(self.path)
        import datetime
        self.assertEqual(led.next_id(datetime.date(2026, 9, 22)), "DM-20260922-01")
        led.add(good_packet(), "2026-09-21")
        self.assertEqual(led.next_id(datetime.date(2026, 9, 22)), "DM-20260922-02")
        led.update("DM-20260922-01", status="applied-by-user", outcome_eod="HIT")
        self.assertEqual(Ledger(self.path).get("DM-20260922-01").outcome_eod, "HIT")
        with self.assertRaises(ValueError):
            led.update("DM-20260922-01", outcome_eod="WIN")


class EodTests(unittest.TestCase):
    def test_cap_and_no_pnl_theater(self):
        t = render(EodInput(date="2026-09-22", gameplan_posted=True, scans_done=6, scans_expected=6, silence_kept=True,
                            packet="posted", tape_vs_plan="HIT", lesson="Level was fine. Sizing was not; keep 10%.", seed="watch 82,400",
                            p2_outcome="HIT", applied=False))
        self.assertLessEqual(len(t.splitlines()), C.EOD_MAX_LINES)
        self.assertIn("no P&L theater", t)
        self.assertIn("LESSON: Level was fine.", t)
        self.assertNotIn("Sizing was not", t)   # one sentence only
