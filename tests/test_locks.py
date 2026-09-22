import unittest
from dm_desk.locks import LockInputs, check


class LockTests(unittest.TestCase):
    def test_all_pass(self):
        r = check(LockInputs(vix=15, cii=0.2, spy_5d_return=0.01, arm_live_would_add=False, lag_seconds=3, front_run_suspected=False))
        self.assertEqual(r.status, "OK"); self.assertFalse(r.any_fail)

    def test_unknown_fails_closed(self):
        r = check(LockInputs())
        self.assertTrue(r.any_fail)
        self.assertEqual(r.results["VIX22"], "FAIL")

    def test_warn_thresholds(self):
        r = check(LockInputs(vix=20.5, cii=0.09, spy_5d_return=-0.035, arm_live_would_add=False, lag_seconds=16, front_run_suspected=False))
        self.assertEqual(r.status, "WARN")
        self.assertEqual(set(r.results.values()), {"WARN", "PASS"})

    def test_lock_breaches(self):
        r = check(LockInputs(vix=22, cii=0.08, spy_5d_return=-0.04, arm_live_would_add=True, lag_seconds=21, front_run_suspected=True))
        self.assertTrue(all(v == "FAIL" for v in r.results.values()))
