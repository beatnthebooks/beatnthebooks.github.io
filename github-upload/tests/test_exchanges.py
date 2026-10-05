"""Kalshi/Polymarket feed helpers and the line-move model: parsing, kickoff times, prices at a
moment, and no look-ahead. No network."""

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import exchanges as X  # noqa: E402
import line_move as LM  # noqa: E402

FEES = {"kalshi": 0.07, "polymarket": 0.05}


def g(day, time="13:00", home="GB", away="CHI", **kw):
    return dict({"date": day, "time": time, "home": home, "away": away, "hs": None, "as": None,
                 "season": 2026, "spread": None, "gid": f"{day}_{away}_{home}"}, **kw)


class Parsing(unittest.TestCase):
    def test_kalshi_ticker(self):
        self.assertEqual(X.kalshi_game("KXNFLGAME-25DEC04DALDET"), (date(2025, 12, 4), "DALDET"))

    def test_team_aliases(self):
        names = {"JAX": "Jaguars", "LA": "Rams", "WAS": "Commanders", "DET": "Lions"}
        self.assertEqual(X.kx_team("JAC", names), "JAX")
        self.assertEqual(X.kx_team("LAR", names), "LA")
        self.assertEqual(X.kx_team("DET", names), "DET")
        self.assertIsNone(X.kx_team("XYZ", names))

    def test_kickoff_utc_handles_daylight_saving(self):
        # 1:00 PM Eastern = 17:00 UTC in October (EDT), 18:00 UTC in December (EST)
        oct_ = datetime.fromtimestamp(X.kickoff_utc(g("2026-10-11")), timezone.utc)
        dec_ = datetime.fromtimestamp(X.kickoff_utc(g("2026-12-13")), timezone.utc)
        self.assertEqual((oct_.hour, dec_.hour), (17, 18))
        # DST ends Sun Nov 1, 2026
        self.assertEqual(datetime.fromtimestamp(X.kickoff_utc(g("2026-11-01")), timezone.utc).hour, 18)

    def test_match_game_needs_both_teams_and_close_date(self):
        games = [g("2026-10-11"), g("2026-12-20", home="CHI", away="GB")]
        by = {}
        for x in games:
            by.setdefault(frozenset((x["home"], x["away"])), []).append(x)
        ko = X.kickoff_utc(games[0])
        self.assertIs(X.match_game(by, "CHI", "GB", ko + 3600), games[0])
        self.assertIsNone(X.match_game(by, "CHI", "GB", ko + 10 * 86400))
        self.assertIsNone(X.match_game(by, "CHI", "KC", ko))


class Quotes(unittest.TestCase):
    rec = {"kalshi": {"home": [[100, 0.60, 0.61], [3700, 0.62, 0.63]],
                      "away": [[100, 0.39, 0.40], [3700, 0.37, 0.38]]},
           "poly": [[100, 0.60], [3700, 0.625]]}

    def test_uses_last_price_at_or_before_the_moment(self):
        q = X.quote(self.rec, "kalshi", 3000, FEES)
        self.assertAlmostEqual(q["home"], 0.61 + 0.07 * 0.61 * 0.39)   # not the later 0.63
        q = X.quote(self.rec, "kalshi", 3700, FEES)
        self.assertAlmostEqual(q["home"], 0.63 + 0.07 * 0.63 * 0.37)

    def test_cheaper_of_yes_and_no(self):
        rec = {"kalshi": {"home": [[100, 0.60, 0.65]], "away": [[100, 0.38, 0.40]]}}
        q = X.quote(rec, "kalshi", 200, FEES)
        self.assertAlmostEqual(q["home"], 0.62 + 0.07 * 0.62 * 0.38)    # NO on the away team at 1 - 0.38

    def test_missing_stale_or_thin_is_none(self):
        self.assertIsNone(X.quote(self.rec, "kalshi", 50, FEES))         # before any price
        self.assertIsNone(X.quote(self.rec, "kalshi", 3700 + 4 * 3600, FEES))   # 4 hours stale
        thin = {"kalshi": {"home": [[100, 0.10, 0.90]], "away": [[100, 0.10, 0.90]]}}
        self.assertIsNone(X.quote(thin, "kalshi", 200, FEES))

    def test_polymarket_pays_half_a_cent_over_the_mid(self):
        q = X.quote(self.rec, "poly", 3700, FEES)
        self.assertAlmostEqual(q["mid"], 0.625)
        self.assertAlmostEqual(q["away"], 0.38 + 0.05 * 0.38 * 0.62)


class LivePrices(unittest.TestCase):
    def test_live_quotes_replace_stale_ones_and_work_without_a_key(self):
        import odds
        from unittest import mock
        games = [g("2026-10-11", hml=-150.0, aml=130.0), g("2026-10-18", home="KC", away="LV", hml=-200.0, aml=170.0)]
        stale = {"book": "Kalshi", "key": "kalshi", "cents": 70.0, "dec": 1.38, "point": None}
        shop = {games[0]["gid"]: {"books": 5, "mine": 1, "fair": {"home": 0.58}, "ml": {"home": dict(stale)},
                                  "spread": {}, "total": {}}}
        live = {games[0]["gid"]: {"kalshi": {"home": 0.55, "away": 0.46}},
                games[1]["gid"]: {"polymarket": {"home": 0.64, "away": 0.37}}}
        with mock.patch.object(odds, "my_books", lambda: {"kalshi", "polymarket"}):
            odds.add_live_exchanges(shop, live, games)
        h = shop[games[0]["gid"]]["ml"]["home"]
        self.assertEqual((h["cents"], h["live"]), (55.0, True))         # the stale 70¢ copy is gone
        self.assertAlmostEqual(h["ev"], round((0.58 / (0.55 + 0.07 * 0.55 * 0.45) - 1) * 100, 1))
        s2 = shop[games[1]["gid"]]                                        # no sportsbook data: nflverse line
        self.assertEqual(s2["books"], 0)
        self.assertAlmostEqual(s2["fair"]["home"], round(odds._fair2(-200.0, 170.0), 4))
        self.assertEqual(s2["ml"]["away"]["book"], "Polymarket")


class LineMove(unittest.TestCase):
    def test_last_ats_uses_only_earlier_games(self):
        games = [g("2026-09-13", hs=30.0, spread=3.0, **{"as": 0.0}), g("2026-09-20"), g("2026-09-27")]
        out = LM.last_ats(games)
        self.assertEqual(out[id(games[0])], 0.0)                      # nothing known before week 1
        self.assertAlmostEqual(out[id(games[1])], 3.0)                # GB +27 vs CHI -27, capped at 21 pts / 7
        games[1]["hs"], games[1]["as"], games[1]["spread"] = 0.0, 50.0, 0.0
        self.assertAlmostEqual(LM.last_ats(games)[id(games[1])], 3.0)  # its own result can't leak in

    def test_pick_needs_positive_return(self):
        self.assertIsNone(LM.pick(0.50, 1.9, 1.9))
        self.assertEqual(LM.pick(0.55, 1.95, 1.95)[0], True)
        self.assertEqual(LM.pick(0.40, 1.80, 2.00)[0], False)

    def test_ols_recovers_a_line(self):
        X_ = [[1.0, x] for x in range(10)]
        y = [2.0 + 0.5 * x for x in range(10)]
        beta, _ = LM.ols(X_, y)
        self.assertAlmostEqual(beta[0], 2.0)
        self.assertAlmostEqual(beta[1], 0.5)


if __name__ == "__main__":
    unittest.main()
