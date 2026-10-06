"""The Oct 6 model upgrade (player_value.py): the league-wide QB term and the position-importance scale for
missing players. No network, synthetic games."""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import player_value as PV  # noqa: E402
import qb_model as Q  # noqa: E402


def game(week, home="GB", away="CHI", hs=None, as_=None, hqb=None, aqb=None, season=2020):
    return {"season": season, "week": week, "home": home, "away": away, "hs": hs, "as": as_, "neutral": False,
            "hrest": 7.0, "arest": 7.0, "hqb": hqb, "aqb": aqb, "gid": f"{season}_{week}_{away}_{home}"}


elo = lambda p: 400 * math.log10(p / (1 - p))


class SkillValue(unittest.TestCase):
    def test_only_earlier_games_and_never_negative(self):
        epa = {"p1": {2020: [(1, 4.0), (2, 8.0), (3, 100.0)], 2019: [(5, 1.0)]}, "p2": {2020: [(1, -3.0)]}}
        self.assertEqual(PV.epa_before(epa, "p1", 2020, 3), 6.0)         # weeks 1-2 only, not week 3's 100
        self.assertEqual(PV.epa_before(epa, "p1", 2020, 1), 1.0)         # no game yet: last season
        self.assertEqual(PV.epa_before(epa, "p2", 2020, 2), 0.0)         # a negative player isn't a bonus
        self.assertEqual(PV.epa_before(epa, "nobody", 2020, 2), 0.0)

    def test_position_weights_set_in_advance(self):
        w = PV.POS_W
        self.assertTrue(w["WR"] == w["DE"] == 1.0 and w["CB"] == w["T"] == 0.9 and w["RB"] == 0.4)
        self.assertNotIn("QB", w)                                        # quarterbacks have their own ratings
        self.assertNotIn("K", w)


class ImportanceInTheModel(unittest.TestCase):
    params = dict(k=20, hfa=55, regress=0.5, mov=True, rest_pts=6, qb_pen=0, mult=0.0)

    def p(self, **kw):
        return Q.run_qb([game(1)], {}, **dict(self.params, **kw))[0][0]["p"]

    def test_missing_starter_costs_w_imp_elo(self):
        base = self.p()
        pv = {(2020, 1, "GB"): (1.0, 0.0, 0.0, 0.0)}                     # one full-time weight-1.0 player out
        self.assertAlmostEqual(elo(base) - elo(self.p(pv=pv, w_imp=24.0)), 24.0, places=6)
        pq = {(2020, 1, "CHI"): (0.0, 1.0, 0.0, 0.0)}                    # one questionable, counted at q_frac
        self.assertAlmostEqual(elo(self.p(pv=pq, w_imp=24.0, q_frac=0.5)) - elo(base), 12.0, places=6)

    def test_off_by_default(self):
        pv = {(2020, 1, "GB"): (3.0, 3.0, 9.0, 9.0)}
        self.assertEqual(self.p(), self.p(pv=pv))                         # weights 0: no effect
        self.assertEqual(self.p(), self.p(abs_mult=0.0))


if __name__ == "__main__":
    unittest.main()
