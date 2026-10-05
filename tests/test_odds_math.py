"""Odds math: conversions, de-vig, edge, EV and Kelly (rift_edge.py and the copies elsewhere)."""

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import edge_lab  # noqa: E402
import rift_edge as E  # noqa: E402
import rift_real  # noqa: E402


class Conversions(unittest.TestCase):
    def test_american_to_decimal(self):
        self.assertAlmostEqual(E.american_to_decimal(-140), 1 + 100 / 140)
        self.assertAlmostEqual(E.american_to_decimal(120), 2.2)
        self.assertAlmostEqual(E.american_to_decimal(100), 2.0)
        self.assertAlmostEqual(E.american_to_decimal(-100), 2.0)

    def test_round_trip(self):
        for a in (-500, -200, -110, 100, 150, 400):
            self.assertEqual(E.decimal_to_american(E.american_to_decimal(a)), a)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            E.american_to_decimal(0)
        with self.assertRaises(ValueError):
            E.implied_prob(1.0)

    def test_every_copy_agrees(self):
        """rift_real and edge_lab keep their own copies of the conversion and de-vig."""
        for a in (-450, -175, -110, -102, 102, 135, 300):
            self.assertAlmostEqual(rift_real.am_to_dec(a), E.american_to_decimal(a))
        for h, a in ((-150, 130), (-110, -110), (-400, 320)):
            want = E.remove_vig([E.american_implied(h), E.american_implied(a)])[0]
            self.assertAlmostEqual(edge_lab.devig(h, a), want)


class Devig(unittest.TestCase):
    def test_even_market(self):
        q = 1 / 1.91
        self.assertEqual(E.remove_vig([q, q]), [0.5, 0.5])

    def test_every_method_sums_to_one(self):
        rng = random.Random(7)
        for _ in range(200):
            a, b = rng.uniform(1.05, 9.0), rng.uniform(1.05, 9.0)
            raw = [1 / a, 1 / b]
            if sum(raw) <= 1:
                continue
            for m in ("multiplicative", "additive", "power"):
                self.assertAlmostEqual(sum(E.remove_vig(raw, m)), 1.0, places=6, msg=m)

    def test_power_shades_the_longshot(self):
        raw = [E.american_implied(-300), E.american_implied(250)]
        mult, power = E.remove_vig(raw), E.remove_vig(raw, "power")
        self.assertGreater(power[0], mult[0])      # favourite gets more
        self.assertLess(power[1], mult[1])         # longshot gets less

    def test_margin(self):
        self.assertAlmostEqual(E.book_margin_pct([0.55, 0.5]), 5.0)


class EdgeEvKelly(unittest.TestCase):
    def test_hand_calculated(self):
        r = E.find_edge(0.55, 2.0, 2.0)
        self.assertAlmostEqual(r.market_fair_prob, 0.5)
        self.assertAlmostEqual(r.edge_pp, 5.0)
        self.assertEqual(r.tier, "MEDIUM")
        self.assertAlmostEqual(r.ev_pct, 10.0)        # 0.55 * 2 - 1
        self.assertAlmostEqual(r.kelly_pct, 10.0)     # (0.55 * 1 - 0.45) / 1

    def test_ev_uses_posted_price_not_fair(self):
        r = E.find_edge(0.5, 1.91, 1.91)
        self.assertAlmostEqual(r.edge_pp, 0.0)
        self.assertAlmostEqual(r.ev_pct, (0.5 * 1.91 - 1) * 100)
        self.assertEqual(r.kelly_pct, 0.0)            # -EV never sizes a bet

    def test_tiers(self):
        for pp, tier in ((4.99, "LOW"), (5, "MEDIUM"), (9.99, "MEDIUM"), (10, "HIGH"), (-12, "HIGH")):
            self.assertEqual(E.classify_edge(pp), tier)

    def test_analyze_game_sides_are_consistent(self):
        h, a = E.analyze_game(-150, 130, 0.62)
        self.assertAlmostEqual(h.market_fair_prob + a.market_fair_prob, 1.0)
        self.assertAlmostEqual(h.model_prob + a.model_prob, 1.0)

    def test_model_prob_bounds(self):
        with self.assertRaises(ValueError):
            E.find_edge(1.0, 2.0, 2.0)


if __name__ == "__main__":
    unittest.main()
