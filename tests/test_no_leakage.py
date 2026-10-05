"""No look-ahead: changing a game's result (or any later result) must not change any
prediction or signal made before it, and changing TEST-season results must not change
anything chosen on the training seasons. Uses the real data/games.csv."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import edge_lab as L  # noqa: E402
import rift_real as R  # noqa: E402

PARAMS = json.loads((ROOT / "results" / "current_ratings.json").read_text(encoding="utf-8"))["params"]


def flipped(games, keep):
    """Copy of games with the score swapped for every played game where keep(i, g) is False."""
    out = []
    for i, g in enumerate(games):
        g2 = dict(g)
        if not keep(i, g) and g["hs"] is not None:
            g2["hs"], g2["as"] = g["as"], g["hs"] + 7      # a different result and margin
        out.append(g2)
    return out


class NoLookAhead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = L.load()
        cls.k = next(i for i, g in enumerate(cls.games) if g["season"] == 2015 and g["week"] == 9)
        cls.recs = R.run(cls.games, **PARAMS)[0]
        cls.sigma = L.fit_sigma(cls.games, L.DEV["spread"])
        cls.rows = L.build_rows(cls.games, cls.recs, cls.sigma)
        cls.alt = flipped(cls.games, lambda i, g: i < cls.k)          # game k and everything after
        cls.alt_recs = R.run(cls.alt, **PARAMS)[0]
        cls.alt_rows = L.build_rows(cls.alt, cls.alt_recs, cls.sigma)

    def test_elo_prediction_ignores_own_and_future_results(self):
        for i in range(self.k + 1):
            self.assertEqual(self.recs[i]["p"], self.alt_recs[i]["p"], f"game {i}")
        self.assertNotEqual([r["p"] for r in self.recs[self.k + 1:]],
                            [r["p"] for r in self.alt_recs[self.k + 1:]],
                            "the check must be able to see a change")

    def test_signals_ignore_own_and_future_results(self):
        for i in range(self.k + 1):
            self.assertEqual(self.rows[i]["side"], self.alt_rows[i]["side"], f"side signals, game {i}")
            self.assertEqual(self.rows[i]["tot"], self.alt_rows[i]["tot"], f"total signals, game {i}")
        later = range(self.k + 1, self.k + 400)
        self.assertTrue(any(self.rows[i]["side"] != self.alt_rows[i]["side"] for i in later))


class TrainingIgnoresTestSeasons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = L.load()
        cls.alt = flipped(cls.games, lambda i, g: g["season"] < 2016)

    def test_elo_tuning_loss(self):
        for p in (PARAMS, dict(PARAMS, k=30, regress=0.25)):
            self.assertEqual(R.train_loss(self.games, **p), R.train_loss(self.alt, **p))

    def test_blend_weight(self):
        def blend(games):
            recs = R.run(games, **PARAMS)[0]
            P, M, O, _ = R.collect(recs, R.TRAIN)
            return R.best_blend(P, M, O)
        self.assertEqual(blend(self.games), blend(self.alt))

    def test_edge_lab_screening_data(self):
        sigma = L.fit_sigma(self.games, L.DEV["spread"])
        self.assertEqual(sigma, L.fit_sigma(self.alt, L.DEV["spread"]))
        a = L.build_rows(self.games, R.run(self.games, **PARAMS)[0], sigma)
        b = L.build_rows(self.alt, R.run(self.alt, **PARAMS)[0], sigma)
        for market in L.MARKETS:
            ra, rb = L.market_rows(a, market, L.DEV[market]), L.market_rows(b, market, L.DEV[market])
            ykey, grp = L.MARKETS[market][1], L.MARKETS[market][2]
            self.assertEqual([(r[grp], r[ykey]) for r in ra], [(r[grp], r[ykey]) for r in rb], market)


if __name__ == "__main__":
    unittest.main()
