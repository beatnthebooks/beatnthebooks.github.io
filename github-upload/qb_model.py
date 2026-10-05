"""
qb_model.py
===========
Elo with a rating for every quarterback (the biggest gap in the original model,
which only knew whether a team's usual QB was starting).

How it works, walk-forward (every number is made before that game's result is used):
  * Each QB has a value rating: an exponential moving average of his per-game value.
    Per-game value is either
      "box": 538's QB formula  -2.2*Att + 3.7*Cmp + Yds/5 + 11.3*TD - 14.1*Int - 8*Sk
                               - 1.1*RushAtt + 0.6*RushYds + 15.9*RushTD
      "epa": passing EPA + rushing EPA (expected points added, from play-by-play)
  * Each team has a rolling average of its starters' values: what its Elo already "knows".
  * Before a game, each team's Elo moves by  mult x (tonight's starter - team average).
    A star returning lifts the team; a backup starting drags it down.
  * New QBs start below the league average (prior_sd standard deviations below).
  * QB values carry across seasons, regressed 25% toward the league average.

Protocol (same as the rest of the project): the QB settings are chosen on 2006-2015 only
(log loss), then 2016-2025 is scored once. Compared with the current model and the market,
at closing prices, and against opening lines (does the line move toward the new model?).

Data: data/nflverse/player_stats_<1999-2024>.csv and stats_player_week_<2025-2026>.csv.

Usage:  py qb_model.py
Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import rift_real as R

ROOT = Path(__file__).resolve().parent
NV = ROOT / "data" / "nflverse"
PARAMS = ROOT / "results" / "current_ratings.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_qb_stats() -> dict:
    """{(player_id, season, week): {"box": v, "epa": v}} for every player-game with a pass or rush."""
    out = {}
    files = sorted(NV.glob("player_stats_*.csv")) + sorted(NV.glob("stats_player_week_*.csv"))
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                att, car = _f(r.get("attempts")), _f(r.get("carries"))
                if att == 0 and car == 0:
                    continue
                ints = _f(r.get("interceptions", r.get("passing_interceptions")))
                sacks = _f(r.get("sacks", r.get("sacks_suffered")))
                box = (-2.2 * att + 3.7 * _f(r.get("completions")) + _f(r.get("passing_yards")) / 5
                       + 11.3 * _f(r.get("passing_tds")) - 14.1 * ints - 8 * sacks
                       - 1.1 * car + 0.6 * _f(r.get("rushing_yards")) + 15.9 * _f(r.get("rushing_tds")))
                epa = _f(r.get("passing_epa")) + _f(r.get("rushing_epa"))
                out[(r["player_id"], int(r["season"]), int(r["week"]))] = {"box": box, "epa": epa}
    return out


def load_team_epa() -> dict:
    """{(team, season, week): offensive EPA} = passers' passing EPA + rushers' rushing EPA
    (receiving EPA is the same plays as passing, so it's left out to avoid double counting)."""
    out = defaultdict(float)
    files = sorted(NV.glob("player_stats_*.csv")) + sorted(NV.glob("stats_player_week_*.csv"))
    for path in files:
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                team = r.get("recent_team") or r.get("team")
                if not team:
                    continue
                team = R.FRANCHISE.get(team, team)
                out[(team, int(r["season"]), int(r["week"]))] += _f(r.get("passing_epa")) + _f(r.get("rushing_epa"))
    return out


def inj_penalty(d, w_off, w_def, w_q) -> float:
    """Elo points a team loses for players listed Out/Doubtful (and, weighted by w_q,
    Questionable), each counted by his usual share of snaps (1.0 = a full-time player)."""
    if not d:
        return 0.0
    return w_off * d["off_out"] + w_def * d["def_out"] + w_q * (d["off_q"] + d["def_q"])


def load_injuries() -> dict:
    """Injury reports valued by snap share, QBs left out (the QB ratings cover them)."""
    import injuries as I
    return dict(I.team_injuries(I.snap_values(), skip_positions=("QB",)))


def run_qb(games, stats, k=20.0, hfa=55.0, regress=0.5, mov=True, rest_pts=6.0, qb_pen=0.0,
           val="box", mult=0.0, alpha=0.1, team_alpha=0.1, prior_sd=0.5,
           team_epa=None, epa_mult=0.0, epa_alpha=0.15,
           inj=None, w_off=0.0, w_def=0.0, w_q=0.0, qb_at_open=False, **_ignored):
    """Like rift_real.run, plus the QB adjustment and (optionally) team EPA efficiency.
    qb_at_open=True predicts each game as of when its line opens: a team's starter is assumed to
    be whoever started its previous game this season (week 1 uses the actual starter, since
    offseason moves are known by then). Ratings still update with the real starters.
    Returns (records, ratings)."""
    Rt = defaultdict(lambda: 1500.0)
    qb_val, team_val = {}, {}
    off, dfn = defaultdict(float), defaultdict(float)   # EMA offensive EPA made / allowed per game
    lg = [0.0, 0.0, 0]                      # running sum, sum of squares, n of starter values
    season, qb_hist, recs = None, {}, []
    last_qb = {}                            # team -> most recent starter this season

    def league():
        n = lg[2]
        if n < 30:
            return (0.0, 1.0) if val == "epa" else (0.0, 1.0)
        m = lg[0] / n
        return m, math.sqrt(max(1e-9, lg[1] / n - m * m))

    for g in games:
        if g["season"] != season:
            if season is not None:
                for t in list(Rt):
                    Rt[t] = 1500.0 + (Rt[t] - 1500.0) * (1.0 - regress)
                m, _ = league()
                for q in qb_val:
                    qb_val[q] = m + (qb_val[q] - m) * 0.75
                for t in list(off):
                    off[t] *= 0.67
                    dfn[t] *= 0.67
            season, qb_hist, last_qb = g["season"], {}, {}
        h, a = g["home"], g["away"]
        hqb, aqb = g["hqb"], g["aqb"]
        if qb_at_open:
            hqb, aqb = last_qb.get(h, hqb), last_qb.get(a, aqb)
        m, sd = league()

        def adj_for(team, qb):
            if not qb or mult == 0:
                return 0.0
            v = qb_val.get(qb, m - prior_sd * sd)
            return mult * (v - team_val.get(team, m))

        hflag, aflag = R._qb_flag(qb_hist, h, hqb), R._qb_flag(qb_hist, a, aqb)
        adj = 0.0 if g["neutral"] else hfa
        adj += max(-35.0, min(35.0, rest_pts * (g["hrest"] - g["arest"])))
        adj += qb_pen * (aflag - hflag)
        adj += adj_for(h, hqb) - adj_for(a, aqb)
        if epa_mult:
            adj += epa_mult * ((off[h] - dfn[h]) - (off[a] - dfn[a]))
        if inj is not None and (w_off or w_def or w_q):
            adj += inj_penalty(inj.get((g["season"], g["week"], a)), w_off, w_def, w_q) \
                - inj_penalty(inj.get((g["season"], g["week"], h)), w_off, w_def, w_q)
        diff = Rt[h] + adj - Rt[a]
        p = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        recs.append({"g": g, "p": p, "hflag": hflag, "aflag": aflag,      # rh/ra: strength before the game
                     "rh": Rt[h] + epa_mult * (off[h] - dfn[h]), "ra": Rt[a] + epa_mult * (off[a] - dfn[a])})
        if g["hs"] is None:
            continue

        act = R.outcome(g)
        mlt = 1.0
        margin = abs(g["hs"] - g["as"])
        if mov and margin > 0:
            wd = diff if act == 1.0 else -diff
            mlt = math.log(margin + 1.0) * (2.2 / (wd * 0.001 + 2.2))
        d = k * mlt * (act - p)
        Rt[h] += d
        Rt[a] -= d
        if team_epa is not None:
            eh = team_epa.get((h, g["season"], g["week"]))
            ea = team_epa.get((a, g["season"], g["week"]))
            if eh is not None and ea is not None:
                off[h] += epa_alpha * (eh - off[h]); dfn[h] += epa_alpha * (ea - dfn[h])
                off[a] += epa_alpha * (ea - off[a]); dfn[a] += epa_alpha * (eh - dfn[a])
        for team, qb in ((h, g["hqb"]), (a, g["aqb"])):
            if qb:
                last_qb[team] = qb
                qb_hist.setdefault(team, []).append(qb)
                st = stats.get((qb, g["season"], g["week"]))
                if st is not None:
                    v = st[val]
                    if qb not in qb_val:
                        qb_val[qb] = m - prior_sd * sd
                    qb_val[qb] += alpha * (v - qb_val[qb])
                    team_val[team] = team_val.get(team, m) + team_alpha * (v - team_val.get(team, m))
                    lg[0] += v
                    lg[1] += v * v
                    lg[2] += 1
    strength = {t: Rt[t] + epa_mult * (off[t] - dfn[t]) for t in list(Rt)}
    return recs, strength


SETTINGS = ROOT / "results" / "qb_model_settings.json"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download"


def ensure_stats(current_season: int, refresh_current: bool) -> None:
    """Download any missing player-stats files (and, if asked, re-download the current season's,
    which grows every week). Older seasons use player_stats_<yr>.csv, 2025+ stats_player_week_<yr>.csv."""
    import urllib.request
    NV.mkdir(parents=True, exist_ok=True)
    for yr in range(1999, current_season + 1):
        name = f"player_stats_{yr}.csv" if yr <= 2024 else f"stats_player_week_{yr}.csv"
        url = f"{STATS_URL}/{'player_stats' if yr <= 2024 else 'stats_player'}/{name}"
        path = NV / name
        if path.exists() and not (refresh_current and yr == current_season):
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except Exception as exc:
            print(f"  couldn't download {name} ({exc}); using what's there")


class Model:
    """The site's model: QB ratings + team EPA on top of Elo, with the settings tuned on
    2006-2015 (results/qb_model_settings.json)."""
    def __init__(self):
        saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        self.params, self.blend_w = saved["params"], saved["blend_w"]
        self.stats = load_qb_stats()
        self.team_epa = load_team_epa()

    def run(self, games):
        return run_qb(games, self.stats, team_epa=self.team_epa, **self.params)


def ll_on(recs, seasons):
    P, _, O, _ = R.collect(recs, seasons)
    return R.log_loss(P, O)


def tune(games, stats, core):
    best = (ll_on(run_qb(games, stats, **core)[0], R.TRAIN), dict(core))
    grids = {"box": (1.0, 2.0, 3.3, 5.0), "epa": (2.0, 4.0, 6.0, 9.0)}
    for val, mults in grids.items():
        for mult in mults:
            for alpha in (0.1, 0.2):
                for prior_sd in (0.0, 0.5, 1.0):
                    for qb_pen in (0.0, core.get("qb_pen", 0.0)):
                        p = dict(core, val=val, mult=mult, alpha=alpha, team_alpha=alpha,
                                 prior_sd=prior_sd, qb_pen=qb_pen)
                        ll = ll_on(run_qb(games, stats, **p)[0], R.TRAIN)
                        if ll < best[0]:
                            best = (ll, p)
    return best[1], best[0]


def tune_inj(games, stats, team_epa, inj, best):
    """Third stage: how many Elo points a missing full-time starter is worth, offense vs
    defense (training seasons only; injury reports exist from 2013)."""
    run = lambda p: ll_on(run_qb(games, stats, team_epa=team_epa, inj=inj, **p)[0], R.TRAIN)
    top = (run(dict(best, w_off=0.0, w_def=0.0, w_q=0.0)), dict(best, w_off=0.0, w_def=0.0, w_q=0.0))
    for w_off in (0.0, 4.0, 8.0, 12.0, 18.0, 25.0):
        for w_def in (0.0, 4.0, 8.0, 12.0, 18.0, 25.0):
            for w_q in (0.0, 2.0):
                p = dict(best, w_off=w_off, w_def=w_def, w_q=w_q)
                ll = run(p)
                if ll < top[0]:
                    top = (ll, p)
    return top[1], top[0]


def tune_epa(games, stats, team_epa, qb_best):
    """Second stage: team EPA efficiency on top of the chosen QB settings (training seasons only)."""
    best = (ll_on(run_qb(games, stats, **qb_best)[0], R.TRAIN), dict(qb_best, epa_mult=0.0))
    for epa_mult in (0.5, 1.0, 2.0, 3.0, 4.0, 6.0):
        for epa_alpha in (0.08, 0.15, 0.25):
            p = dict(qb_best, epa_mult=epa_mult, epa_alpha=epa_alpha)
            ll = ll_on(run_qb(games, stats, team_epa=team_epa, **p)[0], R.TRAIN)
            if ll < best[0]:
                best = (ll, p)
    return best[1], best[0]


def score(label, recs, seasons, blend_w=None):
    P, M, O, G = R.collect(recs, seasons, blend_w)
    b0, u0, r0 = R.roi(P, G, O, 0.0)
    b3, u3, r3 = R.roi(P, G, O, 0.03)
    print(f"  {label:<34}{R.log_loss(P, O):>8.4f}{R.accuracy(P, O) * 100:>7.1f}%"
          f"{r0 * 100:>+8.1f}% ({b0:>4}){r3 * 100:>+8.1f}% ({b3:>4})")


def opener_check(label, recs, blend_w):
    """Against the aussportsbetting opening lines: do lines move toward the lean?"""
    try:
        import history as H
    except Exception:
        return
    if not H.XLSX.exists():
        return
    p_by = {id(r["g"]): r["p"] for r in recs}
    ms = [m for m in H.match(H.read_xlsx(), [r["g"] for r in recs]) if m["g"]["season"] >= 2014]
    by = defaultdict(lambda: {"clv": [], "o": []})
    for m in ms:
        g = m["g"]
        p = p_by.get(id(g))
        dh, da, fo = H.side_prices(m, "o")
        _, _, fc = H.side_prices(m, "c")
        if p is None or fo is None or fc is None:
            continue
        bl = blend_w * p + (1 - blend_w) * fo
        evh, eva = bl * dh - 1, (1 - bl) * da - 1
        if max(evh, eva) <= 0:
            continue
        home = evh >= eva
        y = None if g["hs"] == g["as"] else g["hs"] > g["as"]
        by[H.source(g["season"])]["o"].append(0.0 if y is None else ((dh if home else da) - 1 if y == home else -1.0))
        if fc != fo:
            by[H.source(g["season"])]["clv"].append((fc > fo) if home else (fc < fo))
    for s in sorted(by):
        d = by[s]
        c = sum(d["clv"]) / len(d["clv"]) * 100 if d["clv"] else float("nan")
        roi = sum(d["o"]) / len(d["o"]) * 100 if d["o"] else float("nan")
        print(f"  {label:<14} {s:<22} line moved toward the lean {c:5.1f}% of {len(d['clv']):>4} · "
              f"bet at the open: {roi:+5.1f}% on {len(d['o'])}")


def main():
    games = R.load(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "games.csv")
    stats = load_qb_stats()
    print(f"Loaded {len(stats):,} player-games of passing/rushing stats.")
    saved = json.loads(PARAMS.read_text(encoding="utf-8"))
    core = dict(saved["params"])
    print("Tuning QB ratings on 2006-2015 only ...")
    best, ll_tr = tune(games, stats, core)
    base_tr = ll_on(R.run(games, **core)[0], R.TRAIN)
    print(f"  chosen: value={best.get('val')} mult={best.get('mult')} alpha={best.get('alpha')} "
          f"new-QB prior={best.get('prior_sd')} sd below avg · backup flag={best.get('qb_pen')}")
    print(f"  training log loss: current model {base_tr:.4f} -> QB model {ll_tr:.4f}")
    team_epa = load_team_epa()
    best, ll_tr2 = tune_epa(games, stats, team_epa, best)
    print(f"  + team EPA efficiency: mult={best.get('epa_mult')} alpha={best.get('epa_alpha')}"
          f" -> training log loss {ll_tr2:.4f}")

    inj = load_injuries()
    final, ll_tr3 = tune_inj(games, stats, team_epa, inj, best)
    print(f"  + injuries (all non-QB positions, by snap share): offense {final['w_off']} Elo, "
          f"defense {final['w_def']} Elo per full-time starter out, questionable {final['w_q']}"
          f" -> training log loss {ll_tr3:.4f}")

    cur = R.run(games, **core)[0]
    qbe = run_qb(games, stats, team_epa=team_epa, **best)[0]
    new = run_qb(games, stats, team_epa=team_epa, inj=inj, **final)[0]
    w_cur = saved["blend_w"]
    P, M, O, _ = R.collect(qbe, R.TRAIN)
    w_qbe = R.best_blend(P, M, O)[0]
    P, M, O, _ = R.collect(new, R.TRAIN)
    w_new = R.best_blend(P, M, O)[0]

    print("\nOUT-OF-SAMPLE TEST 2016-2025 (closing moneylines)")
    print(f"  {'':<34}{'LogLoss':>8}{'Acc':>8}{'ROI EV>0':>15}{'ROI EV>3%':>15}")
    score("original Elo", cur, R.TEST)
    score("QB + team EPA", qbe, R.TEST)
    score("QB + team EPA + injuries", new, R.TEST)
    score(f"original blend (w={w_cur})", cur, R.TEST, w_cur)
    score(f"QB + EPA blend (w={w_qbe})", qbe, R.TEST, w_qbe)
    score(f"+ injuries blend (w={w_new})", new, R.TEST, w_new)
    P, M, O, _ = R.collect(new, R.TEST)
    print(f"  {'closing market':<34}{R.log_loss(M, O):>8.4f}{R.accuracy(M, O) * 100:>7.1f}%")

    print("\nBY SEASON (log loss; lower wins)")
    for s in sorted(R.TEST):
        _, Ms, Os, _ = R.collect(new, {s})
        print(f"  {s}: original {ll_on(cur, {s}):.4f}  QB+EPA {ll_on(qbe, {s}):.4f}  "
              f"+injuries {ll_on(new, {s}):.4f}  market {R.log_loss(Ms, Os):.4f}")

    print("\nAGAINST OPENING LINES (2014+; no injury info, which isn't known when lines open)")
    opener_check("original", cur, w_cur)
    opener_check("QB + EPA", qbe, w_qbe)

    # Adopted: QB + team EPA. The injury layer (all non-QB positions by snap share) improved the
    # training seasons but not 2016-2025 (log loss 0.6290 -> 0.6291, close ROI -5.5% -> -6.3%), and
    # its weights (offense 0, defense at the grid maximum) look like noise from 3 seasons of reports.
    out = ROOT / "results" / "qb_model_settings.json"
    out.write_text(json.dumps({"params": best, "blend_w": w_qbe,
                               "injury_layer_rejected": {"weights": {k: final[k] for k in ("w_off", "w_def", "w_q")},
                                                         "blend_w": w_new}}, indent=2), encoding="utf-8")
    print(f"\nWrote {out.relative_to(ROOT)} (adopted: QB + team EPA; injury layer rejected)")


if __name__ == "__main__":
    main()
