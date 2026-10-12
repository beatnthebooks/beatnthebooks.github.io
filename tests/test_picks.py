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
        recs = [rec(2020, True)] * 20 + [rec(2020, False)] * 20
        base = W.fit_lean_shift(recs, 0.3, 2026)
        # 2010 and 2018: the model's tuning seasons (first unseen season is 2019 since Oct 6); 2026: this season
        more = W.fit_lean_shift(recs + [rec(2010, True)] * 80 + [rec(2018, True)] * 80 + [rec(2026, True)] * 80,
                                0.3, 2026)
        self.assertAlmostEqual(base["shift"], more["shift"])
        self.assertEqual(more["n"], 40)


class SpreadMath(unittest.TestCase):
    def test_cover_is_even_when_model_agrees_with_the_line(self):
        p = 1 / (1 + 10 ** (-3 * 25 / 400))                 # Elo win prob worth exactly 3 points
        self.assertAlmostEqual(W.spread_cover(p, 3.0, 11.7, 0.28), 0.5, places=6)

    def test_model_likes_home_more_than_the_line(self):
        self.assertGreater(W.spread_cover(0.8, 3.0, 11.7, 0.28), 0.5)
        self.assertLess(W.spread_cover(0.4, 3.0, 11.7, 0.28), 0.5)

    def test_record_uses_unseen_seasons_and_strong_picks_only(self):
        g = dict(game(2020, 24, 10), spread=3.0, hso=-110.0, aso=-110.0)
        strong = [{"g": g, "p": 0.95}] * 5                    # big edges on both ML and spread
        early = [{"g": dict(g, season=s), "p": 0.95} for s in (2010, 2018)] * 25   # tuning seasons: ignored
        weak = [{"g": g, "p": 0.53}] * 50                     # model ~ market (52%): no strong pick
        rec = W.model_record(strong + early + weak, 0.28, 11.7, 2026)
        self.assertEqual(rec["ml"]["n"], 5)


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


import json  # noqa: E402
import tempfile  # noqa: E402
from unittest import mock  # noqa: E402

import picks as PK  # noqa: E402


def card(status="upcoming", **kw):
    base = {"id": "g1", "status": status, "koIso": "2026-10-11T12:00", "homeName": "Packers", "awayName": "Bears",
            "pElo": 0.6, "eloLine": 4.0, "wind": 16.0, "gaps": []}
    return dict(base, **kw)


WIND = {"point": 44.5, "edge": 3.1, "dec": 1.92, "cents": 52.0, "book": "Kalshi"}


class Ranking(unittest.TestCase):
    def test_bigger_edge_first_and_one_bet_listed_once(self):
        r = card(signal="under", windPick=WIND,
                 gaps=[{"mk": "ml", "side": "away", "point": None, "ev": 6.2, "dec": 2.4, "cents": 40.0, "book": "Polymarket"}],
                 mkt={"lean": "away", "fair": 0.58, "leanEv": 9.9, "leanEdge": 1.4, "leanDec": 2.4, "leanCents": 40.0,
                      "leanBook": "Polymarket"})
        P = PK.game_picks(r, 5.0)
        self.assertEqual([p["text"] for p in P], ["Bears to win", "Under 44.5"])   # gap (6.2) beats wind (3.1)
        self.assertEqual(P[0]["edge"], 6.2)                                        # merged: the gap's edge shows
        self.assertEqual(P[0]["src"], ["gap", "lean"])
        self.assertEqual(P[1]["src"], ["wind"])

    def test_model_picks_need_5pct_model_edge(self):
        weak = card(mkt={"lean": "home", "fair": 0.55, "leanEv": 3.0, "leanEdge": -4.0, "leanDec": 1.77, "leanOdds": -130})
        self.assertEqual(PK.game_picks(weak, 5.0), [])
        strong = card(mkt={"lean": "home", "fair": 0.55, "leanEv": 6.0, "leanEdge": -4.0, "leanDec": 1.77, "leanOdds": -130},
                      spreadLean={"side": "home", "point": -3.5, "ev": 7.5, "edge": -2.5, "dec": 1.91, "odds": -110})
        P = PK.game_picks(strong, 5.0)
        self.assertEqual([p["text"] for p in P], ["Packers -3.5", "Packers to win"])   # by the model's edge, 7.5 > 6.0
        self.assertTrue(all(p["good"] and p["suggested"] for p in P))

    def test_model_picks_rank_by_the_edge_shown(self):
        # Mason, Oct 6 2026: a model pick ranks by the model's own edge (9.9 shown), above a wind under showing 3.1,
        # even though its realistic edge (-1.0) is lower
        r = card(signal="under", windPick=WIND,
                 mkt={"lean": "away", "fair": 0.42, "leanEv": 9.9, "leanEdge": -1.0, "leanDec": 2.4, "leanCents": 40.0,
                      "leanBook": "Polymarket"})
        P = PK.game_picks(r, 5.0)
        self.assertEqual([p["text"] for p in P], ["Bears to win", "Under 44.5"])
        self.assertEqual([PK.rank_edge(p) for p in P], [9.9, 3.1])


class UnitSizing(unittest.TestCase):
    def test_units_follow_the_evidence(self):
        u = lambda **p: PK.units_for(dict({"good": True, "src": [p.get("edgeFrom")]}, **p))
        self.assertEqual(u(edgeFrom="wind", edge=4.0), 1.0)
        self.assertEqual(u(edgeFrom="wind", edge=6.5), 1.5)                  # great price
        self.assertEqual(u(edgeFrom="roof", edge=7.0), 0.5)                  # roof must be open
        self.assertEqual(u(edgeFrom="gap", edge=5.0), 0.5)
        self.assertEqual(u(edgeFrom="gap", edge=5.0, src=["gap", "lean"]), 0.75)   # the model agrees
        self.assertEqual(u(edgeFrom="lean", edge=-3.0), 0.25)
        self.assertEqual(PK.units_for({"good": False, "edgeFrom": "wind", "edge": 9.0}), 0.0)

    def test_picks_carry_units(self):
        P = PK.game_picks(card(signal="under", windPick=dict(WIND, edge=6.2)), 5.0)
        self.assertEqual(P[0]["units"], 1.5)


class Grading(unittest.TestCase):
    g = {"hs": 24, "as": 20, "hml": -150.0, "aml": 130.0, "spread": 3.0, "hso": -110.0, "aso": -110.0,
         "tot": 44.5, "oo": -110.0, "uo": -110.0}

    def test_results(self):
        self.assertEqual(PK.grade({"mk": "ml", "side": "away", "dec": 2.3}, self.g)["units"], -1.0)
        self.assertEqual(PK.grade({"mk": "spread", "side": "home", "point": -3.5, "dec": 1.9}, self.g)["units"], 0.9)
        self.assertEqual(PK.grade({"mk": "spread", "side": "home", "point": -4.0, "dec": 1.9}, self.g)["won"], None)
        self.assertEqual(PK.grade({"mk": "total", "side": "under", "point": 44.5, "dec": 1.9}, self.g)["units"], 0.9)

    def test_closing_price(self):
        gr = PK.grade({"mk": "total", "side": "under", "point": 44.5, "dec": 2.05}, self.g)    # +105 vs fair 50%
        self.assertAlmostEqual(gr["clv"], 2.5)
        self.assertTrue(gr["beat"])
        gr = PK.grade({"mk": "total", "side": "under", "point": 46.0, "dec": 1.9}, self.g)     # 1.5 pts better
        self.assertEqual((gr["clvPts"], gr["beat"]), (1.5, True))
        gr = PK.grade({"mk": "spread", "side": "away", "point": 2.5, "dec": 1.9}, self.g)      # close was +3
        self.assertEqual((gr["clvPts"], gr["beat"]), (-0.5, False))


class PickLog(unittest.TestCase):
    def run_log(self, rows, now, path):
        with mock.patch.object(PK, "LOG", path):
            return PK.update_log(rows, now)

    def test_first_price_kept_and_frozen_at_kickoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pick_log.json"
            r = card(signal="under", windPick=WIND)
            r["picks"] = PK.game_picks(r, 5.0)
            self.run_log([r], "2026-10-08T09:00", path)
            r2 = card(signal="under", windPick=dict(WIND, cents=56.0, dec=1.75))
            r2["picks"] = PK.game_picks(r2, 5.0)
            log = self.run_log([r2], "2026-10-09T09:00", path)
            e = log["g1"]["total|under|44.5"]
            self.assertEqual((e["first"]["price"]["cents"], e["last"]["price"]["cents"]), (52.0, 56.0))
            r3 = dict(r2, status="live", picks=PK.game_picks(card(signal="under", windPick=dict(WIND, cents=70.0)), 5.0))
            log = self.run_log([r3], "2026-10-11T12:30", path)
            self.assertEqual(log["g1"]["total|under|44.5"]["last"]["price"]["cents"], 56.0)   # no changes after kickoff
            self.assertEqual(log["_meta"]["started"], "2026-10-08T09:00")

    def test_finished_games_graded_at_first_price_or_reconstructed(self):
        g = {"hs": 10, "as": 13, "hml": -150.0, "aml": 130.0, "spread": 3.0, "hso": -110.0, "aso": -110.0,
             "tot": 44.5, "oo": -110.0, "uo": -110.0}
        log = {"_meta": {"started": "2026-10-08T09:00"},
               "g1": {"total|under|44.5": {"pick": {"mk": "total", "side": "under", "point": 44.5, "text": "Under 44.5",
                                                    "src": ["wind"], "edgeFrom": "wind", "why": []},
                                           "first": {"ts": "2026-10-10T13:00", "dec": 1.92, "price": {}, "edge": 3.1},
                                           "last": {"ts": "2026-10-11T09:00", "dec": 1.75, "price": {}, "edge": 1.0}}}}
        logged = card("final", signal="under")                                 # still windy at kickoff
        PK.apply_log([logged], {"g1": g}, log)
        self.assertEqual(logged["picks"][0]["grade"]["units"], 0.92)          # graded at the FIRST price
        after = card("final", id="g2", koIso="2026-10-12T12:00",
                     picks=[{"good": True, "mk": "ml", "side": "home", "dec": 1.7, "edgeFrom": "lean"}])
        PK.apply_log([after], {"g2": g}, log)
        self.assertEqual(after["picks"], [])                                   # log running, nothing shown: no pick
        before = card("final", id="g3", koIso="2026-10-04T12:00",
                      picks=[{"good": True, "mk": "ml", "side": "home", "dec": 1.7, "edgeFrom": "lean"}])
        PK.apply_log([before], {"g3": g}, log)
        self.assertTrue(before["picks"][0]["reconstructed"])
        self.assertNotIn("beat", before["picks"][0]["grade"])                 # no closing-line test at the close

    # ---- Oct 12 fixes: one bet per market and side; wind only the day before; withdrawn wind isn't graded ----
    G_FINAL = {"hs": 10, "as": 13, "hml": -150.0, "aml": 130.0, "spread": 3.0, "hso": -110.0, "aso": -110.0,
               "tot": 44.5, "oo": -110.0, "uo": -110.0}

    @staticmethod
    def entry(point, first_ts, last_ts, kind="wind", first_dec=1.92, last_dec=1.75):
        mk, side = ("total", "under") if kind in ("wind", "roof") else ("spread", "home")
        text = f"Under {point:g}" if mk == "total" else f"Packers {point:+g}"
        return {"pick": {"mk": mk, "side": side, "point": point, "text": text, "src": [kind], "edgeFrom": kind, "why": []},
                "first": {"ts": first_ts, "dec": first_dec, "price": {}, "edge": 3.1},
                "last": {"ts": last_ts, "dec": last_dec, "price": {}, "edge": 1.0}}

    def test_a_moving_line_is_one_bet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pick_log.json"
            for t_, pt in (("2026-10-10T13:00", 44.5), ("2026-10-11T09:00", 43.5)):
                r = card(signal="under", windPick=dict(WIND, point=pt))
                r["picks"] = PK.game_picks(r, 5.0)
                log = self.run_log([r], t_, path)
            self.assertEqual(list(log["g1"]), ["total|under|44.5"])          # not a second "43.5" bet
            self.assertEqual(log["g1"]["total|under|44.5"]["last"]["point"], 43.5)

    def test_old_duplicate_lines_count_once_at_the_first(self):
        log = {"_meta": {"started": "2026-10-01T09:00"},
               "g1": {"spread|home|2.5": self.entry(2.5, "2026-10-06T09:00", "2026-10-07T09:00", "spread", 1.95),
                      "spread|home|1.5": self.entry(1.5, "2026-10-08T09:00", "2026-10-11T09:00", "spread", 1.98)}}
        r = card("final")
        PK.apply_log([r], {"g1": self.G_FINAL}, log)
        self.assertEqual(len(r["picks"]), 1)
        self.assertEqual((r["picks"][0]["point"], r["picks"][0]["dec"]), (2.5, 1.95))

    def test_wind_gone_by_kickoff_or_roof_closed_is_withdrawn(self):
        log = {"_meta": {"started": "2026-10-01T09:00"},
               "g1": {"total|under|44.5": self.entry(44.5, "2026-10-10T13:00", "2026-10-10T16:00")}}
        calm = card("final", wind=6.0)                                       # no signal at kickoff
        PK.apply_log([calm], {"g1": self.G_FINAL}, log)
        self.assertEqual(calm["picks"], [])
        self.assertIn("6 mph", calm["withdrawn"][0]["why"])
        closed = card("final")
        del closed["wind"]                                                     # roof closed: no wind on the card
        PK.apply_log([closed], {"g1": self.G_FINAL}, log)
        self.assertEqual(closed["withdrawn"][0]["why"], "the roof was closed")
        self.assertEqual(PK.scoreboard([calm, closed])["wind"]["n"], 0)

    def test_wind_shown_days_early_is_graded_at_its_last_price(self):
        log = {"_meta": {"started": "2026-10-01T09:00"},       # an old log: first shown six days before kickoff
               "g1": {"total|under|44.5": self.entry(44.5, "2026-10-05T17:16", "2026-10-11T09:00")}}
        r = card("final", signal="under")
        PK.apply_log([r], {"g1": self.G_FINAL}, log)
        self.assertEqual((r["picks"][0]["dec"], r["picks"][0]["logged"]), (1.75, "2026-10-11T09:00"))

    def test_wind_watch_is_not_a_bet_yet(self):
        r = card(signal="under", windPick=WIND, windWatch={"from": "2026-10-10T12:00", "fromLabel": "Sat Oct 10"})
        self.assertEqual(PK.game_picks(r, 5.0), [])

    def test_scoreboard_counts_by_main_reason(self):
        rows = [{"picks": [{"edgeFrom": "roof", "grade": {"units": 0.9, "won": True, "clv": 2.0, "beat": True}},
                           {"edgeFrom": "lean", "reconstructed": True, "grade": {"units": -1.0, "won": False}}]}]
        b = PK.scoreboard(rows)
        self.assertEqual((b["wind"]["won"], b["wind"]["beat"], b["wind"]["clvAvg"]), (1, 1, 2.0))
        self.assertEqual((b["lean"]["lost"], b["lean"]["judged"]), (1, 0))
        self.assertEqual(b["all"]["n"], 2)


if __name__ == "__main__":
    unittest.main()
