import unittest
from dm_desk import config as C
from dm_desk.packet import Packet
from tests.helpers import good_packet


class PacketTests(unittest.TestCase):
    def test_complete_packet_has_no_missing_fields(self):
        self.assertEqual(good_packet().missing_fields(), [])

    def test_missing_field_is_not_a_packet(self):
        p = good_packet(time_stop="")
        self.assertIn("TIME STOP / EXPIRY", p.missing_fields())
        p = good_packet(); p.lock_check.pop("VIX22")
        self.assertIn("LOCK CHECK", p.missing_fields())

    def test_lock_fail_forces_do_not_apply(self):
        p = good_packet(); p.lock_check["VIX22"] = "FAIL"; p.enforce_intent()
        self.assertEqual(p.intent, "DO NOT APPLY")

    def test_doubles_beta_forces_watch_only(self):
        p = good_packet(correlation="doubles existing beta"); p.enforce_intent()
        self.assertEqual(p.intent, "WATCH ONLY")

    def test_wrapper_detection(self):
        self.assertTrue(good_packet(rail="IBIT via broker").is_wrapper())
        self.assertTrue(good_packet(asset="ETHA").is_wrapper())
        self.assertFalse(good_packet().is_wrapper())

    def test_render_has_every_required_line(self):
        text = good_packet().render()
        for line in ("PACKET ID:", "INTENT:", "RAIL:", "ASSET / VENUE:", "SIDE:", "ENTRY:", "TRIGGER:", "INVALIDATION:",
                     "TIME STOP / EXPIRY:", "TARGET / R:R:", "SIZE HINT:", "LOCK CHECK:", "DEFI CHECK:", "CORRELATION:",
                     "HISTORY:", "LIVE CHECK:", "NOVELTY:", "ADVISORY RISK:", "CRASHFORGE MUST NOT:", "USER ACTION:", "Drive latest:"):
            self.assertIn(line, text)
        self.assertIn(f"${C.BTC_GTC:,.0f}", text)
        self.assertIn("DM will not APPLY", text)

    def test_roundtrip(self):
        p = good_packet()
        q = Packet.from_dict(p.to_dict())
        self.assertEqual(q.render(), p.render())
