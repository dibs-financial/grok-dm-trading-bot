import unittest
from datetime import timedelta
from dm_desk.gate import qualify
from tests.helpers import good_packet, now


class GateTests(unittest.TestCase):
    def test_good_packet_passes(self):
        g = qualify(good_packet(), now=now(), scan_start=now() - timedelta(hours=4))
        self.assertTrue(g.passed, g.failures)

    def test_wrapper_rail_fails(self):
        g = qualify(good_packet(rail="IBIT", asset="IBIT", venue="broker"))
        self.assertFalse(g.passed); self.assertTrue(any(f.startswith("1 ") for f in g.failures))

    def test_low_rr_fails(self):
        g = qualify(good_packet(rr=1.5))
        self.assertTrue(any(f.startswith("6 ") for f in g.failures))

    def test_overstated_rr_fails(self):
        g = qualify(good_packet(rr=5.0))   # geometric is 2.5
        self.assertTrue(any("exceeds geometric" in f for f in g.failures))

    def test_unproven_history_is_silent(self):
        p = good_packet(); p.history.n = 2
        g = qualify(p); self.assertTrue(any("UNPROVEN" in f for f in g.failures))

    def test_lock_fail_never_ships_apply(self):
        p = good_packet(); p.lock_check["CII0.08"] = "FAIL"
        g = qualify(p)
        self.assertFalse(g.passed); self.assertEqual(p.intent, "DO NOT APPLY")

    def test_defi_unknown_fails_closed(self):
        p = good_packet(); p.defi.paused_or_upgrading = None
        g = qualify(p); self.assertTrue(any("UNPROVEN" in f and f.startswith("13") for f in g.failures))

    def test_slippage_and_gas_limits(self):
        p = good_packet(); p.defi.slippage_edge_fraction = 0.3
        self.assertTrue(any("slippage" in f for f in qualify(p).failures))
        p = good_packet(); p.defi.gas_mev_net_fraction = 0.2
        self.assertTrue(any("gas+MEV" in f for f in qualify(p).failures))

    def test_gtc_zone_second_entry_rejected(self):
        p = good_packet(rail="spot BTC", asset="BTC", entry=77716.0, target=82000.0, invalidation=75500.0, rr=2.0)
        self.assertTrue(any(f.startswith("10 ") for f in qualify(p).failures))

    def test_invalidation_inside_noise_fails(self):
        p = good_packet(invalidation=2690.0, target=2730.0, rr=3.0)
        self.assertTrue(any(f.startswith("4 ") for f in qualify(p).failures))

    def test_time_stop_required_and_future(self):
        p = good_packet(time_stop=(now() - timedelta(hours=1)).isoformat())
        self.assertTrue(any(f.startswith("5 ") for f in qualify(p).failures))

    def test_copy_fails_novelty(self):
        p = good_packet(novelty_reason="same rail + asset + trigger family with only wording changed")
        self.assertTrue(any(f.startswith("12 ") for f in qualify(p).failures))

    def test_touching_hold_book_fails(self):
        p = good_packet(advisory_risk="consider: sell IBIT to fund")
        self.assertTrue(any(f.startswith("11 ") for f in qualify(p).failures))

    def test_missing_field_short_circuits(self):
        p = good_packet(trigger="")
        g = qualify(p); self.assertEqual(len(g.failures), 1); self.assertIn("missing required field", g.failures[0])

    def test_near_miss_flag(self):
        p = good_packet(rr=1.9)
        self.assertTrue(qualify(p).near_miss)
