"""
rift_model.py
=============
A baseline WIN-PROBABILITY model that plugs into rift_edge.py to turn the
edge finder into a full system: estimate each team's win probability, then
rank a slate by betting value.

It's an Elo / power-rating model (margin-aware, home-field aware). You can:
  * feed it past results so it LEARNS ratings  -> model.train(results)
  * or load ratings you trust from anywhere    -> model.set_ratings({...})
    (Sagarin, Massey, DVOA-style, market priors, your own numbers)
then rank_slate() runs every game through the edge math and sorts by EV.

------------------------------------------------------------------------
HONEST LIMITS  -- please read, this is the whole point:
  * Elo is a clean, transparent baseline. It is NOT a market-beater on its
    own. De-vigged sportsbook odds are among the most accurate public
    predictors in existence; a from-scratch Elo will, on average, LOSE to
    the closing line once you pay the vig. That's precisely why a public
    pick record can hover near 50-51% -- break-even is ~52.4% at -110.
  * The de-vig math is identical for everyone, so it is never your edge.
    A real edge comes from information the market hasn't priced yet:
    injury/weather news before the line moves, a stale price at a slow
    book, or genuinely better inputs than the market has.
  * Treat rank_slate() output as a SCREEN that says "look here," not as
    vetted picks. Every flagged game still needs a human check.
------------------------------------------------------------------------
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from rift_edge import analyze_game, EdgeResult  # noqa: F401


# ----------------------------------------------------------------------
# The win-probability model
# ----------------------------------------------------------------------

@dataclass
class EloModel:
    k: float = 20.0                 # update speed (NFL ~20)
    home_adv: float = 55.0          # home field, in Elo points (~2.5 pts)
    base: float = 1500.0            # rating for a team we've never seen
    use_mov: bool = True            # margin-of-victory multiplier (538-style)
    rest_pts: float = 5.0           # Elo points per extra day of rest
    rest_cap: float = 35.0          # max rest swing, in Elo points
    pts_per_elo: float = 25.0       # Elo points per point of spread (~25)
    ratings: dict = field(default_factory=dict)

    # --- reads ---
    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.base)

    def set_ratings(self, ratings: dict) -> None:
        """Load power ratings you trust (overrides learned values)."""
        self.ratings.update(ratings)

    def _rest_adj(self, home_rest, away_rest) -> float:
        """Rest edge in Elo points. Pass days since each team's last game
        (7 = normal, 14 = off a bye, ~4 = short/Thursday week)."""
        if home_rest is None or away_rest is None:
            return 0.0
        swing = self.rest_pts * (home_rest - away_rest)
        return max(-self.rest_cap, min(self.rest_cap, swing))

    def win_prob(self, home: str, away: str, neutral: bool = False,
                 home_rest=None, away_rest=None) -> float:
        """Probability the HOME team wins (ties folded in as half)."""
        hfa = 0.0 if neutral else self.home_adv
        diff = (self.rating(home) + hfa - self.rating(away)
                + self._rest_adj(home_rest, away_rest))
        return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    def elo_to_spread(self, home: str, away: str, neutral: bool = False) -> float:
        """Model's point spread for the home team (negative = home favored)."""
        hfa = 0.0 if neutral else self.home_adv
        diff = self.rating(home) + hfa - self.rating(away)
        return -diff / self.pts_per_elo

    def regress_to_mean(self, frac: float = 1.0 / 3.0) -> "EloModel":
        """Pull every rating toward base by `frac`. Run between seasons
        (NFL carries ~2/3 of last year's rating; frac ~ 1/3)."""
        for t, r in list(self.ratings.items()):
            self.ratings[t] = self.base + (r - self.base) * (1.0 - frac)
        return self

    # --- learning ---
    def update(self, home, away, home_score, away_score, neutral=False,
               home_rest=None, away_rest=None):
        p_home = self.win_prob(home, away, neutral, home_rest, away_rest)
        if home_score > away_score:
            actual = 1.0
        elif home_score < away_score:
            actual = 0.0
        else:
            actual = 0.5
        margin = abs(home_score - away_score)

        mult = 1.0
        if self.use_mov and margin > 0:
            hfa = 0.0 if neutral else self.home_adv
            elo_diff = (self.rating(home) + hfa - self.rating(away)
                        + self._rest_adj(home_rest, away_rest))
            # from the winner's perspective, as in the 538 formula
            winner_diff = elo_diff if actual == 1.0 else -elo_diff
            mult = math.log(margin + 1.0) * (2.2 / (winner_diff * 0.001 + 2.2))

        delta = self.k * mult * (actual - p_home)
        self.ratings[home] = self.rating(home) + delta
        self.ratings[away] = self.rating(away) - delta

    def train(self, results):
        """results: iterable of (home, away, home_score, away_score)."""
        for home, away, hs, as_ in results:
            self.update(home, away, hs, as_)
        return self


# ----------------------------------------------------------------------
# Market anchoring -- the single most useful real-world upgrade
# ----------------------------------------------------------------------

def blend_probs(model_prob: float, market_prob: float, weight: float) -> float:
    """
    Shade the market toward your model instead of replacing it.

        weight = 0.0  -> trust the market completely (the sharp baseline)
        weight = 1.0  -> trust your model completely (dangerous)
        weight ~ 0.1-0.3 is the realistic range: the de-vigged market is
        already excellent, so your model should only nudge it.

    Why this matters: a raw model that disagrees hard with the market is
    usually wrong, not early. Blending caps your downside when the model is
    off and still captures value when it's genuinely ahead. The backtest
    harness (rift_backtest.py) will tell you the weight that actually helped
    on YOUR data -- often that's a small number, and sometimes it's zero.
    """
    w = max(0.0, min(1.0, weight))
    return w * model_prob + (1.0 - w) * market_prob


# ----------------------------------------------------------------------
# The slate ranker  (model + edge finder together)
# ----------------------------------------------------------------------

@dataclass
class SlateGame:
    home: str
    away: str
    home_odds: float
    away_odds: float
    odds_format: str = "american"
    neutral: bool = False
    kickoff: str = ""               # free label, e.g. "3:25 PM ET"


def rank_slate(model: EloModel, games, vig_method="multiplicative",
               min_ev: float = -1e9):
    """
    Run every game through the model + edge finder; return rows sorted by the
    better side's EV (highest first). Filter with min_ev (percent).
    """
    rows = []
    for g in games:
        p_home = model.win_prob(g.home, g.away, g.neutral)
        hr, ar = analyze_game(g.home_odds, g.away_odds, p_home,
                              odds_format=g.odds_format, vig_method=vig_method)
        best = hr if hr.ev_pct >= ar.ev_pct else ar
        best_side = g.home if best is hr else g.away
        rows.append({
            "game": f"{g.away} @ {g.home}",
            "kickoff": g.kickoff,
            "best_side": best_side,
            "model_prob": best.model_prob,
            "fair_prob": best.market_fair_prob,
            "price": best.market_decimal,
            "edge_pp": best.edge_pp,
            "tier": best.tier,
            "ev_pct": best.ev_pct,
            "kelly_pct": best.kelly_pct,
        })
    rows.sort(key=lambda r: r["ev_pct"], reverse=True)
    return [r for r in rows if r["ev_pct"] >= min_ev]


def print_slate(rows) -> None:
    print(f"{'GAME':<20}{'WHEN':<11}{'BET':<10}{'MODEL':>7}{'FAIR':>7}"
          f"{'EDGE':>8}{'TIER':>8}{'EV':>8}{'KELLY':>7}")
    print("-" * 86)
    for r in rows:
        sign = "+" if r["edge_pp"] >= 0 else ""
        print(f"{r['game']:<20}{r['kickoff']:<11}{r['best_side']:<10}"
              f"{r['model_prob']*100:6.1f}%{r['fair_prob']*100:6.1f}%"
              f"{sign}{r['edge_pp']:5.1f}pp{r['tier']:>8}"
              f"{r['ev_pct']:+7.1f}%{r['kelly_pct']:5.1f}%")


# ----------------------------------------------------------------------
# Demo  (EXAMPLE ratings and odds -- illustrative, NOT real games)
# ----------------------------------------------------------------------

if __name__ == "__main__":
    model = EloModel()

    # These are MADE-UP power ratings to show the mechanism. Replace with
    # real ones (learned via model.train(...) or loaded from a source).
    model.set_ratings({
        "Chiefs": 1680, "Bills": 1655, "Ravens": 1640, "49ers": 1650,
        "Jets": 1485, "Giants": 1470, "Panthers": 1450, "Titans": 1460,
    })

    slate = [
        SlateGame("Chiefs", "Jets",     -360, +280, kickoff="1:00 PM ET"),
        SlateGame("49ers",  "Panthers", -280, +230, kickoff="3:25 PM ET"),
        SlateGame("Bills",  "Titans",   -300, +240, kickoff="3:25 PM ET"),
        SlateGame("Ravens", "Giants",   -250, +210, kickoff="1:00 PM ET"),
    ]

    print("SLATE RANKED BY MODEL EV   (EXAMPLE DATA -- illustrative only)")
    print("=" * 86)
    rows = rank_slate(model, slate)
    print_slate(rows)

    print("\n+EV plays only (what the screen would surface):")
    plus = [r for r in rows if r["ev_pct"] > 0]
    if plus:
        print_slate(plus)
    else:
        print("  none -- model agrees with the market, no value to bet.")

    print("\nReminder: edges here come from made-up ratings. With real,")
    print("current ratings a clean Elo still won't beat the closing line on")
    print("average. Use this to screen, then verify every play by hand.")
