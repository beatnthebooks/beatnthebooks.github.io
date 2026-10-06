"""
player_value.py
===============
Two upgrades to the site's model, tested under the project's rules (Mason, Oct 6 2026: "make the model more
tightly grasp the value of players and their skill based on some sort of an importance scale").

PART 1 · One league-wide QB scale.
    The site's model (qb_model.py) moves a team by  mult x (tonight's QB - the team's usual QB level),  so each
    team's Elo has to carry how good its usual QB is. When a star misses most of a season (Burrow, 2025) the
    team's Elo sinks with the backups and half of that is still there the next year. New term:
        abs_mult x (the team's usual QB level - the league average)
    counts the QB directly, so the Elo becomes "the team without its QB". abs_mult = 0 is today's model;
    abs_mult = mult rates every QB on one absolute scale. Tuned on 2006-2015 (log loss), scored once on 2016-2025.

PART 2 · An importance scale for every other position.
    Each non-QB player on the final pre-game injury report counts
        position weight x his usual share of snaps          (playing time)
      + for receivers, tight ends and backs: his receiving + rushing EPA per game so far   (skill)
    Position weights are fixed in advance from published positional-value research (QB far above everyone, then
    receivers and pass rushers, then corners and tackles, ...): WR/DE 1.0, CB/T 0.9, LB/S/TE/DT 0.6, G/C 0.5,
    RB 0.4, FB 0.1 (kickers, punters, long snappers left out). Out/Doubtful count fully, Questionable by a
    tuned fraction. Weights tuned on 2013-2018 (injury reports start in 2013), scored once on 2019-2025.
    (The earlier injury layer, rejected Oct 4, used playing time only, split offense/defense.)

RULE, fixed before running: a part is adopted only if it lowers log loss on its own test seasons versus the
model it would replace. Accuracy, return at closing prices, season-by-season wins and the model's 5%+ picks are
reported either way.

Usage:  py player_value.py      -> results/player_value.txt, results/player_value_settings.json
Standard library only. Uses data already in data/nflverse/ (player stats, snap counts, injury reports).
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import injuries as I
import qb_model as Q
import rift_real as R

ROOT = Path(__file__).resolve().parent
NV = ROOT / "data" / "nflverse"
OUT_TXT = ROOT / "results" / "player_value.txt"
OUT_JSON = ROOT / "results" / "player_value_settings.json"

TRAIN1, TEST1 = set(range(2006, 2016)), set(range(2016, 2026))
TRAIN2, TEST2 = set(range(2013, 2019)), set(range(2019, 2026))

POS_W = {"WR": 1.0, "DE": 1.0, "CB": 0.9, "T": 0.9, "OT": 0.9, "LB": 0.6, "OLB": 0.6, "ILB": 0.6, "MLB": 0.6,
         "S": 0.6, "FS": 0.6, "SS": 0.6, "DB": 0.6, "TE": 0.6, "DT": 0.6, "NT": 0.6, "G": 0.5, "OG": 0.5,
         "C": 0.5, "RB": 0.4, "FB": 0.1}
OFFENSE = {"WR", "T", "OT", "TE", "G", "OG", "C", "RB", "FB"}
SKILL = {"WR", "TE", "RB", "FB"}


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, *a):
        s = " ".join(str(x) for x in a)
        print(s)
        self.f.write(s + "\n")
        self.f.flush()


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------
# Player values (part 2)
# ----------------------------------------------------------------------

def skill_epa() -> dict:
    """{player_id: {season: [(week, receiving + rushing EPA)]}} for every game with a target or a carry."""
    out = defaultdict(lambda: defaultdict(list))
    files = sorted(NV.glob("player_stats_*.csv")) + sorted(NV.glob("stats_player_week_*.csv"))
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if _f(r.get("targets")) == 0 and _f(r.get("carries")) == 0:
                    continue
                out[r["player_id"]][int(r["season"])].append(
                    (int(r["week"]), _f(r.get("receiving_epa")) + _f(r.get("rushing_epa"))))
    return out


def epa_before(epa: dict, pid: str, season: int, week: int) -> float:
    """His EPA per game in earlier games this season (else last season), never below 0: a player who has been
    costing his team points isn't counted as a bonus when he sits."""
    d = epa.get(pid)
    if not d:
        return 0.0
    rows = [e for w, e in d.get(season, []) if w < week] or [e for _, e in d.get(season - 1, [])]
    return max(0.0, sum(rows) / len(rows)) if rows else 0.0


def player_features(value=None, epa=None, examples: list | None = None) -> dict:
    """{(season, week, team): [importance Out/Doubtful, importance Questionable, EPA/game Out/D, EPA/game Q]}"""
    value = value or I.snap_values()
    epa = epa if epa is not None else skill_epa()
    feats = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    seen = set()
    for s in range(2013, 2027):
        path = NV / f"injuries_{s}.csv"
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                st, pos = r["report_status"], r["position"]
                if st not in ("Out", "Doubtful", "Questionable") or pos not in POS_W:
                    continue
                t, wk = I.team(r["team"]), int(r["week"])
                key = (s, wk, t, r["gsis_id"] or r["full_name"])
                if key in seen:
                    continue
                seen.add(key)
                off, dfn = value(s, wk, t, r["full_name"])
                imp = POS_W[pos] * (off if pos in OFFENSE else dfn)
                e = epa_before(epa, r["gsis_id"], s, wk) if pos in SKILL else 0.0
                slot = 0 if st in ("Out", "Doubtful") else 1
                feats[(s, wk, t)][slot] += imp
                feats[(s, wk, t)][2 + slot] += e
                if examples is not None and slot == 0:
                    examples.append((imp, e, s, wk, t, r["full_name"], pos))
    return dict(feats)


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

def ll(recs, seasons):
    return Q.ll_on(recs, seasons)


def evaluate(recs, seasons, blend_w):
    P, M, O, G = R.collect(recs, seasons)
    Pb = R.collect(recs, seasons, blend_w)[0]
    return {"ll": R.log_loss(P, O), "acc": R.accuracy(P, O), "roi0": R.roi(P, G, O, 0.0), "roi3": R.roi(P, G, O, 0.03),
            "ll_b": R.log_loss(Pb, O), "roi0_b": R.roi(Pb, G, O, 0.0), "roi3_b": R.roi(Pb, G, O, 0.03),
            "mkt": R.log_loss(M, O), "n": len(P)}


def paired(recs_a, recs_b, seasons):
    """Per-game log loss difference (b - a): mean and t-stat. Negative mean = b more accurate."""
    la = {id(r["g"]): r["p"] for r in recs_a}
    d = []
    for r in recs_b:
        g = r["g"]
        if g["season"] not in seasons or g["hs"] is None or R.market_fair(g) is None:
            continue
        o, pa, pb = R.outcome(g), la[id(g)], r["p"]
        lo = lambda p: -(o * math.log(p) + (1 - o) * math.log(1 - p))
        d.append(lo(pb) - lo(pa))
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
    return m, m / (sd / math.sqrt(len(d)))


def table(say, rows):
    say(f"  {'':<38}{'LogLoss':>8}{'Acc':>7}{'Return, every edge':>22}{'edges over 3%':>18}")
    for label, e, which in rows:
        if which == "blend":
            l, r0, r3 = e["ll_b"], e["roi0_b"], e["roi3_b"]
        else:
            l, r0, r3 = e["ll"], e["roi0"], e["roi3"]
        acc = f"{e['acc'] * 100:>6.1f}%" if which != "blend" else f"{'':>7}"
        say(f"  {label:<38}{l:>8.4f}{acc}{r0[2] * 100:>+14.1f}% ({r0[0]:>4}){r3[2] * 100:>+10.1f}% ({r3[0]:>4})")


def by_season(say, label_a, ra, label_b, rb, seasons):
    wins = 0
    for s in sorted(seasons):
        a, b = ll(ra, {s}), ll(rb, {s})
        _, M, O, _ = R.collect(rb, {s})
        wins += b < a
        say(f"  {s}: {label_a} {a:.4f}  {label_b} {b:.4f}  market {R.log_loss(M, O):.4f}   {'<- new better' if b < a else ''}")
    say(f"  New model more accurate in {wins} of {len(seasons)} seasons.")


def picks_record(say, label, recs, blend_w, sigma, start, end):
    import weekly as W
    rec = W.model_record(recs, blend_w, sigma, end + 1, start=start)
    ml, sp = rec["ml"], rec["spread"]
    say(f"  {label:<38} moneyline {ml['roi']:+.1f}% on {ml['n']} bets · spread {sp['roi']:+.1f}% on {sp['n']} bets")


def example(say, label, recs):
    for gid in ("2026_05_CIN_MIA",):
        r = next((x for x in recs if x["g"]["gid"] == gid), None)
        if r:
            say(f"  {label:<38} Bengals at Dolphins (week 5): Dolphins {r['p'] * 100:.1f}% to win (market about 24%)")


# ----------------------------------------------------------------------

def main():
    import weekly as W
    say = Tee(OUT_TXT)
    games = W.load(W.DATA)
    stats, team_epa = Q.load_qb_stats(), Q.load_team_epa()
    saved = json.loads(Q.SETTINGS.read_text(encoding="utf-8"))
    saved = saved.get("previous", saved)          # after adoption: still compare against the model this replaced
    cur_p, cur_w = dict(saved["params"]), saved["blend_w"]
    sigma = W.fit_sigma(games, W.DEV["spread"])
    run = lambda p, **kw: Q.run_qb(games, stats, team_epa=team_epa, **dict(p, **kw))[0]
    say(__doc__.split("RULE")[0].strip().splitlines()[0])
    say("Mason asked for a model that grasps player value on an importance scale. Rules fixed before running:")
    say("  a part is adopted only if it lowers log loss on its own test seasons vs the model it would replace.\n")

    # ---------------- PART 1 ----------------
    say("=" * 96)
    say("PART 1 · ONE LEAGUE-WIDE QB SCALE (tune 2006-2015, test 2016-2025 once)")
    say("=" * 96)
    cur = run(cur_p)
    say(f"Current site model: training log loss {ll(cur, TRAIN1):.5f}")
    best_abs, best_ctl = None, None              # with the new term / same tuning without it (control)
    n = 0
    for abs_mult in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        for mult in (1.0, 2.0, 3.3):
            for alpha in (0.1, 0.2):
                for prior_sd in (0.5, 1.0):
                    for regress in (0.33, 0.5, 0.67):
                        p = dict(cur_p, abs_mult=abs_mult, mult=mult, alpha=alpha, team_alpha=alpha,
                                 prior_sd=prior_sd, regress=regress)
                        l_ = ll(run(p), TRAIN1)
                        n += 1
                        if abs_mult > 0 and (best_abs is None or l_ < best_abs[0]):
                            best_abs = (l_, p)
                        if abs_mult == 0 and (best_ctl is None or l_ < best_ctl[0]):
                            best_ctl = (l_, p)
    for name in ("abs", "ctl"):
        b = best_abs if name == "abs" else best_ctl
        top = b
        for epa_mult in (1.0, 2.0, 3.0, 4.0, 6.0):
            for epa_alpha in (0.05, 0.08, 0.15):
                p = dict(b[1], epa_mult=epa_mult, epa_alpha=epa_alpha)
                l_ = ll(run(p), TRAIN1)
                n += 1
                if l_ < top[0]:
                    top = (l_, p)
        if name == "abs":
            best_abs = top
        else:
            best_ctl = top
    say(f"Tried {n} settings on the training seasons.")
    pa = best_abs[1]
    say(f"Chosen (with league-wide QB scale): abs_mult={pa['abs_mult']} mult={pa['mult']} alpha={pa['alpha']} "
        f"new-QB prior={pa['prior_sd']} sd below avg, regress={pa['regress']}, team EPA x{pa['epa_mult']} "
        f"(alpha {pa['epa_alpha']}) -> training log loss {best_abs[0]:.5f}")
    pc = best_ctl[1]
    say(f"Control (same re-tuning, no new term): mult={pc['mult']} alpha={pc['alpha']} prior={pc['prior_sd']} "
        f"regress={pc['regress']} EPA x{pc['epa_mult']} -> training log loss {best_ctl[0]:.5f}")
    new1, ctl1 = run(pa), run(pc)
    P, M, O, _ = R.collect(new1, TRAIN1)
    w_new1 = R.best_blend(P, M, O)[0]
    P, M, O, _ = R.collect(ctl1, TRAIN1)
    w_ctl1 = R.best_blend(P, M, O)[0]
    e_cur, e_new, e_ctl = evaluate(cur, TEST1, cur_w), evaluate(new1, TEST1, w_new1), evaluate(ctl1, TEST1, w_ctl1)
    say("\nOUT-OF-SAMPLE TEST 2016-2025 (closing moneylines; return = betting every side the model likes, $1 flat)")
    table(say, [("current site model", e_cur, "raw"), ("re-tuned, no QB scale (control)", e_ctl, "raw"),
                ("NEW: league-wide QB scale", e_new, "raw"),
                (f"current blend (w={cur_w})", e_cur, "blend"), (f"NEW blend (w={w_new1})", e_new, "blend")])
    say(f"  {'closing market':<38}{e_cur['mkt']:>8.4f}")
    m_, t_ = paired(cur, new1, TEST1)
    say(f"  Per game, new minus current log loss: {m_ * 1000:+.2f} per 1000 (t = {t_:+.2f}; |t| < 2 = could be luck)")
    say("\nBY SEASON (log loss, lower is better)")
    by_season(say, "current", cur, "new", new1, TEST1)
    say("\nTHE SITE'S MODEL PICKS (model edge 5%+, blend, closing prices, 2016-2025)")
    picks_record(say, "current", cur, cur_w, sigma, 2016, 2025)
    picks_record(say, "new", new1, w_new1, sigma, 2016, 2025)
    say("\nTHIS SEASON SO FAR (2026, played games; informative only)")
    if R.collect(cur, {2026})[0]:
        say(f"  current {ll(cur, {2026}):.4f} · new {ll(new1, {2026}):.4f} · market "
            f"{R.log_loss(*[R.collect(cur, {2026})[i] for i in (1, 2)]):.4f}")
    example(say, "current", cur)
    example(say, "new", new1)
    adopt1 = e_new["ll"] < e_cur["ll"]
    say(f"\nPART 1 VERDICT: {'ADOPT' if adopt1 else 'REJECT'} (test log loss {e_cur['ll']:.4f} -> {e_new['ll']:.4f})")

    # ---------------- PART 2 ----------------
    base_p, base_w = (pa, w_new1) if adopt1 else (cur_p, cur_w)
    base_name = "league-wide QB model" if adopt1 else "current site model"
    say("\n" + "=" * 96)
    say(f"PART 2 · IMPORTANCE SCALE FOR EVERY OTHER POSITION, on top of the {base_name}")
    say("         (tune 2013-2018, test 2019-2025 once)")
    say("=" * 96)
    ex = []
    pv = player_features(examples=ex)
    say(f"Team-games with an injury report: {len(pv):,}. Average per team-game: "
        f"importance out {sum(v[0] for v in pv.values()) / len(pv):.2f}, questionable "
        f"{sum(v[1] for v in pv.values()) / len(pv):.2f}, skill EPA/game out {sum(v[2] for v in pv.values()) / len(pv):.2f}")
    say("Biggest single absences in 2024 by importance (position weight x snap share) and skill (EPA/game):")
    for imp, e, s, wk, t, name, pos in sorted([x for x in ex if x[2] == 2024], key=lambda x: -(x[0] + x[1] / 4))[:8]:
        say(f"  {s} wk{wk:>2} {t:<3} {name:<24} {pos:<3} importance {imp:.2f}  EPA/game {e:.1f}")
    base = run(base_p)
    top = (ll(base, TRAIN2), dict(base_p, w_imp=0.0, w_pepa=0.0, q_frac=0.0))
    n = 0
    for w_imp in (0.0, 4.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0):
        for w_pepa in (0.0, 1.0, 2.0, 4.0, 6.0, 9.0, 12.0):
            for q_frac in (0.0, 0.25, 0.5):
                if w_imp == 0 and w_pepa == 0:
                    continue
                p = dict(base_p, w_imp=w_imp, w_pepa=w_pepa, q_frac=q_frac)
                l_ = ll(run(p, pv=pv), TRAIN2)
                n += 1
                if l_ < top[0]:
                    top = (l_, p)
    p2 = top[1]
    say(f"\nTried {n} weightings on 2013-2018. Chosen: {p2['w_imp']} Elo per full-time player at weight 1.0, "
        f"{p2['w_pepa']} Elo per EPA/game of a missing receiver/back, questionable counted at {p2['q_frac']}")
    say(f"  training log loss {ll(base, TRAIN2):.5f} -> {top[0]:.5f}")
    new2 = run(p2, pv=pv)
    P, M, O, _ = R.collect(new2, TRAIN2)
    w_new2 = R.best_blend(P, M, O)[0]
    P, M, O, _ = R.collect(base, TRAIN2)
    w_base2 = R.best_blend(P, M, O)[0]
    e_b, e_n = evaluate(base, TEST2, w_base2), evaluate(new2, TEST2, w_new2)
    say("\nOUT-OF-SAMPLE TEST 2019-2025 (closing moneylines)")
    table(say, [(base_name, e_b, "raw"), ("NEW: + importance scale", e_n, "raw"),
                (f"{base_name} blend (w={w_base2})", e_b, "blend"), (f"NEW blend (w={w_new2})", e_n, "blend")])
    say(f"  {'closing market':<38}{e_b['mkt']:>8.4f}")
    m_, t_ = paired(base, new2, TEST2)
    say(f"  Per game, new minus base log loss: {m_ * 1000:+.2f} per 1000 (t = {t_:+.2f})")
    say("\nBY SEASON (log loss)")
    by_season(say, "base", base, "new", new2, TEST2)
    say("\nTHE SITE'S MODEL PICKS (model edge 5%+, blend, closing prices, 2019-2025)")
    picks_record(say, base_name, base, w_base2, sigma, 2019, 2025)
    picks_record(say, "+ importance scale", new2, w_new2, sigma, 2019, 2025)
    adopt2 = p2["w_imp"] + p2["w_pepa"] > 0 and e_n["ll"] < e_b["ll"]
    say(f"\nPART 2 VERDICT: {'ADOPT' if adopt2 else 'REJECT'} (test log loss {e_b['ll']:.4f} -> {e_n['ll']:.4f})")

    OUT_JSON.write_text(json.dumps({
        "part1": {"adopt": adopt1, "params": pa, "blend_w": w_new1, "control": pc,
                  "test_ll": {"current": e_cur["ll"], "new": e_new["ll"], "control": e_ctl["ll"], "market": e_cur["mkt"]}},
        "part2": {"adopt": adopt2, "params": {k: p2[k] for k in ("w_imp", "w_pepa", "q_frac")}, "blend_w": w_new2,
                  "base": base_name, "test_ll": {"base": e_b["ll"], "new": e_n["ll"], "market": e_b["mkt"]}},
        "pos_weights": POS_W}, indent=2), encoding="utf-8")
    say(f"\nWrote {OUT_TXT.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
