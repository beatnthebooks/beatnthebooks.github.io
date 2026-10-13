"""
disagreement.py
===============
Should the site skip model picks where the model and the market disagree a lot? (Oct 12 2026, after week 5:
the biggest disagreements, Dolphins 43% vs 25%, Cardinals 47% vs 30%, Browns 65% vs 44%, all lost.)

Rule, fixed before running (the 15-point line came from week 5 of 2026, not from the test seasons):
  * Bets: the site's suggested model picks (model edge >= weekly.MODEL_MIN_EDGE, moneyline and spread, the
    model's blend with the market as the site uses it), at the closing price, on 2019-2025: the current model's
    unseen seasons (results/qb_model_settings.json, first_unseen_season).
  * Disagreement = |model win chance - market's fair win chance| in percentage points, at the close.
  * Adopt "skip model picks with disagreement > 15" only if those picks returned less than the rest overall AND in
    both halves (2019-2021, 2022-2025).

Usage:  py disagreement.py      -> results/disagreement.txt
"""

from __future__ import annotations

import math
from pathlib import Path

import qb_model as Q
import weekly as W
from edge_lab import devig
from rift_real import am_to_dec

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "disagreement.txt"
LINE = 15.0
SEASONS, HALVES = range(2019, 2026), (range(2019, 2022), range(2022, 2026))


def model_picks(recs, w, sigma, seasons):
    """(season, kind, disagreement, return per $1) for every suggested model pick at the close."""
    out = []
    for r in recs:
        g = r["g"]
        if g["season"] not in seasons or g["hs"] is None or not (g["hml"] and g["aml"]):
            continue
        f = devig(g["hml"], g["aml"])
        dis = abs(r["p"] - f) * 100
        if g["hs"] != g["as"]:
            bl = w * r["p"] + (1 - w) * f
            dh, da = am_to_dec(g["hml"]), am_to_dec(g["aml"])
            evh, eva = bl * dh - 1, (1 - bl) * da - 1
            home = evh >= eva
            if max(evh, eva) * 100 >= W.MODEL_MIN_EDGE:
                won = (g["hs"] > g["as"]) == home
                out.append((g["season"], "ml", dis, (dh if home else da) - 1 if won else -1.0))
        if g["spread"] is not None and g["hso"] and g["aso"]:
            pc = W.spread_cover(r["p"], g["spread"], sigma, w)
            dh, da = am_to_dec(g["hso"]), am_to_dec(g["aso"])
            evh, eva = pc * dh - 1, (1 - pc) * da - 1
            home = evh >= eva
            if max(evh, eva) * 100 >= W.MODEL_MIN_EDGE:
                margin = g["hs"] - g["as"]
                ret = 0.0 if margin == g["spread"] else ((dh if home else da) - 1 if (margin > g["spread"]) == home else -1.0)
                out.append((g["season"], "spread", dis, ret))
    return out


def summary(rows):
    n = len(rows)
    if not n:
        return n, float("nan"), float("nan")
    rets = [x[3] for x in rows]
    m = sum(rets) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / max(1, n - 1))
    return n, m * 100, sd


def diff_t(a, b):
    na, ma, sa = summary(a)
    nb, mb, sb = summary(b)
    se = math.sqrt((sa ** 2) / max(1, na) + (sb ** 2) / max(1, nb)) * 100
    return (ma - mb) / se if se else float("nan")


def main():
    lines = []
    say = lambda s="": (print(s), lines.append(s))
    games = W.load(W.DATA)
    m = Q.Model()
    recs, _ = m.run(games)
    sigma = W.fit_sigma(games, W.DEV["spread"])
    picks = model_picks(recs, m.blend_w, sigma, SEASONS)
    say(__doc__.strip().split("Usage:")[0].rstrip())
    say(f"\nModel: {Q.SETTINGS.name} (blend {m.blend_w}); {len(picks)} suggested model picks 2019-2025 at the close\n")
    say("BY DISAGREEMENT (return per $1 at the closing price)")
    for lo, hi in ((0, 5), (5, 10), (10, 15), (15, 20), (20, 100)):
        for kind in ("ml", "spread", "all"):
            rows = [x for x in picks if lo <= x[2] < hi and (kind == "all" or x[1] == kind)]
            n, roi, _ = summary(rows)
            if kind == "all":
                say(f"  {lo:>2}-{hi if hi < 100 else '':<3} pts   all {n:>4} bets {roi:+6.1f}%")
            else:
                say(f"  {lo:>2}-{hi if hi < 100 else '':<3} pts {kind:>6} {n:>4} bets {roi:+6.1f}%")
    say("\nTHE RULE: skip picks with disagreement > 15 points")
    big = [x for x in picks if x[2] > LINE]
    rest = [x for x in picks if x[2] <= LINE]
    nb, rb, _ = summary(big)
    nr, rr, _ = summary(rest)
    say(f"  2019-2025: over 15 pts {nb} bets {rb:+.1f}% | 15 or less {nr} bets {rr:+.1f}% | difference t = {diff_t(big, rest):+.2f}")
    ok = rb < rr
    for h in HALVES:
        b = [x for x in big if x[0] in h]
        r_ = [x for x in rest if x[0] in h]
        n1, r1, _ = summary(b)
        n2, r2, _ = summary(r_)
        say(f"  {h.start}-{h.stop - 1}: over 15 pts {n1} bets {r1:+.1f}% | 15 or less {n2} bets {r2:+.1f}%")
        ok = ok and (n1 > 0 and r1 < r2)
    say(f"\nVERDICT: {'ADOPT: skip model picks more than 15 points from the market' if ok else 'REJECT: keep suggesting them'}")
    cur = model_picks(recs, m.blend_w, sigma, {2026})
    cb = [x for x in cur if x[2] > LINE]
    cr = [x for x in cur if x[2] <= LINE]
    say(f"\n2026 so far (informative): over 15 pts {summary(cb)[0]} bets {summary(cb)[1]:+.1f}% | "
        f"15 or less {summary(cr)[0]} bets {summary(cr)[1]:+.1f}%")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return ok


if __name__ == "__main__":
    main()
