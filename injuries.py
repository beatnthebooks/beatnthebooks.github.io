"""
injuries.py
===========
Does the official injury report predict results BEYOND the closing line?

Data (nflverse, data/nflverse/): injuries_<season>.csv (final pre-game report: Out /
Doubtful / Questionable) and snap_counts_<season>.csv (each player's share of snaps).
Snap counts start in 2013.

Feature: each listed player is worth his usual share of his team's snaps (average over
earlier games this season that he played; first game of a season -> last season's average).
Per team and game:
    off_out / def_out  = summed offensive / defensive snap share of players Out or Doubtful
    off_q / def_q      = the same for Questionable players
    qb_out             = 1 if a QB with >= 50% of offensive snaps is Out or Doubtful

Signals (side markets: positive = good for the HOME team; totals: positive = more points):
    inj_off   = away off_out - home off_out        inj_def = away def_out - home def_out
    inj_all   = inj_off + inj_def                   inj_q   = (away off_q + def_q) - (home off_q + def_q)
    inj_qb    = away qb_out - home qb_out
    tot_off   = -(home off_out + away off_out)      tot_def = home def_out + away def_out
    tot_net   = tot_def + tot_off

Protocol (fixed before running, same rule as edge_lab.py):
    DEV 2013-2018: keep a signal only if |z| >= 2 on top of the market's own price AND the
    sign agrees in both halves (2013-15, 2016-18).
    TEST 2019-2025, scored once, expanding-window refit, bets at the real closing price.

Usage:  py injuries.py
Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import edge_lab as L
from rift_real import run

ROOT = Path(__file__).resolve().parent
NV = ROOT / "data" / "nflverse"
SEASONS = range(2013, 2027)
DEV = set(range(2013, 2019))
HALVES = (set(range(2013, 2016)), set(range(2016, 2019)))
TEST = set(range(2019, 2026))
OUT = {"Out", "Doubtful"}
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}

SIDE_FEATS = ["inj_off", "inj_def", "inj_all", "inj_q", "inj_qb"]
TOT_FEATS = ["tot_off", "tot_def", "tot_net"]


def norm(name: str) -> str:
    n = re.sub(r"[.\-']", "", name.lower())
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def team(t: str) -> str:
    return FRANCHISE.get(t, t)


def snap_values():
    """{(season, week, team, name): (off_share, def_share)} = the player's usual share
    BEFORE that week, from games he played (earlier weeks; else last season)."""
    played = defaultdict(list)          # (season, team, name) -> [(week, off, def)]
    last_season = {}                    # (season, name) -> (off, def) season average
    for s in SEASONS:
        path = NV / f"snap_counts_{s}.csv"
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    off, dfn = float(r["offense_pct"] or 0), float(r["defense_pct"] or 0)
                except ValueError:
                    continue
                if off == 0 and dfn == 0:
                    continue
                played[(s, team(r["team"]), norm(r["player"]))].append((int(r["week"]), off, dfn))
    by_name = defaultdict(list)
    for (s, t, n), rows in played.items():
        by_name[(s, n)].extend(rows)
    for (s, n), rows in by_name.items():
        last_season[(s, n)] = (sum(r[1] for r in rows) / len(rows), sum(r[2] for r in rows) / len(rows))

    def value(season, week, t, name):
        n = norm(name)
        prior = [r for r in played.get((season, t, n), []) if r[0] < week]
        if prior:
            return (sum(r[1] for r in prior) / len(prior), sum(r[2] for r in prior) / len(prior))
        return last_season.get((season - 1, n), (0.0, 0.0))
    return value


def team_injuries(value):
    """{(season, week, team): {off_out, def_out, off_q, def_q, qb_out}}"""
    out = defaultdict(lambda: {"off_out": 0.0, "def_out": 0.0, "off_q": 0.0, "def_q": 0.0, "qb_out": 0})
    for s in SEASONS:
        path = NV / f"injuries_{s}.csv"
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                st = r["report_status"]
                if st not in OUT and st != "Questionable":
                    continue
                t, wk = team(r["team"]), int(r["week"])
                off, dfn = value(s, wk, t, r["full_name"])
                d = out[(s, wk, t)]
                if st in OUT:
                    d["off_out"] += off
                    d["def_out"] += dfn
                    if r["position"] == "QB" and off >= 0.5:
                        d["qb_out"] = 1
                else:
                    d["off_q"] += off
                    d["def_q"] += dfn
    return out


def add_features(rows, inj):
    zero = {"off_out": 0.0, "def_out": 0.0, "off_q": 0.0, "def_q": 0.0, "qb_out": 0}
    covered = 0
    for r in rows:
        g = r["g"]
        h = inj.get((g["season"], g["week"], g["home"]))
        a = inj.get((g["season"], g["week"], g["away"]))
        if g["season"] in SEASONS and (h or a):
            covered += 1
        h, a = h or zero, a or zero
        r["side"].update({
            "inj_off": a["off_out"] - h["off_out"],
            "inj_def": a["def_out"] - h["def_out"],
            "inj_all": (a["off_out"] + a["def_out"]) - (h["off_out"] + h["def_out"]),
            "inj_q": (a["off_q"] + a["def_q"]) - (h["off_q"] + h["def_q"]),
            "inj_qb": a["qb_out"] - h["qb_out"],
        })
        r["tot"].update({
            "tot_off": -(h["off_out"] + a["off_out"]),
            "tot_def": h["def_out"] + a["def_out"],
            "tot_net": (h["def_out"] + a["def_out"]) - (h["off_out"] + a["off_out"]),
        })
    return covered


def screen(rows, market, feats):
    _, ykey, grp, _ = L.MARKETS[market]
    data = L.market_rows(rows, market, DEV)
    out = []
    for f in feats:
        X = [L.design(r, market, [f]) for r in data]
        y = [r[ykey] for r in data]
        b, se = L.fit_logit(X, y)
        z = b[2] / se[2] if se[2] else 0.0
        signs = []
        for hs in HALVES:
            d2 = [r for r in data if r["season"] in hs]
            b2, _ = L.fit_logit([L.design(r, market, [f]) for r in d2], [r[ykey] for r in d2])
            signs.append(math.copysign(1, b2[2]))
        stable = signs[0] == signs[1]
        mean_abs = sum(abs(r[grp][f]) for r in data) / len(data)
        out.append({"feat": f, "coef": b[2], "z": z, "stable": stable, "mean_abs": mean_abs,
                    "selected": abs(z) >= 2.0 and stable})
    return out, len(data)


def main():
    games = L.load()
    params = json.loads(L.PARAMS.read_text(encoding="utf-8"))["params"]
    recs, _, _ = run(games, **params)
    sigma = L.fit_sigma(games, L.DEV["spread"])
    rows = L.build_rows(games, recs, sigma)
    inj = team_injuries(snap_values())
    covered = add_features(rows, inj)
    print(f"Team-weeks with an injury report: {len(inj)} · games covered 2013+: {covered}")

    # sanity: how much the report matters on average
    vals = [v["off_out"] + v["def_out"] for v in inj.values()]
    print(f"Average snap share listed Out/Doubtful per team-game: {sum(vals) / len(vals):.2f} "
          f"(1.00 = one full-time player) · QB out in {sum(v['qb_out'] for v in inj.values())} team-games")

    selected = {}
    for market, feats in (("ml", SIDE_FEATS), ("spread", SIDE_FEATS), ("total", TOT_FEATS)):
        res, n = screen(rows, market, feats)
        print(f"\n=== {market.upper()} · DEV 2013-2018 ({n} games) ===")
        print(f"  {'signal':<10}{'coef':>9}{'z':>7}  halves agree  avg |value|")
        for x in sorted(res, key=lambda d: -abs(d["z"])):
            print(f"  {x['feat']:<10}{x['coef']:>+9.3f}{x['z']:>+7.2f}  {'yes' if x['stable'] else 'no ':<12}"
                  f"  {x['mean_abs']:.2f}   {'<== SELECTED' if x['selected'] else ''}")
        selected[market] = [x["feat"] for x in res if x["selected"]]

    print("\nSelected on DEV:", {m: v or ["(none)"] for m, v in selected.items()})
    L.TEST = TEST
    L.FIRST_FIT = {"ml": 2013, "spread": 2013, "total": 2013}
    print("\n" + "=" * 78)
    print("OUT-OF-SAMPLE TEST 2019-2025 (expanding-window refit, real closing prices)")
    print("=" * 78)
    for market in L.MARKETS:
        for label, feats in (("market calibration only", []), ("+ selected injury signals", selected[market])):
            if label.startswith("+") and not feats:
                print(f"\n{market.upper()}: no injury signal passed the screen")
                continue
            res = L.test_market(rows, market, feats)
            print(f"\n{market.upper()}: {label} {feats if feats else ''}")
            print(f"  log loss  model {res['ll_model']:.5f}  vs market {res['ll_mkt']:.5f}"
                  f"  ({'model' if res['ll_model'] < res['ll_mkt'] else 'market'} better, {res['n']} games)")
            for thr in L.EV_THRESHOLDS:
                print(f"  EV > {thr * 100:.0f}%: {L.summarize(res['bets'][thr])}")


if __name__ == "__main__":
    main()
