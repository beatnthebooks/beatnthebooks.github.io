"""
rift_backtest.py
================
The piece that makes "better" mean something: a walk-forward backtest that
scores the model out-of-sample and compares it to the market.

A model is only better if it's *measurably* better, so this harness reports:
  * Brier score and log loss   -- probabilistic accuracy (lower = better)
  * accuracy                   -- did the favorite side hit
  * calibration                -- when you say 70%, does it happen ~70%?
  * ROI vs the vigged market   -- the only number that pays rent

It also AUTO-TUNES the model (grid search on K and home-field) and finds the
market-blend weight that actually helps on the data you give it.

Run it as-is and it builds a synthetic season with a known truth, so you can
watch the harness recover signal and — the honest part — watch a sharp market
stay unbeatable while a soft market gets beaten. Point it at real data and the
same report tells you where you really stand.

No third-party packages; standard library only.
"""

from __future__ import annotations

import math
import random

from rift_model import EloModel, blend_probs


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------

def _clip(p, eps=1e-12):
    return min(1.0 - eps, max(eps, p))


def brier(preds, outs):
    return sum((p - o) ** 2 for p, o in zip(preds, outs)) / len(preds)


def log_loss(preds, outs):
    return -sum(o * math.log(_clip(p)) + (1 - o) * math.log(1 - _clip(p))
                for p, o in zip(preds, outs)) / len(preds)


def accuracy(preds, outs):
    hit = sum(1 for p, o in zip(preds, outs)
              if (p >= 0.5) == (o >= 0.5))
    return hit / len(preds)


def metrics(preds, outs, label):
    return {"label": label, "n": len(preds), "brier": brier(preds, outs),
            "logloss": log_loss(preds, outs), "acc": accuracy(preds, outs)}


def calibration(preds, outs, bins=5):
    table = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, p in enumerate(preds)
               if p >= lo and (p < hi or (i == bins - 1 and p <= hi))]
        if not idx:
            continue
        table.append((lo, hi, len(idx),
                      sum(preds[j] for j in idx) / len(idx),
                      sum(outs[j] for j in idx) / len(idx)))
    return table


# ----------------------------------------------------------------------
# Walk-forward evaluation (no leakage: predict, THEN learn)
# ----------------------------------------------------------------------

def walk_forward(games, k=20.0, home_adv=55.0, use_mov=True):
    """
    games: ordered list of dicts with home, away, home_score, away_score,
           and optional neutral / home_rest / away_rest.
    Returns (rows, trained_model). Each row: i, model (out-of-sample prob
    for the home team), out (1 home win, 0 away win, 0.5 tie).
    """
    m = EloModel(k=k, home_adv=home_adv, use_mov=use_mov)
    rows = []
    for i, g in enumerate(games):
        mp = m.win_prob(g["home"], g["away"], g.get("neutral", False),
                        g.get("home_rest"), g.get("away_rest"))
        hs, as_ = g["home_score"], g["away_score"]
        out = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
        rows.append({"i": i, "model": mp, "out": out})
        m.update(g["home"], g["away"], hs, as_, g.get("neutral", False),
                 g.get("home_rest"), g.get("away_rest"))
    return rows, m


def auto_tune(games, ks=(10, 15, 20, 25, 30, 40),
              hfas=(25, 40, 55, 70, 85), movs=(True, False), warmup=48):
    """Grid-search K / home-field / MOV by out-of-sample log loss."""
    best = None
    for k in ks:
        for h in hfas:
            for mv in movs:
                rows, _ = walk_forward(games, k=k, home_adv=h, use_mov=mv)
                ev = [r for r in rows if r["i"] >= warmup]
                ll = log_loss([r["model"] for r in ev], [r["out"] for r in ev])
                if best is None or ll < best["logloss"]:
                    best = {"k": k, "home_adv": h, "use_mov": mv, "logloss": ll}
    return best


def best_blend_weight(model_p, market_p, outs, step=0.05):
    """Weight on the model (vs market) that minimizes log loss."""
    best = (0.0, 1e9)
    w = 0.0
    while w <= 1.0 + 1e-9:
        preds = [blend_probs(mp, kp, w) for mp, kp in zip(model_p, market_p)]
        ll = log_loss(preds, outs)
        if ll < best[1]:
            best = (round(w, 2), ll)
        w += step
    return best


# ----------------------------------------------------------------------
# ROI: bet every +EV side against the vigged market, flat stakes
# ----------------------------------------------------------------------

def roi_sim(probs, market_fair, outs, vig=0.045, edge_threshold=0.0):
    """
    probs        : your probability the HOME team wins, per game
    market_fair  : the market's fair HOME prob (the book builds its price on this)
    Returns bets, units won/lost, and ROI per unit staked.
    """
    pnl = 0.0
    bets = 0
    over = 1.0 + vig
    for ph, fair_h, out in zip(probs, market_fair, outs):
        off_h, off_a = fair_h * over, (1 - fair_h) * over     # offered implied (vig in)
        dec_h, dec_a = 1.0 / off_h, 1.0 / off_a
        pa = 1 - ph
        ev_h, ev_a = ph * dec_h - 1, pa * dec_a - 1
        if max(ev_h, ev_a) <= edge_threshold:
            continue
        bets += 1
        if ev_h >= ev_a:
            pnl += (dec_h - 1) if out >= 0.5 else -1
        else:
            pnl += (dec_a - 1) if out < 0.5 else -1
    return {"bets": bets, "units": pnl, "roi": (pnl / bets) if bets else 0.0}


# ----------------------------------------------------------------------
# Synthetic season with a known truth (so we can check the harness)
# ----------------------------------------------------------------------

def make_season(n_teams=32, weeks=18, seed=7):
    rnd = random.Random(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    strength = {t: rnd.gauss(0.0, 0.45) for t in teams}   # logit-scale skill
    home_edge = 0.20                                       # ~ real home edge
    games = []
    for _w in range(weeks):
        order = teams[:]
        rnd.shuffle(order)
        for a in range(0, n_teams - 1, 2):
            home, away = order[a], order[a + 1]
            logit = strength[home] - strength[away] + home_edge
            true_p = 1.0 / (1.0 + math.exp(-logit))
            home_win = rnd.random() < true_p
            mu = 3.0 + 7.0 * abs(logit)                    # expected margin
            margin = max(1, round(abs(rnd.gauss(mu, 10.0))))
            if home_win:
                hs, as_ = 17 + margin, 17
            else:
                hs, as_ = 17, 17 + margin
            # two market snapshots from the SAME truth: sharp vs soft.
            # A real closing line is very sharp (tiny noise); a soft/early
            # line at a slow book wanders much further from the truth.
            mkt_sharp = 1.0 / (1.0 + math.exp(-(logit + rnd.gauss(0, 0.02))))
            mkt_soft = 1.0 / (1.0 + math.exp(-(logit + rnd.gauss(0, 0.45))))
            games.append({"home": home, "away": away, "home_score": hs,
                          "away_score": as_, "true_p": true_p,
                          "mkt_sharp": mkt_sharp, "mkt_soft": mkt_soft})
    return games, strength


# ----------------------------------------------------------------------
# Demo / self-check
# ----------------------------------------------------------------------

def calibrate_blend_weight(scen, n_val=20, params=None, warmup=48, val_seed0=9000):
    """
    Choose the model-vs-market blend weight on VALIDATION seasons, so it can be
    applied out-of-sample during evaluation. Picking the weight on the same
    games you then score is lookahead leakage -- it overfits the outcomes and
    invents ROI that doesn't exist. This is how fake 'winning systems' are born.
    """
    params = params or {"k": 20.0, "home_adv": 55.0, "use_mov": True}
    mp_all, mk_all, out_all = [], [], []
    for s in range(n_val):
        games, _ = make_season(seed=val_seed0 + s)
        rows, _ = walk_forward(games, **params)
        test = [r for r in rows if r["i"] >= warmup]
        mp_all += [r["model"] for r in test]
        mk_all += [games[r["i"]][f"mkt_{scen}"] for r in test]
        out_all += [r["out"] for r in test]
    w, _ = best_blend_weight(mp_all, mk_all, out_all)
    return w


def multi_season(weights, n=40, params=None, warmup=48, vig=0.045, thr=0.02,
                 eval_seed0=1000):
    """
    Pool ROI across independent EVALUATION seasons using FIXED blend weights
    (calibrated on separate validation seasons). No per-season weight fitting,
    so no leakage. `weights` is {"sharp": w, "soft": w}.
    """
    params = params or {"k": 20.0, "home_adv": 55.0, "use_mov": True}
    agg = {s: {"model": [0.0, 0], "blend": [0.0, 0]} for s in ("sharp", "soft")}
    for s in range(n):
        games, _ = make_season(seed=eval_seed0 + s)
        rows, _ = walk_forward(games, **params)
        test = [r for r in rows if r["i"] >= warmup]
        model_p = [r["model"] for r in test]
        outs = [r["out"] for r in test]
        for scen in ("sharp", "soft"):
            mk = [games[r["i"]][f"mkt_{scen}"] for r in test]
            bl = [blend_probs(mp, kp, weights[scen]) for mp, kp in zip(model_p, mk)]
            rm = roi_sim(model_p, mk, outs, vig, thr)
            rb = roi_sim(bl, mk, outs, vig, thr)
            agg[scen]["model"][0] += rm["units"]; agg[scen]["model"][1] += rm["bets"]
            agg[scen]["blend"][0] += rb["units"]; agg[scen]["blend"][1] += rb["bets"]
    out = {}
    for scen, d in agg.items():
        out[scen] = {
            "model_roi": d["model"][0] / d["model"][1] if d["model"][1] else 0.0,
            "model_bets": d["model"][1],
            "blend_roi": d["blend"][0] / d["blend"][1] if d["blend"][1] else 0.0,
            "blend_bets": d["blend"][1],
            "weight": weights[scen],
        }
    return out


def _print_row(m):
    print(f"  {m['label']:<22} n={m['n']:<4} "
          f"Brier {m['brier']:.4f}   LogLoss {m['logloss']:.4f}   "
          f"Acc {m['acc']*100:4.1f}%")


if __name__ == "__main__":
    games, truth = make_season()
    warmup = 48

    print("AUTO-TUNING the model (out-of-sample log loss)")
    print("=" * 70)
    best = auto_tune(games, warmup=warmup)
    print(f"  best params:  K={best['k']}  home_adv={best['home_adv']}  "
          f"MOV={best['use_mov']}   logloss={best['logloss']:.4f}")

    rows, final = walk_forward(games, k=best["k"], home_adv=best["home_adv"],
                               use_mov=best["use_mov"])
    test = [r for r in rows if r["i"] >= warmup]
    model_p = [r["model"] for r in test]
    outs = [r["out"] for r in test]

    print("\nCoin flip baseline:  LogLoss 0.6931   (anything below this has signal)")
    print("\nMODEL vs MARKET  (out-of-sample)")
    print("=" * 70)
    _print_row(metrics(model_p, outs, "our model"))

    # Calibrate blend weights out-of-sample (on validation seasons), once.
    weights = {scen: calibrate_blend_weight(scen) for scen in ("sharp", "soft")}

    for scen in ("sharp", "soft"):
        market_p = [games[r["i"]][f"mkt_{scen}"] for r in test]
        w = weights[scen]
        print(f"\n-- {scen.upper()} market " + "-" * (70 - 11 - len(scen)))
        _print_row(metrics(market_p, outs, f"market ({scen})"))
        blend_p = [blend_probs(mp, kp, w) for mp, kp in zip(model_p, market_p)]
        _print_row(metrics(blend_p, outs, f"blend (w={w} oos)"))

    print("\nROI, POOLED OVER 40 SEASONS  (bet only EV > 2%, vig = 4.5%)")
    print("Blend weight calibrated on separate seasons (no leakage)")
    print("=" * 70)
    ms = multi_season(weights)
    for scen in ("sharp", "soft"):
        d = ms[scen]
        print(f"  {scen:<6} market:  model {d['model_roi']*100:+5.1f}% "
              f"({d['model_bets']} bets)   "
              f"blend {d['blend_roi']*100:+5.1f}% ({d['blend_bets']} bets)   "
              f"blend weight {d['weight']:.2f}")

    print("\n" + "=" * 70)
    print("How to read it:")
    print(" - Below 0.6931 log loss, the model has real predictive signal.")
    print(" - Against a SHARP market the blend weight sits near 0 (defer to the")
    print("   line) and pooled ROI lands around or below zero -- you can't")
    print("   out-predict a sharp line once you pay the vig.")
    print(" - Against a SOFT market the model earns real weight and pooled ROI")
    print("   turns clearly positive.")
    print("The lesson: 'better' isn't a fancier model, it's finding soft lines")
    print("and pricing them before the market corrects.")
