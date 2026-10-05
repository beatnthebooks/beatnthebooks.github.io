"""
rift_edge.py
============
A self-contained "edge finder" that mirrors the public methodology Rift
Odds describes on its site:

    1. Convert a sportsbook's odds into an implied probability.
    2. Strip out the book's margin ("vig") to get a FAIR market probability.
    3. Edge = the gap between your model's probability and that fair price.
    4. Label the edge LOW / MEDIUM / HIGH on the same thresholds they use.

This reproduces only the ANALYSIS math, which is standard and openly
documented. It deliberately contains NO prediction model: you supply the
win probability (`model_prob`), or wire your own model into analyze_game().
The win model is the separate, harder piece we'll build next.

No network access, no connection to riftodds.com — just the math.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence


# ----------------------------------------------------------------------
# 1. Odds  ->  probability
# ----------------------------------------------------------------------

def american_to_decimal(american: float) -> float:
    """American moneyline -> decimal odds.  -140 -> 1.714,  +120 -> 2.20"""
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def decimal_to_american(decimal: float) -> int:
    if decimal <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    if decimal >= 2.0:
        return round((decimal - 1.0) * 100.0)
    return round(-100.0 / (decimal - 1.0))


def implied_prob(decimal: float) -> float:
    """Decimal odds -> raw implied probability (still contains the vig)."""
    if decimal <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / decimal


def american_implied(american: float) -> float:
    return implied_prob(american_to_decimal(american))


# ----------------------------------------------------------------------
# 2. Remove the vig  (the book's built-in margin)
# ----------------------------------------------------------------------
#
# Raw implied probabilities for the two sides sum to MORE than 1 — that
# excess is the book's margin. De-vigging rescales them back to a fair
# set that sums to exactly 1.

def remove_vig(raw_probs: Sequence[float],
               method: str = "multiplicative") -> list[float]:
    """
    Convert raw implied probs (sum > 1) into fair no-vig probs (sum = 1).

      "multiplicative" : proportional normalization. The standard, and the
                         literal meaning of "margin removed". DEFAULT.
      "additive"       : subtract the margin equally across outcomes.
      "power"          : solve p_i = q_i ** k so the set sums to 1; shades
                         favorites and underdogs differently (closer to how
                         sharp books actually price).
    """
    q = list(raw_probs)
    if any(x <= 0 for x in q):
        raise ValueError("Probabilities must be positive")
    total = sum(q)

    if method == "multiplicative":
        return [x / total for x in q]

    if method == "additive":
        n = len(q)
        margin = total - 1.0
        return [x - margin / n for x in q]

    if method == "power":
        lo, hi = 0.0, 10.0
        for _ in range(200):                 # bisection on the exponent k
            k = (lo + hi) / 2.0
            if sum(x ** k for x in q) > 1.0:
                lo = k
            else:
                hi = k
        k = (lo + hi) / 2.0
        return [x ** k for x in q]

    raise ValueError(f"Unknown de-vig method: {method!r}")


def book_margin_pct(raw_probs: Sequence[float]) -> float:
    """The book's total margin, as a percent.  e.g. 3.8 means 3.8% vig."""
    return (sum(raw_probs) - 1.0) * 100.0


# ----------------------------------------------------------------------
# 3. Edge + the numbers you'd actually act on
# ----------------------------------------------------------------------

# Rift's labels: LOW (<5%), MEDIUM (5-9.9%), HIGH (10%+)
EDGE_TIERS = (("HIGH", 10.0), ("MEDIUM", 5.0))


def classify_edge(edge_pp: float) -> str:
    a = abs(edge_pp)
    for label, threshold in EDGE_TIERS:
        if a >= threshold:
            return label
    return "LOW"


@dataclass
class EdgeResult:
    model_prob: float         # your win probability for this side (0..1)
    market_decimal: float     # the actual price you would bet at
    market_raw_prob: float    # implied prob WITH vig
    market_fair_prob: float   # no-vig market prob
    edge_pp: float            # model - fair market, in percentage points
    tier: str                 # LOW / MEDIUM / HIGH
    ev_pct: float             # expected value % at the posted price
    kelly_pct: float          # full-Kelly stake as % of bankroll (0 if -EV)

    def as_dict(self) -> dict:
        return asdict(self)


def find_edge(model_prob: float,
              market_decimal: float,
              opponent_decimal: float,
              vig_method: str = "multiplicative") -> EdgeResult:
    """
    Core edge finder for ONE side of a two-way market.

        model_prob       : your probability this side wins (0..1)
        market_decimal   : decimal odds offered on THIS side
        opponent_decimal : decimal odds on the OTHER side
                           (needed to measure and strip the vig)

    Note: edge is measured against the no-vig fair probability, but EV and
    Kelly use the REAL posted price (market_decimal) — that's the price your
    money actually gets.
    """
    if not 0.0 < model_prob < 1.0:
        raise ValueError("model_prob must be strictly between 0 and 1")

    raw_side = implied_prob(market_decimal)
    raw_opp = implied_prob(opponent_decimal)
    fair_side, _fair_opp = remove_vig([raw_side, raw_opp], method=vig_method)

    edge_pp = (model_prob - fair_side) * 100.0

    b = market_decimal - 1.0
    ev_pct = (model_prob * market_decimal - 1.0) * 100.0
    kelly = (model_prob * b - (1.0 - model_prob)) / b
    kelly_pct = max(0.0, kelly) * 100.0

    return EdgeResult(
        model_prob=model_prob,
        market_decimal=market_decimal,
        market_raw_prob=raw_side,
        market_fair_prob=fair_side,
        edge_pp=edge_pp,
        tier=classify_edge(edge_pp),
        ev_pct=ev_pct,
        kelly_pct=kelly_pct,
    )


def analyze_game(home_odds, away_odds, model_home, model_away=None,
                 odds_format: str = "american",
                 vig_method: str = "multiplicative"):
    """
    Analyze both sides of a two-way game.

        home_odds, away_odds : the two prices (american by default, or decimal)
        model_home           : your model's win prob for the home side
        model_away           : optional; defaults to 1 - model_home

    Returns (home_result, away_result) as EdgeResult objects.
    """
    if model_away is None:
        model_away = 1.0 - model_home

    if odds_format == "american":
        dh = american_to_decimal(home_odds)
        da = american_to_decimal(away_odds)
    elif odds_format == "decimal":
        dh, da = float(home_odds), float(away_odds)
    else:
        raise ValueError("odds_format must be 'american' or 'decimal'")

    home_res = find_edge(model_home, dh, da, vig_method)
    away_res = find_edge(model_away, da, dh, vig_method)
    return home_res, away_res


# ----------------------------------------------------------------------
# Demo
# ----------------------------------------------------------------------

def _row(res: EdgeResult, name: str) -> str:
    sign = "+" if res.edge_pp >= 0 else ""
    return (f"  {name:<10} price {res.market_decimal:>5.2f}  "
            f"model {res.model_prob * 100:5.1f}%  "
            f"fair {res.market_fair_prob * 100:5.1f}%  "
            f"edge {sign}{res.edge_pp:5.1f}pp [{res.tier:<6}]  "
            f"EV {res.ev_pct:+6.1f}%  Kelly {res.kelly_pct:4.1f}%")


if __name__ == "__main__":
    print("RIFT-STYLE EDGE FINDER  (analysis only, no model)")
    print("=" * 78)

    # (home, home_odds, away, away_odds, YOUR model prob for home)
    games = [
        ("Vikings", -140, "Packers", +120, 0.64),
        ("Lakers",  +110, "Celtics", -130, 0.40),
        ("Yankees", -160, "Red Sox", +140, 0.60),
    ]

    for home, ho, away, ao, p_home in games:
        hr, ar = analyze_game(ho, ao, p_home, odds_format="american")
        vig = book_margin_pct([american_implied(ho), american_implied(ao)])
        print(f"\n{home} ({ho:+d}) vs {away} ({ao:+d})    book vig {vig:.1f}%")
        print(_row(hr, home))
        print(_row(ar, away))

    print("\n" + "=" * 78)
    print("Edge is measured vs the no-vig fair price. Bet the side with a")
    print("positive edge / positive EV; Kelly suggests a stake size.")
