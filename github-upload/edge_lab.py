"""
edge_lab.py
===========
Search for edges AGAINST the closing market, not just a better win model.

The Elo work showed a stand-alone model loses to the closing line. The right
question is narrower: given the market's own price, does anything known before
kickoff still predict the result? Each candidate is tested as a "market
residual":

    logit P(outcome) = b0 + b1 * logit(p_market) + b2 * feature

b2 = 0 means the market already prices that feature. Three markets:
moneyline (home wins), spread (home covers), total (over).

Protocol (decided before any test-season number was looked at):
  * DEV seasons  : moneyline 2006-2015, spread/total 2001-2015.
  * A feature is SELECTED only if, on DEV, |z| >= 2 for b2 AND b2 has the
    same sign in both halves of DEV.
  * TEST seasons : 2016-2025. Selected features are combined per market;
    each test season is predicted with coefficients fit on every earlier
    season only (expanding window). Bets at the real closing price.
  * Every feature is computed from information available before kickoff.

Usage:
    python3 edge_lab.py            # DEV screening only
    python3 edge_lab.py --test     # screening + the out-of-sample test

Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

from rift_real import FRANCHISE, am_to_dec, run

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "games.csv"
PARAMS = ROOT / "results" / "current_ratings.json"

DEV = {"ml": set(range(2006, 2016)), "spread": set(range(2001, 2016)),
       "total": set(range(2001, 2016))}
TEST = set(range(2016, 2026))
FIRST_FIT = {"ml": 2006, "spread": 2001, "total": 2001}
EV_THRESHOLDS = (0.0, 0.02, 0.04)
ND = NormalDist()

# Time zone of each home stadium (hours vs Eastern), by RAW team code
TZ = {**{t: 0 for t in ("ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND",
                        "JAX", "MIA", "NE", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS")},
      **{t: -1 for t in ("CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN", "STL")},
      "DEN": -2, "ARI": -2.5,
      **{t: -3 for t in ("LA", "LAC", "SD", "LV", "OAK", "SF", "SEA")}}
WARM = {"MIA", "TB", "JAX", "SD", "LAC", "LA", "ARI"}


def _f(x):
    return float(x) if x not in ("", None, "NA") else None


def logit(p):
    p = min(1 - 1e-9, max(1e-9, p))
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x)) if x > -500 else 0.0


def devig(a, b):
    """Two American prices -> fair probability of side a (multiplicative)."""
    qa, qb = 1 / am_to_dec(a), 1 / am_to_dec(b)
    return qa / (qa + qb)


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def load(path=DATA):
    import csv
    games = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            games.append({
                "season": int(r["season"]), "week": int(r["week"]),
                "type": r["game_type"], "date": r["gameday"],
                "time": r["gametime"] or "00:00",
                "home": FRANCHISE.get(r["home_team"], r["home_team"]),
                "away": FRANCHISE.get(r["away_team"], r["away_team"]),
                "rhome": r["home_team"], "raway": r["away_team"],
                "neutral": r["location"] == "Neutral",
                "hs": _f(r["home_score"]), "as": _f(r["away_score"]),
                "hrest": _f(r["home_rest"]) or 7.0, "arest": _f(r["away_rest"]) or 7.0,
                "hml": _f(r["home_moneyline"]), "aml": _f(r["away_moneyline"]),
                "spread": _f(r["spread_line"]),
                "hso": _f(r["home_spread_odds"]), "aso": _f(r["away_spread_odds"]),
                "tot": _f(r["total_line"]), "oo": _f(r["over_odds"]), "uo": _f(r["under_odds"]),
                "div": r["div_game"] == "1", "roof": r["roof"],
                "temp": _f(r["temp"]), "wind": _f(r["wind"]),
                "hqb": r["home_qb_id"] or None, "aqb": r["away_qb_id"] or None,
                "hqbn": r["home_qb_name"], "aqbn": r["away_qb_name"],
                "ref": r["referee"] or None, "sid": r["stadium_id"],
                "stadium": r["stadium"], "gid": r["game_id"],
            })
    games.sort(key=lambda g: (g["date"], g["time"]))
    return games


# ----------------------------------------------------------------------
# Small logistic regression (Newton's method)
# ----------------------------------------------------------------------

def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            raise ZeroDivisionError
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def _inverse(A):
    n = len(A)
    cols = [_solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def fit_logit(X, y, ridge=1e-3, iters=30):
    """Returns (coefs, standard errors). y may be fractional (ties = 0.5)."""
    k = len(X[0])
    beta = [0.0] * k
    H = None
    for _ in range(iters):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for x, t in zip(X, y):
            z = sum(b * v for b, v in zip(beta, x))
            p = sigmoid(z)
            w = p * (1 - p)
            for i in range(k):
                g[i] += (t - p) * x[i]
                xi_w = x[i] * w
                for j in range(i, k):
                    H[i][j] += xi_w * x[j]
        for i in range(k):
            for j in range(i):
                H[i][j] = H[j][i]
            if i:
                H[i][i] += ridge
                g[i] -= ridge * beta[i]
        step = _solve(H, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    cov = _inverse(H)
    return beta, [math.sqrt(max(cov[i][i], 0.0)) for i in range(k)]


# ----------------------------------------------------------------------
# Walk-forward features (everything known before kickoff)
# ----------------------------------------------------------------------

class TeamState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.n = 0
        self.pf = 0.0
        self.pa = 0.0
        self.ats = 0.0          # sum of (actual margin - expected margin)
        self.ou = 0.0           # sum of (game total - total line)
        self.last_ats = 0.0
        self.last_margin = 0.0
        self.last_ou = 0.0


def build_rows(games, elo_recs, sigma):
    """One dict per game with market probabilities, outcomes and features."""
    state = defaultdict(TeamState)
    ref_ou = defaultdict(lambda: [0.0, 0])      # referee: sum(total - line), n
    league = {"pts": [0.0, 0], "line": [0.0, 0]}
    roof_hist = defaultdict(lambda: defaultdict(int))  # raw team -> roof -> count
    season = None
    rows = []
    elo_by_id = {id(r["g"]): r for r in elo_recs}

    for g in games:
        if g["season"] != season:
            season = g["season"]
            for st in state.values():
                st.reset()
        h, a = state[g["home"]], state[g["away"]]
        e = elo_by_id[id(g)]
        row = {"g": g, "season": g["season"], "played": g["hs"] is not None}

        # --- market probabilities (home side / over) ---
        row["p_ml"] = devig(g["hml"], g["aml"]) if g["hml"] and g["aml"] else None
        if g["spread"] is not None:
            row["p_sp_win"] = ND.cdf(g["spread"] / sigma)        # spread-implied win prob
            row["p_cover"] = devig(g["hso"], g["aso"]) if g["hso"] and g["aso"] else 0.5
            row["sp_odds"] = (g["hso"] or -110, g["aso"] or -110)
        if g["tot"] is not None:
            row["p_over"] = devig(g["oo"], g["uo"]) if g["oo"] and g["uo"] else 0.5
            row["tot_odds"] = (g["oo"] or -110, g["uo"] or -110)

        # --- outcomes ---
        if row["played"]:
            res = g["hs"] - g["as"]
            row["y_ml"] = 1.0 if res > 0 else 0.0 if res < 0 else 0.5
            if g["spread"] is not None:
                row["y_spread"] = None if res == g["spread"] else float(res > g["spread"])
            if g["tot"] is not None:
                tt = g["hs"] + g["as"]
                row["y_total"] = None if tt == g["tot"] else float(tt > g["tot"])

        # --- side features (positive = good for HOME) ---
        f = {}
        p_elo = e["p"]
        base_win = row["p_ml"] if row["p_ml"] is not None else row.get("p_sp_win")
        f["elo_gap"] = logit(p_elo) - logit(base_win) if base_win else 0.0
        f["ml_vs_spread"] = (logit(row["p_ml"]) - logit(row["p_sp_win"])
                             if row["p_ml"] is not None and g["spread"] is not None else 0.0)
        f["rest_diff"] = max(-7.0, min(7.0, g["hrest"] - g["arest"]))
        f["short_week"] = float(g["arest"] <= 4) - float(g["hrest"] <= 4)
        f["off_bye"] = float(g["hrest"] >= 13) - float(g["arest"] >= 13)
        tzh, tza = TZ.get(g["rhome"], 0), TZ.get(g["raway"], 0)
        f["tz_travel"] = 0.0 if g["neutral"] else abs(tzh - tza)
        early = g["time"] <= "13:05"
        f["west_early"] = float(not g["neutral"] and early and tza <= -2.5 and tzh >= -1)
        f["primetime_home"] = float(g["time"] >= "19:00")
        spread = g["spread"] or 0.0
        f["home_dog"] = float(spread < 0)
        f["div_dog"] = (float(spread < 0) - float(spread > 0)) if g["div"] else 0.0
        f["big_dog"] = float(spread <= -10) - float(spread >= 10)
        f["last_ats"] = max(-21, min(21, h.last_ats)) - max(-21, min(21, a.last_ats))
        f["last_margin"] = max(-28, min(28, h.last_margin)) - max(-28, min(28, a.last_margin))
        f["season_ats"] = h.ats / (h.n + 3) - a.ats / (a.n + 3)
        f["early_elo"] = f["elo_gap"] * float(g["week"] <= 4)
        f["qb_change"] = float(e["aflag"]) - float(e["hflag"])
        f["neutral"] = float(g["neutral"])
        f["playoff"] = float(g["type"] != "REG")
        lp = league["pts"][0] / league["pts"][1] if league["pts"][1] else 21.0
        k = 4.0
        def shrunk(st, attr):
            return (getattr(st, attr) + k * lp) / (st.n + k)
        exp_h = (shrunk(h, "pf") + shrunk(a, "pa")) / 2
        exp_a = (shrunk(a, "pf") + shrunk(h, "pa")) / 2
        f["pts_gap"] = (exp_h - exp_a) - (spread - (0 if g["neutral"] else 2.0)) if g["spread"] is not None else 0.0
        hdome = max(roof_hist[g["raway"]].items(), key=lambda kv: kv[1])[0] in ("dome", "closed") \
            if roof_hist[g["raway"]] else False
        cold = g["roof"] == "outdoors" and g["temp"] is not None and g["temp"] <= 35
        f["cold_vs_warm"] = float(cold and (g["raway"] in WARM or hdome))
        row["side"] = f

        # --- total features (positive = good for OVER) ---
        t = {}
        outdoors = g["roof"] in ("outdoors", "open")
        wind = g["wind"] if (outdoors and g["wind"] is not None) else 0.0
        t["wind"] = min(wind, 30.0)
        t["wind_15"] = float(wind >= 15)
        t["cold"] = float(outdoors and g["temp"] is not None and g["temp"] <= 32)
        t["dome"] = float(g["roof"] in ("dome", "closed"))
        ll = league["line"][0] / league["line"][1] if league["line"][1] else 40.0
        t["line_level"] = (g["tot"] - ll) if g["tot"] is not None else 0.0
        t["div"] = float(g["div"])
        t["primetime"] = float(g["time"] >= "19:00")
        t["playoff"] = float(g["type"] != "REG")
        t["late_season"] = float(g["week"] >= 13 and g["type"] == "REG")
        ro = ref_ou[g["ref"]] if g["ref"] else [0.0, 0]
        t["ref_ou"] = ro[0] / (ro[1] + 30)
        t["team_ou"] = (h.ou / (h.n + 3) + a.ou / (a.n + 3)) / 2
        t["last_ou"] = (max(-21, min(21, h.last_ou)) + max(-21, min(21, a.last_ou))) / 2
        t["pts_model"] = (exp_h + exp_a - g["tot"]) if g["tot"] is not None else 0.0
        t["abs_spread"] = abs(spread)
        t["any_backup_qb"] = float(e["hflag"] or e["aflag"])
        t["short_week"] = float(g["hrest"] <= 4 and g["arest"] <= 4)
        row["tot"] = t
        rows.append(row)

        # --- update state with the result (after the prediction) ---
        if g["tot"] is not None:
            league["line"][0] += g["tot"]; league["line"][1] += 1
        roof_hist[g["rhome"]][g["roof"]] += 1
        if not row["played"]:
            continue
        res = g["hs"] - g["as"]
        league["pts"][0] += g["hs"] + g["as"]; league["pts"][1] += 2
        exp_margin = g["spread"] if g["spread"] is not None else 0.0
        for st, pf, pa, sign in ((h, g["hs"], g["as"], 1), (a, g["as"], g["hs"], -1)):
            st.n += 1
            st.pf += pf
            st.pa += pa
            st.last_margin = pf - pa
            st.last_ats = (pf - pa) - sign * exp_margin
            st.ats += st.last_ats
            if g["tot"] is not None:
                st.last_ou = pf + pa - g["tot"]
                st.ou += st.last_ou
        if g["ref"] and g["tot"] is not None:
            ref_ou[g["ref"]][0] += g["hs"] + g["as"] - g["tot"]
            ref_ou[g["ref"]][1] += 1
    return rows


def fit_sigma(games, seasons):
    """Std-dev of the margin around the spread, fit by log loss on DEV only."""
    data = [(g["spread"], 1.0 if g["hs"] > g["as"] else 0.0)
            for g in games if g["season"] in seasons and g["hs"] is not None
            and g["spread"] is not None and g["hs"] != g["as"]]
    best = None
    for s10 in range(100, 181):
        s = s10 / 10
        ll = -sum(math.log(max(1e-12, ND.cdf(sp / s) if y else 1 - ND.cdf(sp / s)))
                  for sp, y in data)
        if best is None or ll < best[0]:
            best = (ll, s)
    return best[1]


# ----------------------------------------------------------------------
# Market plumbing
# ----------------------------------------------------------------------

MARKETS = {
    # name: (base-prob key, outcome key, feature group, odds getter)
    "ml": ("p_ml", "y_ml", "side", lambda r: (r["g"]["hml"], r["g"]["aml"])),
    "spread": ("p_cover", "y_spread", "side", lambda r: r["sp_odds"]),
    "total": ("p_over", "y_total", "tot", lambda r: r["tot_odds"]),
}


def market_rows(rows, market, seasons):
    pkey, ykey, _, _ = MARKETS[market]
    return [r for r in rows if r["season"] in seasons and r["played"]
            and r.get(pkey) is not None and r.get(ykey) is not None]


def design(r, market, feats):
    pkey, _, grp, _ = MARKETS[market]
    return [1.0, logit(r[pkey])] + [r[grp][f] for f in feats]


def log_loss(ps, ys):
    return -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(ps, ys)) / len(ps)


# ----------------------------------------------------------------------
# Screening on DEV
# ----------------------------------------------------------------------

def screen(rows, market):
    _, ykey, grp, _ = MARKETS[market]
    dev = sorted(DEV[market])
    half = len(dev) // 2
    halves = (set(dev[:half]), set(dev[half:]))
    data = market_rows(rows, market, DEV[market])
    feats = list(data[0][grp].keys())
    out = []
    for f in feats:
        vals = [r[grp][f] for r in data]
        if max(vals) == min(vals):
            continue
        X = [design(r, market, [f]) for r in data]
        y = [r[ykey] for r in data]
        b, se = fit_logit(X, y)
        z = b[2] / se[2] if se[2] else 0.0
        signs = []
        for hs in halves:
            d2 = [r for r in data if r["season"] in hs]
            b2, _ = fit_logit([design(r, market, [f]) for r in d2], [r[ykey] for r in d2])
            signs.append(math.copysign(1, b2[2]))
        stable = signs[0] == signs[1]
        out.append({"feat": f, "coef": b[2], "z": z, "stable": stable,
                    "selected": abs(z) >= 2.0 and stable})
    # calibration of the market itself (favorite-longshot / home bias)
    Xb = [design(r, market, []) for r in data]
    yb = [r[ykey] for r in data]
    bb, sb = fit_logit(Xb, yb)
    return out, (bb, sb, len(data))


# ----------------------------------------------------------------------
# Out-of-sample test
# ----------------------------------------------------------------------

def settle(p_side, dec, y_side):
    return dec - 1.0 if y_side == 1.0 else -1.0 if y_side == 0.0 else 0.0


def test_market(rows, market, feats):
    pkey, ykey, _, odds = MARKETS[market]
    preds = []                             # (row, p_model, p_market)
    for s in sorted(TEST):
        train = market_rows(rows, market, set(range(FIRST_FIT[market], s)))
        b, _ = fit_logit([design(r, market, feats) for r in train], [r[ykey] for r in train])
        for r in market_rows(rows, market, {s}):
            x = design(r, market, feats)
            preds.append((r, sigmoid(sum(bi * xi for bi, xi in zip(b, x))), r[pkey]))
    ys = [r[ykey] for r, _, _ in preds]
    ll_model = log_loss([p for _, p, _ in preds], ys)
    ll_mkt = log_loss([m for _, _, m in preds], ys)

    bets = {thr: [] for thr in EV_THRESHOLDS}
    for r, p, _ in preds:
        oh, oa = odds(r)
        dh, da = am_to_dec(oh), am_to_dec(oa)
        evh, eva = p * dh - 1, (1 - p) * da - 1
        y = r[ykey]
        for thr in EV_THRESHOLDS:
            if max(evh, eva) <= thr:
                continue
            ret = settle(p, dh, y) if evh >= eva else settle(1 - p, da, 1 - y if y != 0.5 else 0.5)
            bets[thr].append((r["season"], ret))
    return {"n": len(preds), "ll_model": ll_model, "ll_mkt": ll_mkt, "bets": bets}


def summarize(bets):
    n = len(bets)
    if not n:
        return "no bets"
    rets = [x for _, x in bets]
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / max(1, n - 1))
    t = mean / (sd / math.sqrt(n)) if sd else 0.0
    by = defaultdict(float)
    for s, x in bets:
        by[s] += x
    pos = sum(1 for v in by.values() if v > 0)
    return f"{n:>5} bets  ROI {mean * 100:+6.2f}%  (t = {t:+.2f})  winning seasons {pos}/{len(by)}"


def blind_baselines(rows):
    out = []
    for market, sides in (("spread", ("home", "away")), ("total", ("over", "under"))):
        data = market_rows(rows, market, TEST)
        _, ykey, _, odds = MARKETS[market]
        for i, side in enumerate(sides):
            rets = []
            for r in data:
                o = odds(r)[i]
                y = r[ykey] if i == 0 else 1 - r[ykey]
                rets.append(settle(None, am_to_dec(o), y))
            out.append(f"  every {side:<6} {market:<7} {len(rets):>5} bets  "
                       f"ROI {sum(rets) / len(rets) * 100:+6.2f}%")
    return out


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    games = load()
    params = json.loads(PARAMS.read_text(encoding="utf-8"))["params"]
    elo_recs, _, _ = run(games, **params)
    sigma = fit_sigma(games, DEV["spread"])
    rows = build_rows(games, elo_recs, sigma)
    print(f"{len(games)} games. Margin std-dev around the spread (fit on DEV): {sigma}")

    selected = {}
    for market in MARKETS:
        res, (bb, sb, n) = screen(rows, market)
        dev = sorted(DEV[market])
        print(f"\n=== {market.upper()}  DEV {dev[0]}-{dev[-1]}  ({n} games) ===")
        print(f"  market calibration: intercept {bb[0]:+.3f} (z {bb[0] / sb[0]:+.1f})   "
              f"slope on logit(p) {bb[1]:.3f} (z vs 1: {(bb[1] - 1) / sb[1]:+.1f})")
        print(f"  {'feature':<16}{'coef':>9}{'z':>7}  halves agree  selected")
        for x in sorted(res, key=lambda d: -abs(d["z"])):
            print(f"  {x['feat']:<16}{x['coef']:>+9.4f}{x['z']:>+7.2f}  "
                  f"{'yes' if x['stable'] else 'no ':<12}  {'<== SELECTED' if x['selected'] else ''}")
        selected[market] = [x["feat"] for x in res if x["selected"]]

    print("\nSelected on DEV:", {m: v or ["(none)"] for m, v in selected.items()})
    if "--test" not in sys.argv:
        print("\nDEV only. Run with --test for the one-time out-of-sample check.")
        return

    print("\n" + "=" * 78)
    print("OUT-OF-SAMPLE TEST 2016-2025 (expanding-window refit, real closing prices)")
    print("=" * 78)
    for market in MARKETS:
        for label, feats in (("market calibration only", []),
                             ("+ selected features", selected[market])):
            if label.startswith("+") and not feats:
                continue
            res = test_market(rows, market, feats)
            print(f"\n{market.upper()}: {label} {feats if feats else ''}")
            print(f"  log loss  model {res['ll_model']:.5f}  vs market {res['ll_mkt']:.5f}"
                  f"  ({'model' if res['ll_model'] < res['ll_mkt'] else 'market'} better, {res['n']} games)")
            for thr in EV_THRESHOLDS:
                print(f"  EV > {thr * 100:.0f}%: {summarize(res['bets'][thr])}")
    print("\nBlind baselines, 2016-2025 at closing prices:")
    print("\n".join(blind_baselines(rows)))


if __name__ == "__main__":
    main()
