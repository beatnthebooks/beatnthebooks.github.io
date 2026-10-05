"""Kalshi/Polymarket math in odds.py: fees, fair price from sportsbooks, best offer, line matching."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import odds as O  # noqa: E402


def am(p):
    """Contract price (0-1) -> American odds, the way the odds service reports it."""
    return round(100 * (1 - p) / p) if p < 0.5 else round(-100 * p / (1 - p))


def book(key, title, ml=None, spread=None, total=None):
    m = []
    if ml:
        m.append({"key": "h2h", "outcomes": [{"name": "Chicago Bears", "price": ml[0]},
                                             {"name": "Green Bay Packers", "price": ml[1]}]})
    if spread:
        pt, ca, ga = spread                                     # Bears point, prices
        m.append({"key": "spreads", "outcomes": [{"name": "Chicago Bears", "price": ca, "point": pt},
                                                 {"name": "Green Bay Packers", "price": ga, "point": -pt}]})
    if total:
        pt, ov, un = total
        m.append({"key": "totals", "outcomes": [{"name": "Over", "price": ov, "point": pt},
                                                {"name": "Under", "price": un, "point": pt}]})
    return {"key": key, "title": title, "last_update": "2026-10-04T20:00:00Z", "markets": m}


EVENT = {"home_team": "Green Bay Packers", "away_team": "Chicago Bears",
         "commence_time": "2026-10-11T17:00:00Z", "bookmakers": [
             book("draftkings", "DraftKings", (150, -175), (3.5, -110, -110), (44.5, -110, -110)),
             book("fanduel", "FanDuel", (155, -180), (3.5, -108, -112), (44.5, -112, -108)),
             book("pinnacle", "Pinnacle", (152, -170), (3.0, -105, -105), (44.5, -108, -102)),
             book("polymarket", "Polymarket", (am(0.37), am(0.64)), (3.5, am(0.49), am(0.52)), (45.5, am(0.50), am(0.52))),
             book("kalshi", "Kalshi", (am(0.39), am(0.62)), None, (44.5, am(0.51), am(0.48))),
         ]}


class Fees(unittest.TestCase):
    def test_polymarket_sports_fee(self):
        o = O._offer({"key": "polymarket", "title": "Polymarket"}, am(0.40))
        self.assertAlmostEqual(o["cents"], 40.0, places=0)
        self.assertAlmostEqual(o["fee"], 0.05 * 0.4 * 0.6 * 100, places=1)   # 1.2 cents
        self.assertAlmostEqual(o["dec"], 1 / (0.4 + 0.012), places=2)

    def test_kalshi_and_unknown_books(self):
        k = O._offer({"key": "kalshi", "title": "Kalshi"}, am(0.5))
        self.assertAlmostEqual(k["fee"], 0.07 * 0.25 * 100, places=1)          # 1.75 cents at 50c
        d = O._offer({"key": "draftkings", "title": "DK"}, -110)
        self.assertEqual(d["fee"], 0.0)

    def test_fee_is_largest_at_50c(self):
        fees = [O._offer({"key": "polymarket", "title": "P"}, am(p))["fee"] for p in (0.1, 0.3, 0.5, 0.7, 0.9)]
        self.assertEqual(max(fees), fees[2])


class Summarize(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(O, "setting", lambda name, default="": default)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.s = O.summarize(EVENT)

    def test_counts(self):
        self.assertEqual(self.s["books"], 3)      # sportsbooks set the fair price
        self.assertEqual(self.s["mine"], 2)       # exchanges are where the bets go

    def test_fair_price_ignores_exchanges(self):
        fairs = [O._fair2(-175, 150), O._fair2(-180, 155), O._fair2(-170, 152)]
        self.assertAlmostEqual(self.s["fair"]["home"], sorted(fairs)[1], places=4)

    def test_most_common_line_is_the_fair_line(self):
        self.assertEqual(self.s["fair"]["spreadPoint"], -3.5)   # 2 books hang GB -3.5, 1 hangs -3
        self.assertEqual(self.s["fair"]["totalPoint"], 44.5)

    def test_best_offer_and_ev(self):
        away = self.s["ml"]["away"]
        self.assertEqual(away["book"], "Polymarket")             # 37c beats Kalshi's 39c
        want = (1 - self.s["fair"]["home"]) / (0.37 + 0.05 * 0.37 * 0.63) - 1
        self.assertAlmostEqual(away["ev"], want * 100, delta=0.2)   # 37c arrives as +170 = 37.04c

    def test_other_line_has_no_ev(self):
        self.assertIsNone(O._fair_prob(self.s["fair"], "total", "under", 45.5))
        self.assertIsNotNone(O._fair_prob(self.s["fair"], "total", "under", 44.5))
        self.assertEqual(self.s["total"]["under"]["point"], 44.5)  # same-line Kalshi offer preferred

    def test_spread_sides_mirror(self):
        f = self.s["fair"]
        self.assertAlmostEqual(O._fair_prob(f, "spread", "home", -3.5) + O._fair_prob(f, "spread", "away", 3.5), 1.0)


class Matching(unittest.TestCase):
    def test_skips_games_already_started_and_matches_by_date(self):
        games = [{"gid": "g1", "home": "GB", "away": "CHI", "date": "2026-10-11", "hs": None},
                 {"gid": "g0", "home": "GB", "away": "CHI", "date": "2026-09-01", "hs": None}]
        names = {"GB": "Packers", "CHI": "Bears"}
        live = dict(EVENT, commence_time="2026-10-04T17:00:00Z")
        odds = {"fetched": datetime(2026, 10, 5, tzinfo=timezone.utc).isoformat(), "events": [EVENT, live]}
        with mock.patch.object(O, "setting", lambda name, default="": default):
            out = O.match_games(odds, games, names)
        self.assertEqual(list(out), ["g1"])


if __name__ == "__main__":
    unittest.main()
