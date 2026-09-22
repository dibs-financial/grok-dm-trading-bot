import tempfile, unittest
from dm_desk.engine.links import build
from dm_desk.engine.patterns import mine
from dm_desk.engine.scanner import Scanner


class LinkTests(unittest.TestCase):
    def test_ranking_and_links(self):
        nodes = build()
        self.assertEqual(len(nodes), 27)
        first = next(n for n in nodes if n.date == "2026-05-11" and n.kind == "memo")
        self.assertEqual(first.novelty, 1.0)                 # nothing earlier to resemble
        for n in nodes:
            self.assertEqual(len(n.links), 3)
            self.assertTrue(0 <= n.priority <= 1)
            self.assertNotIn(n.cite, [c for c, _ in n.links])
        self.assertEqual([n.aliases for n in nodes].count([]), 27)   # no byte-near duplicates in corpus text

    def test_level_aliases_collapse(self):
        atlas = mine(Scanner(data_dir=tempfile.mkdtemp()).scan()["store"])
        lp = next(l for l in atlas.levels if l.id == "level:BTC:65600")
        self.assertIsInstance(lp.aliases, list)
        merged = [l for l in atlas.levels if l.aliases]
        self.assertTrue(all(abs(a - l.level) / l.level <= 0.004 for l in merged for a in l.aliases))
