"""
line_move.py
============
Can we predict where the moneyline will CLOSE from what's known when it OPENS?

The closing line is the market's best guess, and our model can't beat it. But lines move
during the week, and earlier checks found they tend to move toward our model's leans. If we
can predict the move, we can bet the opening price before it moves (positive closing-line
value, the best early sign of a real edge).

Data: data/nfl_odds_history.xlsx (aussportsbetting.com, personal use only), opening and closing
moneylines 2014-2025: Pinnacle 2014-17, bet365 2018-24, betr 2025.

Plan, fixed before running:
  1. Model probabilities "as of opening day" (qb_model.run_qb(qb_at_open=True)): a team's starter
     is whoever started its previous game, because a midweek QB injury isn't known at the open.
     First, re-run the earlier "lines move toward our leans" check this way, since the earlier
     version used the actual starters (a leak).
  2. Target: the move, logit(p_close) - logit(p_open), using no-vig prices.
     Candidate signals, all known at the open (home minus away):
        gap       logit(p_model) - logit(p_open)        our model disagrees with the opener
        fav       logit(p_open)                          lines drift toward favorites?
        last_ats  each team's last game vs the spread    does the market chase or fade last week?
        rest      rest-day difference / 7
     Screen on 2014-2019 (least squares): keep a signal only if |z| >= 2 and it has the same
     sign in 2014-16 and 2017-19.
  3. Test 2020-2025 once, refitting each season on earlier seasons only. Compare two rules,
     both betting at the opening price:
        current  the site's lean: 28% model + 72% opening market, bet the side with a positive
                 expected return
        move     predicted closing price; bet the side whose opening price beats it
     Scored by: how often the line moved our way, value vs the close (the expected return if the
     closing price is right: p_close x decimal odds - 1, low noise) and actual return.

Usage:  py line_move.py
Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import history as H
import qb_model as Q
from edge_lab import _inverse, load, logit, sigmoid

ROOT = Path(__file__).resolve().parent
DEV = set(range(2014, 2020))
TEST = set(range(2020, 2026))
HALVES = (set(range(2014, 2017)), set(range(2017, 2020)))
FEATURES = ("gap", "fav", "last_ats", "rest")
SETTINGS = ROOT / "results" / "line_move_settings.json"


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def last_ats(games) -> dict:
    """{id(game): home team's last result vs the spread - away team's}, this season only.
    nflverse spread_line = expected home margin."""
    out, last, season = {}, {}, None
    for g in games:
        if g["season"] != season:
            season, last = g["season"], {}
        h, a = g["home"], g["away"]
        out[id(g)] = max(-21.0, min(21.0, last.get(h, 0.0) - last.get(a, 0.0))) / 7.0
        if g["hs"] is not None and g["spread"] is not None:
            res = (g["hs"] - g["as"]) - g["spread"]
            last[h], last[a] = res, -res
    return out


def model_probs(games, at_open=True) -> dict:
    m = Q.Model()
    recs, _ = Q.run_qb(games, m.stats, team_epa=m.team_epa, qb_at_open=at_open, **m.params)
    return {id(r["g"]): r["p"] for r in recs}, m.blend_w


def build(games, p_open, ats) -> list:
    """One row per game with opening + closing moneylines (2014 on)."""
    rows = []
    for mt in H.match(H.read_xlsx(), games):
        g = mt["g"]
        if g["season"] < 2014:
            continue
        dh, da, fo = H.side_prices(mt, "o")
        dhc, dac, fc = H.side_prices(mt, "c")
        p = p_open.get(id(g))
        if fo is None or fc is None or p is None:
            continue
        f = {"gap": logit(p) - logit(fo), "fav": logit(fo), "last_ats": ats[id(g)],
             "rest": max(-7.0, min(7.0, g["hrest"] - g["arest"])) / 7.0}
        y = None if g["hs"] == g["as"] else (1.0 if g["hs"] > g["as"] else 0.0)
        rows.append({"g": g, "season": g["season"], "src": H.source(g["season"]), "p": p,
                     "fo": fo, "fc": fc, "dh": dh, "da": da, "f": f, "y": y,
                     "move": logit(fc) - logit(fo)})
    return rows


# ----------------------------------------------------------------------
# Least squares
# ----------------------------------------------------------------------

def ols(X, y):
    """(coefs, standard errors)."""
    k = len(X[0])
    XtX = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    Xty = [sum(x[i] * t for x, t in zip(X, y)) for i in range(k)]
    inv = _inverse(XtX)
    beta = [sum(inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]
    rss = sum((t - sum(b * v for b, v in zip(beta, x))) ** 2 for x, t in zip(X, y))
    s2 = rss / max(1, len(y) - k)
    return beta, [math.sqrt(max(0.0, s2 * inv[i][i])) for i in range(k)]


def design(r, feats):
    return [1.0] + [r["f"][f] for f in feats]


def fit(rows, feats):
    return ols([design(r, feats) for r in rows], [r["move"] for r in rows])[0]


def predict_close(beta, feats, fo, f):
    """Predicted closing no-vig home probability."""
    return sigmoid(logit(fo) + beta[0] + sum(b * f[k] for b, k in zip(beta[1:], feats)))


def screen(rows):
    dev = [r for r in rows if r["season"] in DEV]
    beta, se = ols([design(r, FEATURES) for r in dev], [r["move"] for r in dev])
    halves = [fit([r for r in dev if r["season"] in h], FEATURES) for h in HALVES]
    keep, lines = [], []
    for i, f in enumerate(FEATURES, start=1):
        z = beta[i] / se[i] if se[i] else 0.0
        same = halves[0][i] * halves[1][i] > 0
        ok = abs(z) >= 2 and same
        lines.append(f"  {f:<10} coef {beta[i]:+.4f}  z = {z:+5.2f}  halves {halves[0][i]:+.4f} / "
                     f"{halves[1][i]:+.4f}  {'KEEP' if ok else 'drop'}")
        if ok:
            keep.append(f)
    return keep, lines


# ----------------------------------------------------------------------
# Rules and scoring
# ----------------------------------------------------------------------

def pick(p_home, dh, da, min_ev=0.0):
    """(home?, expected return) for the better side at these prices, or None."""
    evh, eva = p_home * dh - 1.0, (1.0 - p_home) * da - 1.0
    if max(evh, eva) <= min_ev:
        return None
    return (True, evh) if evh >= eva else (False, eva)


def bet_record(r, home):
    d = r["dh"] if home else r["da"]
    pc = r["fc"] if home else 1.0 - r["fc"]
    ret = 0.0 if r["y"] is None else (d - 1.0 if r["y"] == (1.0 if home else 0.0) else -1.0)
    moved = None if r["fc"] == r["fo"] else ((r["fc"] > r["fo"]) == home)
    return {"clv": pc * d - 1.0, "ret": ret, "moved": moved}


def summary(bets):
    n = len(bets)
    if not n:
        return "    0 bets"
    mv = [b["moved"] for b in bets if b["moved"] is not None]
    clv = sum(b["clv"] for b in bets) / n
    rets = [b["ret"] for b in bets]
    mu = sum(rets) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / max(1, n - 1))
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    cs = [b["clv"] for b in bets]
    csd = math.sqrt(sum((x - clv) ** 2 for x in cs) / max(1, n - 1))
    ct = clv / (csd / math.sqrt(n)) if csd else 0.0
    return (f"{n:>5} bets · moved our way {sum(mv) / max(1, len(mv)) * 100:5.1f}% · "
            f"value vs close {clv * 100:+5.1f}% (t = {ct:+.1f}) · actual return {mu * 100:+6.1f}% (t = {t:+.1f})")


def lean_bets(rows, blend_w, seasons, key="p"):
    out = defaultdict(list)
    for r in rows:
        if r["season"] not in seasons:
            continue
        bl = blend_w * r[key] + (1 - blend_w) * r["fo"]
        s = pick(bl, r["dh"], r["da"])
        if s:
            out[r["src"]].append(bet_record(r, s[0]))
    return out


def main():
    games = load()
    ats = last_ats(games)
    p_open, blend_w = model_probs(games, at_open=True)
    p_act, _ = model_probs(games, at_open=False)
    rows = build(games, p_open, ats)
    for r in rows:
        r["p_act"] = p_act[id(r["g"])]
    print(f"Games with opening + closing moneylines, 2014-2025: {len(rows)}")

    print("\n1. THE EARLIER CHECK, REDONE WITHOUT KNOWING THE STARTING QB "
          f"(site's lean: {int(blend_w * 100)}% model + market, bet at the open)")
    for label, key in (("actual starters (earlier, leaks)", "p_act"), ("as of opening day (honest)", "p")):
        by = lean_bets(rows, blend_w, DEV | TEST, key)
        print(f"  {label}")
        for s in sorted(by):
            print(f"    {s:<18}{summary(by[s])}")

    print("\n2. SCREEN ON 2014-2019 · what predicts the move from open to close?")
    keep, lines = screen(rows)
    print("\n".join(lines))
    print(f"  kept: {', '.join(keep) if keep else 'nothing'}")

    print("\n3. TEST 2020-2025 (refit each season on earlier seasons only) · bet at the open")
    move_bets, cur_bets = defaultdict(list), lean_bets(rows, blend_w, TEST)
    sse_model = sse_zero = 0.0
    coefs = {}
    if keep:
        for s in sorted(TEST):
            beta = fit([r for r in rows if r["season"] < s], keep)
            coefs[s] = beta
            for r in rows:
                if r["season"] != s:
                    continue
                pc = predict_close(beta, keep, r["fo"], r["f"])
                r["pc_hat"] = pc
                sse_model += (logit(pc) - logit(r["fc"])) ** 2
                sse_zero += (logit(r["fo"]) - logit(r["fc"])) ** 2
                sd = pick(pc, r["dh"], r["da"])
                if sd:
                    move_bets[r["src"]].append(bet_record(r, sd[0]))
        print(f"  share of the open-to-close move explained: {(1 - sse_model / sse_zero) * 100:.1f}% "
              f"(0% = no better than assuming the line won't move)")
        last = coefs[max(coefs)]
        print("  coefficients (fit through 2024): " + ", ".join(
            f"{k} {b:+.3f}" for k, b in zip(("intercept",) + tuple(keep), last)))
    for label, by in (("current lean rule", cur_bets), ("line-move rule", move_bets)):
        print(f"  {label}")
        alln = []
        for s in sorted(by):
            print(f"    {s:<18}{summary(by[s])}")
            alln += by[s]
        print(f"    {'all 2020-2025':<18}{summary(alln)}")

    if keep:
        beta = fit([r for r in rows if r["season"] in DEV | TEST], keep)
        SETTINGS.write_text(json.dumps({"features": keep, "coefs": beta,
                                        "fit_seasons": "2014-2025"}, indent=2), encoding="utf-8")
        print(f"\nSaved the fit on all seasons to {SETTINGS.relative_to(ROOT)} (used only if adopted).")


if __name__ == "__main__":
    sys.exit(main())
