"""
rift_real.py
============
Backtest the Elo model on REAL NFL history (nflverse games.csv) against the
actual closing moneylines, then print current team ratings and the model's
read on any games that haven't been played yet.

Usage:   python3 rift_real.py games.csv

How it stays honest (no peeking):
  * Ratings run continuously from 1999. Each new season pulls every team
    part of the way back toward 1500.
  * Every prediction is made BEFORE that game's result is used.
  * Parameters and the market-blend weight are chosen on 2006-2015 (the
    first decade with closing moneylines). 2016-2025 is then scored once,
    out-of-sample. Nothing from the test seasons influences any choice.
  * ROI is measured at the real closing prices, real vig included.

Features tested (each one has to earn its place on the training seasons):
  * home field, fixed or adaptive (follows the league's recent home win %)
  * season-to-season regression toward the mean
  * margin-of-victory multiplier
  * rest days (byes, short weeks)
  * backup-QB flag: penalize a team whose starter isn't its usual starter
    this season (the single biggest thing plain Elo misses)

Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA"}   # relocations -> current code
TRAIN = set(range(2006, 2016))
TEST = set(range(2016, 2026))

TEAM_NAME = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LA": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def _f(x):
    return float(x) if x not in ("", None, "NA") else None


def load(path):
    games = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            games.append({
                "season": int(r["season"]), "week": int(r["week"]),
                "type": r["game_type"], "date": r["gameday"],
                "time": r["gametime"] or "00:00",
                "home": FRANCHISE.get(r["home_team"], r["home_team"]),
                "away": FRANCHISE.get(r["away_team"], r["away_team"]),
                "neutral": r["location"] == "Neutral",
                "hs": _f(r["home_score"]), "as": _f(r["away_score"]),
                "hrest": _f(r["home_rest"]) or 7.0, "arest": _f(r["away_rest"]) or 7.0,
                "hml": _f(r["home_moneyline"]), "aml": _f(r["away_moneyline"]),
                "hqb": r["home_qb_id"] or None, "aqb": r["away_qb_id"] or None,
                "hqbn": r["home_qb_name"], "aqbn": r["away_qb_name"],
            })
    games.sort(key=lambda g: (g["date"], g["time"]))
    return games


def am_to_dec(a):
    return 1.0 + a / 100.0 if a > 0 else 1.0 + 100.0 / abs(a)


def market_fair(g):
    """De-vigged (multiplicative) closing probability that the HOME team wins."""
    if g["hml"] is None or g["aml"] is None:
        return None
    qh, qa = 1.0 / am_to_dec(g["hml"]), 1.0 / am_to_dec(g["aml"])
    return qh / (qh + qa)


def outcome(g):
    if g["hs"] > g["as"]:
        return 1.0
    if g["hs"] < g["as"]:
        return 0.0
    return 0.5


# ----------------------------------------------------------------------
# The model: walk-forward Elo
# ----------------------------------------------------------------------

def _qb_flag(hist, team, qb):
    """1 if this team's starter isn't its most common starter so far this season."""
    if not qb:
        return 0
    h = hist.get(team)
    if not h:
        return 0
    usual = Counter(h).most_common(1)[0][0]
    return 1 if qb != usual else 0


def run(games, k=20.0, hfa=55.0, hfa_mode="fixed", regress=1 / 3, mov=True,
        rest_pts=0.0, qb_pen=0.0):
    """Predict every game before learning from it. Returns (records, ratings, info)."""
    R = defaultdict(lambda: 1500.0)
    season = None
    qb_hist = {}
    home_rates = deque(maxlen=3)
    s_home = [0.0, 0]
    cur_hfa = hfa
    recs = []
    for g in games:
        if g["season"] != season:
            if season is not None:
                if s_home[1]:
                    home_rates.append(s_home[0] / s_home[1])
                for t in list(R):
                    R[t] = 1500.0 + (R[t] - 1500.0) * (1.0 - regress)
            season = g["season"]
            s_home = [0.0, 0]
            qb_hist = {}
            if hfa_mode == "adaptive" and home_rates:
                ph = sum(home_rates) / len(home_rates)
                cur_hfa = 400.0 * math.log10(ph / (1.0 - ph))
            else:
                cur_hfa = hfa

        h, a = g["home"], g["away"]
        hflag = _qb_flag(qb_hist, h, g["hqb"])
        aflag = _qb_flag(qb_hist, a, g["aqb"])
        adj = 0.0 if g["neutral"] else cur_hfa
        adj += max(-35.0, min(35.0, rest_pts * (g["hrest"] - g["arest"])))
        adj += qb_pen * (aflag - hflag)
        diff = R[h] + adj - R[a]
        p = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        recs.append({"g": g, "p": p, "hflag": hflag, "aflag": aflag,
                     "adj": adj, "hfa": cur_hfa, "rh": R[h], "ra": R[a]})

        if g["hs"] is None:            # not played yet: predict only
            continue
        act = outcome(g)
        if not g["neutral"]:
            s_home[0] += act
            s_home[1] += 1
        mult = 1.0
        margin = abs(g["hs"] - g["as"])
        if mov and margin > 0:
            wd = diff if act == 1.0 else -diff
            mult = math.log(margin + 1.0) * (2.2 / (wd * 0.001 + 2.2))
        d = k * mult * (act - p)
        R[h] += d
        R[a] -= d
        for t, q in ((h, g["hqb"]), (a, g["aqb"])):
            if q:
                qb_hist.setdefault(t, deque(maxlen=6)).append(q)
    return recs, R, {"hfa_now": cur_hfa}


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

def collect(recs, seasons, blend_w=None):
    """Played games in `seasons` that have a closing line."""
    P, M, O, G = [], [], [], []
    for r in recs:
        g = r["g"]
        if g["season"] not in seasons or g["hs"] is None:
            continue
        mf = market_fair(g)
        if mf is None:
            continue
        p = r["p"] if blend_w is None else blend_w * r["p"] + (1 - blend_w) * mf
        P.append(p); M.append(mf); O.append(outcome(g)); G.append(g)
    return P, M, O, G


def _clip(p):
    return min(1 - 1e-12, max(1e-12, p))


def log_loss(P, O):
    return -sum(o * math.log(_clip(p)) + (1 - o) * math.log(1 - _clip(p))
                for p, o in zip(P, O)) / len(P)


def brier(P, O):
    return sum((p - o) ** 2 for p, o in zip(P, O)) / len(P)


def accuracy(P, O):
    rows = [(p, o) for p, o in zip(P, O) if o != 0.5]
    return sum(1 for p, o in rows if (p >= 0.5) == (o == 1.0)) / len(rows)


def roi(P, G, O, thr=0.0):
    """Bet the better side whenever its EV at the CLOSING price clears thr. 1u flat."""
    bets, units = 0, 0.0
    for p, g, o in zip(P, G, O):
        dh, da = am_to_dec(g["hml"]), am_to_dec(g["aml"])
        evh, eva = p * dh - 1.0, (1.0 - p) * da - 1.0
        if max(evh, eva) <= thr:
            continue
        bets += 1
        if o == 0.5:                     # tie = push on a moneyline
            continue
        if evh >= eva:
            units += (dh - 1.0) if o == 1.0 else -1.0
        else:
            units += (da - 1.0) if o == 0.0 else -1.0
    return bets, units, (units / bets if bets else 0.0)


def best_blend(P, M, O, step=0.02):
    best = (0.0, 1e9)
    w = 0.0
    while w <= 1.0 + 1e-9:
        ll = log_loss([w * p + (1 - w) * m for p, m in zip(P, M)], O)
        if ll < best[1]:
            best = (round(w, 2), ll)
        w += step
    return best


def train_loss(games, **params):
    recs, _, _ = run(games, **params)
    P, _, O, _ = collect(recs, TRAIN)
    return log_loss(P, O)


# ----------------------------------------------------------------------
# Tuning (training seasons only)
# ----------------------------------------------------------------------

def tune(games):
    best = None
    for k in (15, 20, 25, 30):
        for hm, h in (("fixed", 40), ("fixed", 55), ("fixed", 65), ("adaptive", 55)):
            for reg in (0.25, 1 / 3, 0.5):
                for mv in (True, False):
                    p = dict(k=k, hfa=h, hfa_mode=hm, regress=reg, mov=mv)
                    ll = train_loss(games, **p)
                    if best is None or ll < best[0]:
                        best = (ll, p)
    core = best[1]
    best_rest = min(((train_loss(games, **core, rest_pts=r), r)
                     for r in (0, 2, 4, 6)), key=lambda x: x[0])
    best_qb = min(((train_loss(games, **core, qb_pen=q), q)
                   for q in (0, 25, 50, 75, 100, 150)), key=lambda x: x[0])
    return core, best_rest[1], best_qb[1]


def score_row(label, P, O, G):
    b0, u0, r0 = roi(P, G, O, 0.0)
    b3, u3, r3 = roi(P, G, O, 0.03)
    return (f"  {label:<26}{log_loss(P, O):>8.4f}{brier(P, O):>8.4f}"
            f"{accuracy(P, O) * 100:>7.1f}%{r0 * 100:>+8.1f}% ({b0:>4})"
            f"{r3 * 100:>+8.1f}% ({b3:>4})")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main(path):
    games = load(path)
    played = sum(1 for g in games if g["hs"] is not None)
    print(f"Loaded {len(games)} games ({played} played), "
          f"{games[0]['season']}-{games[-1]['season']}.")

    print("\nTuning on 2006-2015 only ...")
    core, rest_pts, qb_pen = tune(games)
    print(f"  core: K={core['k']}  home field={core['hfa_mode']}"
          f"{'' if core['hfa_mode'] == 'adaptive' else ' ' + str(core['hfa'])}"
          f"  regression={core['regress']:.2f}  MOV={core['mov']}")
    print(f"  rest: {rest_pts} Elo/day    backup-QB penalty: {qb_pen} Elo")

    variants = [
        ("Elo, core only", dict(core)),
        ("+ rest", dict(core, rest_pts=rest_pts)),
        ("+ backup-QB flag", dict(core, qb_pen=qb_pen)),
        ("+ rest + QB  (final)", dict(core, rest_pts=rest_pts, qb_pen=qb_pen)),
    ]
    final_params = variants[-1][1]

    # Blend weight chosen on TRAIN seasons only
    recs_final, ratings, info = run(games, **final_params)
    Ptr, Mtr, Otr, _ = collect(recs_final, TRAIN)
    w, _ = best_blend(Ptr, Mtr, Otr)

    head = (f"  {'':<26}{'LogLoss':>8}{'Brier':>8}{'Acc':>8}"
            f"{'ROI EV>0':>15}{'ROI EV>3%':>15}")
    print("\nOUT-OF-SAMPLE TEST, 2016-2025  (closing moneylines, real vig)")
    print("=" * 86)
    print(head)
    for label, params in variants:
        recs, _, _ = run(games, **params)
        P, M, O, G = collect(recs, TEST)
        print(score_row(label, P, O, G))
    P, M, O, G = collect(recs_final, TEST)
    print(score_row(f"blend (w={w} on model)", [w * p + (1 - w) * m for p, m in zip(P, M)], O, G))
    print(f"  {'closing market':<26}{log_loss(M, O):>8.4f}{brier(M, O):>8.4f}"
          f"{accuracy(M, O) * 100:>7.1f}%{'(the benchmark)':>23}")
    print(f"  {'coin flip':<26}{0.6931:>8.4f}{0.25:>8.4f}")
    print(f"  games scored: {len(P)}")

    # Season by season, final model vs market
    print("\nBY SEASON (final model vs closing market, log loss; lower wins)")
    for s in sorted(TEST):
        Ps, Ms, Os, Gs = collect(recs_final, {s})
        flag = "model" if log_loss(Ps, Os) < log_loss(Ms, Os) else "market"
        print(f"  {s}: model {log_loss(Ps, Os):.4f}  market {log_loss(Ms, Os):.4f}  -> {flag}")

    # 2026 so far
    P26, M26, O26, G26 = collect(recs_final, {2026})
    if P26:
        b, u, r = roi(P26, G26, O26, 0.0)
        print(f"\n2026 SO FAR ({len(P26)} games): model logloss {log_loss(P26, O26):.4f}"
              f"  market {log_loss(M26, O26):.4f}  ROI EV>0 {r * 100:+.1f}% ({b} bets)")

    # Current ratings
    print("\nCURRENT RATINGS (after every completed game)")
    ranked = sorted(ratings.items(), key=lambda kv: -kv[1])
    for i, (t, v) in enumerate(ranked, 1):
        print(f"  {i:>2}. {TEAM_NAME.get(t, t):<11} {v:7.1f}")
    print(f"  home-field now: {info['hfa_now']:.1f} Elo")

    # Upcoming games
    upcoming = [r for r in recs_final if r["g"]["hs"] is None and r["g"]["hml"] is not None
                and r["g"]["season"] == games[-1]["season"]]
    upcoming = [r for r in upcoming if r["g"]["date"] <= (upcoming[0]["g"]["date"][:8] + "31")] if upcoming else []
    if upcoming:
        print("\nNOT YET PLAYED (model vs closing line)")
        for r in upcoming[:16]:
            g = r["g"]
            mf = market_fair(g)
            bl = w * r["p"] + (1 - w) * mf
            flags = []
            if r["hflag"]:
                flags.append(f"{g['home']} QB {g['hqbn']} not usual starter")
            if r["aflag"]:
                flags.append(f"{g['away']} QB {g['aqbn']} not usual starter")
            print(f"  {g['date']} {g['time']}  {g['away']:>3} @ {g['home']:<3}  "
                  f"model {r['p'] * 100:5.1f}%  market {mf * 100:5.1f}%  "
                  f"blend {bl * 100:5.1f}%  (home)  {'; '.join(flags)}")

    out = {"params": final_params, "blend_w": w, "hfa_now": info["hfa_now"],
           "ratings": {TEAM_NAME.get(t, t): round(v, 1) for t, v in ratings.items()}}
    res = Path(__file__).resolve().parent / "results"
    dest = res / "current_ratings.json" if res.is_dir() else Path("current_ratings.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nWrote {dest.name} to {dest.parent.name}/" if res.is_dir() else f"\nWrote {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "games.csv")
