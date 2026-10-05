"""Realistic pick edges (weekly.py): the edge math, which seasons each record may use (no current-season
results, no model-training seasons for leans), and which price a wind under is quoted at. No network."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import weekly as W  # noqa: E402


def game(season, hs, as_, wind=15.0, roof="outdoors", tot=44.5, hml=-120.0, aml=100.0):
    return {"season": season, "hs": hs, "as": as_, "wind": wind, "roof": roof, "tot": tot,
            "oo": -110.0, "uo": -110.0, "hml": hml, "aml": aml}


class EdgeMath(unittest.TestCase):
    def test_fair_price_no_shift_is_zero_edge(self):
        self.assertEqual(W.real_edge(0.5, 0.0, 2.0), 0.0)

    def test_positive_record_raises_edge(self):
        self.assertGreater(W.real_edge(0.5, 0.2, 1.909), W.real_edge(0.5, 0.0, 1.909))


class WindShift(unittest.TestCase):
    def test_uses_only_past_windy_outdoor_games(self):
        past = [game(2020, 10, 10)] * 30 + [game(2020, 30, 30)] * 10        # unders 3 of 4
        noise = ([game(2026, 30, 30)] * 50                                  # this season: no peeking
                 + [game(2020, 30, 30, wind=5.0)] * 50                       # calm games don't count
                 + [game(2020, 30, 30, roof="dome")] * 50)                   # indoor games don't count
        a = W.fit_wind_shift(past, 2026)
        b = W.fit_wind_shift(past + noise, 2026)
        self.assertGreater(a["shift"], 0)
        self.assertAlmostEqual(a["shift"], b["shift"])
        self.assertEqual(b["n"], 40)


class LeanShift(unittest.TestCase):
    def test_skips_training_seasons_and_this_season(self):
        def rec(season, home_won):
            return {"g": game(season, 24 if home_won else 10, 10 if home_won else 24), "p": 0.9}  # lean = home
        recs = [rec(2018, True)] * 20 + [rec(2018, False)] * 20
        base = W.fit_lean_shift(recs, 0.3, 2026)
        more = W.fit_lean_shift(recs + [rec(2010, True)] * 80 + [rec(2026, True)] * 80, 0.3, 2026)
        self.assertAlmostEqual(base["shift"], more["shift"])
        self.assertEqual(more["n"], 40)


class WindPickPrice(unittest.TestCase):
    g = {"tot": 44.5, "oo": -110.0, "uo": -110.0}

    def test_exchange_price_when_its_line_matches(self):
        s = {"fair": {"over": 0.5, "totalPoint": 44.5},
             "total": {"under": {"point": 44.5, "dec": 1.95, "cents": 50.0, "book": "Kalshi"}}}
        wp = W.wind_pick(self.g, s, 0.2)
        self.assertEqual((wp["book"], wp["point"]), ("Kalshi", 44.5))
        self.assertEqual(wp["edge"], W.real_edge(0.5, 0.2, 1.95))

    def test_sportsbook_odds_when_exchange_line_differs(self):
        s = {"fair": {"over": 0.5, "totalPoint": 44.5},
             "total": {"under": {"point": 43.5, "dec": 2.0, "cents": 49.0, "book": "Kalshi"}}}
        wp = W.wind_pick(self.g, s, 0.2)
        self.assertEqual((wp.get("odds"), wp["point"]), (-110, 44.5))


if __name__ == "__main__":
    unittest.main()
