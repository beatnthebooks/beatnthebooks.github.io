"""
weekly.py
=========
Build the Beatn' the Books website (site/): every NFL game of the current season,
week by week, combining everything the project knows:

  * Elo win probability and Elo line (rift_real.run, walk-forward: every
    game's number was made before that game's result was used)
  * the market: moneyline (de-vigged), spread and total from games.csv
  * the Elo "lean" (blend of Elo and market, +EV at the posted price) -- shown
    with its real track record, which is negative at closing prices
  * the wind watch: forecast wind for outdoor games, UNDER signal at >= 10 mph
  * results, season-to-date scoring, and power ratings

Wind forecasts are logged in data/wind_log.json. A game's entry is refreshed
on every run until kickoff, then frozen, so the season record scores the
forecast you would have bet on. Games kicked off before the log existed are
backfilled from Open-Meteo's archived short-range forecasts (the same source
as the wind backtest).

The pages (site/*.html, site/assets/) are static; this script only writes
site/data.js (all the numbers) and build/artifact-index.html (the home page
without its document wrapper, for publishing to claude.ai).

Usage:
    py weekly.py            # rebuild site/data.js from data/games.csv
    py weekly.py --fetch    # download the latest nflverse games.csv first

Open site/index.html in a browser to view it locally. Publishing: see CLAUDE.md.
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import NormalDist

import alerts
import picks as P
from edge_lab import DEV, _inverse, _solve, devig, fit_sigma, load, logit, sigmoid
from odds import EXCHANGE_FEE, add_live_exchanges, get_odds, log_snapshots, match_games
from qb_model import Model as QBModel, ensure_stats
from rift_real import TEAM_NAME, am_to_dec, run
from update_board import now_central
from wind_check import STADIUMS, WIND_MPH, fetch, forecast, game_wind, stadium_key

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "games.csv"
PARAMS = ROOT / "results" / "current_ratings.json"
WIND_LOG = ROOT / "data" / "wind_log.json"
SITE = ROOT / "site"
ARTIFACT_INDEX = ROOT / "build" / "artifact-index.html"
SOURCE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
OUTDOOR = ("outdoors", "open")
GAP_EV = 2.0       # flag an exchange price this many % better than the sportsbooks' fair price, after fees
GAP_MIN_BOOKS = 5  # ...but only when that fair price comes from this many books. Early in the week only a
                   # few post lines, and their median strayed 2-5 win-% pts from the consensus (Oct 4, 2026)


# ----------------------------------------------------------------------
# Data refresh
# ----------------------------------------------------------------------

def fetch_games() -> None:
    """Download the latest nflverse games.csv; keep the old file if anything looks off."""
    with urllib.request.urlopen(SOURCE, timeout=120) as resp:
        raw = resp.read()
    text = raw.decode("utf-8")
    if not text.startswith("game_id,") or text.count("\n") < 7000:
        raise RuntimeError("downloaded games.csv looks wrong; kept the old file")
    tmp = DATA.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(DATA)
    print(f"Downloaded games.csv ({len(raw):,} bytes)")


def kickoff_ct(g) -> datetime:
    """games.csv kickoffs are Eastern; Central is one hour earlier."""
    return datetime.fromisoformat(f"{g['date']}T{g['time']}") - timedelta(hours=1)


def update_wind_log(games, season: int, now: datetime) -> dict:
    log = json.loads(WIND_LOG.read_text(encoding="utf-8")) if WIND_LOG.exists() else {}
    outdoor = [g for g in games if g["season"] == season and g["roof"] not in ("dome", "closed")
               and stadium_key(g) in STADIUMS]

    # 1) not kicked off, within the 16-day forecast range: take the latest live forecast
    upcoming = defaultdict(list)
    for g in outdoor:
        ko = kickoff_ct(g)
        if g["hs"] is None and now < ko <= now + timedelta(days=15):
            upcoming[stadium_key(g)].append(g)
    for sid, gs in upcoming.items():
        try:
            series = forecast(*STADIUMS[sid])
        except Exception as exc:                       # keep the last good value
            print(f"  live forecast failed for {sid}: {exc}")
            continue
        for g in gs:
            w = game_wind(series, g["date"], g["time"])
            if w is not None:
                log[g["gid"]] = {"wind": round(w, 1), "src": "live",
                                 "asof": now.isoformat(timespec="minutes")}

    # 2) kicked off but never logged: backfill from the archived short-range forecast
    missing = defaultdict(list)
    for g in outdoor:
        if kickoff_ct(g) <= now and g["gid"] not in log:
            missing[stadium_key(g)].append(g)
    for sid, gs in missing.items():
        lat, lon = STADIUMS[sid]
        start = min(g["date"] for g in gs)
        end = min(max(g["date"] for g in gs), now.date().isoformat())
        try:
            h = fetch("https://historical-forecast-api.open-meteo.com/v1/forecast?"
                      f"latitude={lat}&longitude={lon}&wind_speed_unit=mph"
                      f"&timezone=America/New_York&start_date={start}&end_date={end}"
                      "&hourly=wind_speed_10m")["hourly"]
        except Exception as exc:
            print(f"  archived forecast failed for {sid}: {exc}")
            continue
        series = dict(zip(h["time"], h["wind_speed_10m"]))
        for g in gs:
            w = game_wind(series, g["date"], g["time"])
            if w is not None:
                log[g["gid"]] = {"wind": round(w, 1), "src": "archive", "asof": None}

    WIND_LOG.write_text(json.dumps(log, indent=1, sort_keys=True), encoding="utf-8")
    return log


# ----------------------------------------------------------------------
# Page data
# ----------------------------------------------------------------------

WIND_FIT_FROM = 2006


def _fit_offset_logit(X, offset, y, iters=40):
    """Logistic regression with a fixed offset (the market's own log-odds). Returns (coefs, std errors).
    No data: zeros (= no shift from the market)."""
    if not y:
        return [0.0], [0.0]
    k = len(X[0])
    beta = [0.0] * k
    H = None
    for _ in range(iters):
        grad, H = [0.0] * k, [[0.0] * k for _ in range(k)]
        for x, o, t in zip(X, offset, y):
            p = sigmoid(o + sum(b * v for b, v in zip(beta, x)))
            w = p * (1 - p)
            for i in range(k):
                grad[i] += (t - p) * x[i]
                for j in range(k):
                    H[i][j] += w * x[i] * x[j]
        step = _solve(H, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-10:
            break
    cov = _inverse(H)
    return beta, [math.sqrt(max(cov[i][i], 0.0)) for i in range(k)]


# Realistic edges for ranking a game's bets (Oct 5, 2026). Each bet type's chance of winning is the market's
# fair chance shifted by what that type of bet ACTUALLY did in past seasons:
#     logit P(win) = logit(p_market) + shift
# then edge = P(win) x decimal price - 1 at the price you'd pay. Why not the raw model numbers: at closing prices
# 2016-2025, wind unders were predicted +2.2% by a wind-speed model but returned +11.8%; model leans were predicted
# +5.1% and returned -5.4%, and the biggest predicted lean edges did worst (-7.3%). Wind speed above 10 mph didn't
# separate better unders from worse ones, so one shift per bet type.
PICKS_FIT_FROM = 2006
LEAN_FIT_FROM = 2016   # the model's settings were tuned on 2006-2015, so leans only count from its first unseen season


def fit_wind_shift(games: list, season: int) -> dict:
    """How much more often unders won than the closing price said, in outdoor/open-roof games with recorded
    wind >= 10 mph, 2006 to last season."""
    off, y = [], []
    for g in games:
        if not (PICKS_FIT_FROM <= g["season"] < season) or g["hs"] is None or g["roof"] not in OUTDOOR:
            continue
        if g["wind"] is None or g["wind"] < WIND_MPH or g["tot"] is None or not g["oo"] or not g["uo"]:
            continue
        pts = g["hs"] + g["as"]
        if pts == g["tot"]:
            continue
        off.append(logit(1 - devig(g["oo"], g["uo"])))
        y.append(1.0 if pts < g["tot"] else 0.0)
    beta, se = _fit_offset_logit([[1.0]] * len(y), off, y)
    return {"shift": round(beta[0], 5), "se": round(se[0], 5), "n": len(y), "won": int(sum(y)),
            "seasons": f"{PICKS_FIT_FROM}-{season - 1}"}


def fit_lean_shift(recs: list, blend_w: float, season: int, start: int = LEAN_FIT_FROM) -> dict:
    """How often the model's lean side won compared with the closing fair price, from the model's first
    unseen season to last season (walk-forward; lean = the side with a positive expected return at the
    closing price). Training seasons are left out: the model was tuned to look good on them."""
    off, y = [], []
    for r in recs:
        g = r["g"]
        if not (start <= g["season"] < season) or g["hs"] is None or not g["hml"] or not g["aml"]:
            continue
        if g["hs"] == g["as"]:
            continue
        f = devig(g["hml"], g["aml"])
        bl = blend_w * r["p"] + (1 - blend_w) * f
        evh, eva = bl * am_to_dec(g["hml"]) - 1, (1 - bl) * am_to_dec(g["aml"]) - 1
        if max(evh, eva) <= 0:
            continue
        home = evh >= eva
        off.append(logit(f if home else 1 - f))
        y.append(1.0 if (g["hs"] > g["as"]) == home else 0.0)
    beta, se = _fit_offset_logit([[1.0]] * len(y), off, y)
    return {"shift": round(beta[0], 5), "se": round(se[0], 5), "n": len(y), "won": int(sum(y)),
            "seasons": f"{start}-{season - 1}"}


def real_edge(p_fair: float, shift: float, dec: float) -> float:
    """Edge in % at decimal price dec, using the market's fair chance shifted by the bet type's record."""
    return round((sigmoid(logit(p_fair) + shift) * dec - 1) * 100, 1)


# Model picks on the moneyline and the spread are SUGGESTED when the model's own edge is at least this big
# (Mason, Oct 5: "suggest bets when the edge is pretty good on the ML or the spread"). They're shown with their
# real record (model_record) and ranked by real_edge like everything else. 5% chosen as "pretty good" up front;
# 8%+ looked better in 2016-25 (ML +2.9%, spread +0.4%) but choosing the cutoff that looks best is fooling ourselves.
MODEL_MIN_EDGE = 5.0
ND = NormalDist()


def model_margin(p: float) -> float:
    """Elo win probability -> expected home margin in points (25 Elo per point)."""
    return 400 * math.log10(p / (1 - p)) / 25


def spread_cover(p: float, line: float, sigma: float, blend_w: float) -> float:
    """Model-blend chance the HOME team covers. line = expected home margin (nflverse spread_line, + = home
    favored); the blend mixes our margin with the market's like the moneyline blend; sigma = margin spread."""
    bm = blend_w * model_margin(p) + (1 - blend_w) * line
    return ND.cdf((bm - line) / sigma)


def _model_bets(recs, blend_w, sigma, start, season):
    """Walk-forward model picks at closing prices: yields (kind, model_ev, market_p_of_side, dec, won/None)."""
    for r in recs:
        g = r["g"]
        if not (start <= g["season"] < season) or g["hs"] is None:
            continue
        if g["hml"] and g["aml"] and g["hs"] != g["as"]:
            f = devig(g["hml"], g["aml"])
            bl = blend_w * r["p"] + (1 - blend_w) * f
            dh, da = am_to_dec(g["hml"]), am_to_dec(g["aml"])
            evh, eva = bl * dh - 1, (1 - bl) * da - 1
            home = evh >= eva
            yield "ml", max(evh, eva), (f if home else 1 - f), (dh if home else da), (g["hs"] > g["as"]) == home
        if g["spread"] is not None and g["hso"] and g["aso"]:
            pc = spread_cover(r["p"], g["spread"], sigma, blend_w)
            pm = devig(g["hso"], g["aso"])
            dh, da = am_to_dec(g["hso"]), am_to_dec(g["aso"])
            evh, eva = pc * dh - 1, (1 - pc) * da - 1
            home = evh >= eva
            margin = g["hs"] - g["as"]
            won = None if margin == g["spread"] else (margin > g["spread"]) == home
            yield "spread", max(evh, eva), (pm if home else 1 - pm), (dh if home else da), won


def fit_spread_shift(recs, blend_w, sigma, season, start=LEAN_FIT_FROM) -> dict:
    """Like fit_lean_shift, for the model's spread picks (from its first unseen season)."""
    off, y = [], []
    for kind, ev, pm, _, won in _model_bets(recs, blend_w, sigma, start, season):
        if kind == "spread" and ev > 0 and won is not None:
            off.append(logit(pm))
            y.append(1.0 if won else 0.0)
    beta, se = _fit_offset_logit([[1.0]] * len(y), off, y)
    return {"shift": round(beta[0], 5), "se": round(se[0], 5), "n": len(y), "won": int(sum(y)),
            "seasons": f"{start}-{season - 1}"}


def model_record(recs, blend_w, sigma, season, start=LEAN_FIT_FROM) -> dict:
    """What suggested model picks (model edge >= MODEL_MIN_EDGE) returned at closing prices, per $1."""
    out = {}
    for kind in ("ml", "spread"):
        rets = [0.0 if won is None else (dec - 1 if won else -1.0)
                for k, ev, _, dec, won in _model_bets(recs, blend_w, sigma, start, season)
                if k == kind and ev * 100 >= MODEL_MIN_EDGE]
        out[kind] = {"n": len(rets), "roi": round(sum(rets) / len(rets) * 100, 1) if rets else None,
                     "seasons": f"{start}-{season - 1}"}
    return out


def wind_pick(g, s: dict | None, wind_shift: float) -> dict | None:
    """The under to bet on a wind signal: line, the price you'd pay (your best Kalshi/Polymarket offer when it
    matches the sportsbooks' line, else sportsbook odds; finished games: the closing price, as in the
    backtests) and its realistic edge in %."""
    u = (s or {}).get("total", {}).get("under")
    fair = (s or {}).get("fair", {})
    if u and "over" in fair and u.get("point") == fair.get("totalPoint"):
        point, pf, dec, price = u["point"], 1 - fair["over"], u["dec"], {"cents": u["cents"], "book": u["book"]}
    elif g["tot"] is not None and g["oo"] and g["uo"]:
        point, pf, dec, price = g["tot"], 1 - devig(g["oo"], g["uo"]), am_to_dec(g["uo"]), {"odds": int(g["uo"])}
    else:
        return None
    return {"point": point, "fairUnder": round(pf, 4), "edge": real_edge(pf, wind_shift, dec), "dec": round(dec, 4),
            **price}


def ko_label(ko: datetime) -> str:
    return f"{ko:%a} {ko:%b} {ko.day} · {ko.strftime('%I:%M').lstrip('0')} {ko:%p} CT"


def settle(won, dec: float) -> float:
    """Flat 1-unit bet: won True/False/None (push)."""
    return 0.0 if won is None else (dec - 1.0 if won else -1.0)


def game_row(r, blend_w: float, wind_log: dict, shop: dict, now: datetime, shifts: dict | None = None) -> dict:
    """shifts: {"wind": fit_wind_shift(...), "lean": fit_lean_shift(...)} for realistic pick edges."""
    g = r["g"]
    p = r["p"]
    ko = kickoff_ct(g)
    final = g["hs"] is not None
    row = {
        "id": g["gid"], "wk": g["week"], "type": g["type"],
        "ko": ko_label(ko), "koIso": ko.isoformat(timespec="minutes"), "date": g["date"],
        "status": "final" if final else ("live" if ko <= now else "upcoming"),
        "away": g["away"], "home": g["home"],
        "awayName": TEAM_NAME.get(g["away"], g["away"]),
        "homeName": TEAM_NAME.get(g["home"], g["home"]),
        "roof": g["roof"] or "retractable", "stadium": g["stadium"], "neutral": g["neutral"],
        "as": g["as"], "hs": g["hs"],
        "pElo": round(p, 4),
        "eloLine": round(400 * math.log10(p / (1 - p)) / 25, 1),   # + = home favored
        "notes": [],
    }
    if r["hflag"]:
        row["notes"].append(f"{TEAM_NAME[g['home']]} QB {g['hqbn']} isn't the usual starter")
    if r["aflag"]:
        row["notes"].append(f"{TEAM_NAME[g['away']]} QB {g['aqbn']} isn't the usual starter")
    rest = g["hrest"] - g["arest"]
    if abs(rest) >= 3:
        fav = g["home"] if rest > 0 else g["away"]
        row["notes"].append(f"{TEAM_NAME[fav]} have {abs(rest):.0f} more days of rest")

    home_won = None
    if final:
        home_won = True if g["hs"] > g["as"] else False if g["hs"] < g["as"] else None
        if home_won is not None:
            row["eloRight"] = (p >= 0.5) == home_won

    # ---- market ----
    # Upcoming games with live odds: fair price = median no-vig across sportsbooks, and the
    # price you'd actually pay = your best exchange offer, fees included (odds.py).
    # Finished games: always the nflverse closing line, the same as the backtests.
    s = shop.get(g["gid"]) if not final else None
    if s:
        row["shop"] = s
        row["gaps"] = [dict(o, mk=mk, side=side) for mk in ("ml", "spread", "total")
                       for side, o in s[mk].items() if o.get("ev") is not None and o["ev"] >= GAP_EV
                       and s["books"] >= GAP_MIN_BOOKS]
    mine = (s or {}).get("ml", {})
    fair = (s or {}).get("fair", {}).get("home")
    src = "books" if fair is not None else "nflverse"
    if fair is not None and 0 < s["books"] < GAP_MIN_BOOKS and g["hml"] and g["aml"]:
        fair, src = None, "nflverse"      # too few books for a fair price (early-week lines): use the consensus line
    if fair is None and g["hml"] and g["aml"]:
        fair = devig(g["hml"], g["aml"])
    if "home" in mine and "away" in mine:
        dh, da = mine["home"]["dec"], mine["away"]["dec"]
    elif g["hml"] and g["aml"]:
        dh, da = am_to_dec(g["hml"]), am_to_dec(g["aml"])
    else:
        dh = da = None
    if fair is not None:
        bl = blend_w * p + (1 - blend_w) * fair
        m = {"fair": round(fair, 4), "blend": round(bl, 4), "lean": None, "src": src}
        if g["hml"] and g["aml"]:
            m["hml"], m["aml"] = int(g["hml"]), int(g["aml"])
    if fair is not None and dh:
        evh, eva = bl * dh - 1, (1 - bl) * da - 1
        if max(evh, eva) > 0:
            side = "home" if evh >= eva else "away"
            m["lean"] = side
            m["leanEv"] = round(max(evh, eva) * 100, 1)          # the model's own estimate
            m["leanDec"] = round(dh if side == "home" else da, 4)
            if shifts:                                             # what leans like this have really returned
                m["leanEdge"] = real_edge(fair if side == "home" else 1 - fair, shifts["lean"]["shift"],
                                          dh if side == "home" else da)
            if side in mine:
                m["leanBook"], m["leanCents"] = mine[side]["book"], mine[side]["cents"]
            else:
                m["leanOdds"] = int(g["hml"] if side == "home" else g["aml"])
            if final:
                won = None if home_won is None else (home_won if side == "home" else not home_won)
                m["leanUnits"] = round(settle(won, dh if side == "home" else da), 3)
    if fair is not None:
        if final and home_won is not None:
            m["mktRight"] = (fair >= 0.5) == home_won
        row["mkt"] = m
    # Closing fair prices (nflverse) for the bet tracker's "vs close": once a game kicks off,
    # these are the closing lines.
    cf = {}
    if g["hml"] and g["aml"]:
        cf["home"] = round(devig(g["hml"], g["aml"]), 4)
    if g["spread"] is not None:
        cf["spreadLine"] = g["spread"]
        if g["hso"] and g["aso"]:
            cf["spreadHome"] = round(devig(g["hso"], g["aso"]), 4)
    if g["tot"] is not None:
        cf["total"] = g["tot"]
        if g["oo"] and g["uo"]:
            cf["over"] = round(devig(g["oo"], g["uo"]), 4)
    if cf:
        row["closeFair"] = cf
    f = (s or {}).get("fair", {})
    if g["spread"] is not None:
        row["spread"] = {"line": g["spread"], "ho": g["hso"], "ao": g["aso"]}
    elif "spreadPoint" in f:
        row["spread"] = {"line": -f["spreadPoint"], "ho": None, "ao": None}   # API gives the home point
    if g["tot"] is not None:
        row["total"] = {"line": g["tot"], "oo": g["oo"], "uo": g["uo"]}
    elif "totalPoint" in f:
        row["total"] = {"line": f["totalPoint"], "oo": None, "uo": None}

    # ---- model spread pick: our margin vs the line, priced where you'd bet (finished games: closing price) ----
    L = (row.get("spread") or {}).get("line")
    if shifts and L is not None:
        offers = (s or {}).get("spread", {})
        if s and s["books"] >= GAP_MIN_BOOKS and f.get("spreadPoint") == -L and "spreadHome" in f:
            pm = f["spreadHome"]                       # sportsbooks' fair chance the home side covers
        elif g["hso"] and g["aso"]:
            pm = devig(g["hso"], g["aso"])
        else:
            pm = 0.5
        opts = {}
        for side, pt, am in (("home", -L, g["hso"]), ("away", L, g["aso"])):
            o = offers.get(side)
            if o and o.get("point") == pt:
                opts[side] = (o["dec"], {"cents": o["cents"], "book": o["book"]})
            elif am:
                opts[side] = (am_to_dec(am), {"odds": int(am)})
        if len(opts) == 2:
            pc = spread_cover(p, L, shifts["sigma"], blend_w)
            evs = {"home": pc * opts["home"][0] - 1, "away": (1 - pc) * opts["away"][0] - 1}
            side = max(evs, key=evs.get)
            dec, price = opts[side]
            sl = {"side": side, "point": -L if side == "home" else L, "ev": round(evs[side] * 100, 1), "dec": round(dec, 4),
                  "edge": real_edge(pm if side == "home" else 1 - pm, shifts["spread"]["shift"], dec), **price}
            if final:
                margin = g["hs"] - g["as"]
                sl["units"] = round(settle(None if margin == L else (margin > L) == (side == "home"), dec), 3)
            row["spreadLean"] = sl

    # ---- wind watch ----
    w = wind_log.get(g["gid"])
    if w and g["roof"] not in ("dome", "closed"):
        row["wind"] = w["wind"]
        row["windSrc"] = w["src"]
        row["windAsof"] = w["asof"]
        if w["wind"] >= WIND_MPH:
            row["signal"] = "under" if g["roof"] in OUTDOOR else "roof"
            if shifts:
                wp = wind_pick(g, s, shifts["wind"]["shift"])
                if wp:
                    row["windPick"] = wp
            if row["signal"] == "under" and final and g["tot"] is not None and g["uo"]:
                tot = g["hs"] + g["as"]
                won = None if tot == g["tot"] else tot < g["tot"]
                row["underUnits"] = round(settle(won, am_to_dec(g["uo"])), 3)
    if g["wind"] is not None and final:
        row["windRecorded"] = g["wind"]
    if shifts:
        row["picks"] = P.game_picks(row, MODEL_MIN_EDGE)
    return row


def season_models(games: list, season: int, site_recs: list, site_blend: float) -> list:
    """This season's version of the Method page's model table: finished games at closing moneylines, scored the
    same way as the 2016-2025 backtest (rift_real.collect / log_loss / accuracy / roi)."""
    import rift_real as RR
    saved = json.loads(PARAMS.read_text(encoding="utf-8"))
    params, w_elo = saved["params"], saved.get("blend_w", 0.22)
    elo_core = run(games, **dict(params, rest_pts=0.0, qb_pen=0.0))[0]
    elo_full = run(games, **params)[0]
    out = []

    def add(label, recs, blend=None, kind="model"):
        P, M, O, G = RR.collect(recs, {season}, blend)
        if not P:
            return
        b0, _, r0 = RR.roi(P, G, O, 0.0)
        b3, _, r3 = RR.roi(P, G, O, 0.03)
        out.append({"label": label, "kind": kind, "n": len(P), "ll": round(RR.log_loss(P, O), 4),
                    "acc": round(RR.accuracy(P, O), 4), "roi": round(r0 * 100, 1), "bets": b0,
                    "roi3": round(r3 * 100, 1), "bets3": b3})

    add("Elo, core only", elo_core)
    add("+ rest + backup-QB flag", elo_full)
    add(f"Blend, {round(w_elo * 100)}% Elo (the old lean)", elo_full, w_elo)
    add("QB ratings + team efficiency (today’s model)", site_recs, kind="site")
    add(f"Blend, {round(site_blend * 100)}% of today’s model (its picks)", site_recs, site_blend, kind="site")
    P, M, O, _ = RR.collect(site_recs, {season})
    if M:
        out.append({"label": "Closing market", "kind": "market", "n": len(M),
                    "ll": round(RR.log_loss(M, O), 4), "acc": round(RR.accuracy(M, O), 4)})
    return out


def season_summary(rows: list) -> dict:
    fin = [x for x in rows if x["status"] == "final"]
    with_mkt = [x for x in fin if "mkt" in x and "mktRight" in x["mkt"]]

    def ll(ps, ys):
        return -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(ps, ys)) / len(ps)

    out = {"final": len(fin), "withLines": len(with_mkt)}
    if with_mkt:
        ys = [1.0 if x["hs"] > x["as"] else 0.0 for x in with_mkt]
        out["eloAcc"] = sum(x["eloRight"] for x in with_mkt) / len(with_mkt)
        out["mktAcc"] = sum(x["mkt"]["mktRight"] for x in with_mkt) / len(with_mkt)
        out["eloLL"] = ll([x["pElo"] for x in with_mkt], ys)
        out["mktLL"] = ll([x["mkt"]["fair"] for x in with_mkt], ys)
    leans = [x["mkt"]["leanUnits"] for x in fin if "mkt" in x and "leanUnits" in x["mkt"]]
    out["lean"] = {"n": len(leans), "units": round(sum(leans), 2),
                   "won": sum(1 for u in leans if u > 0), "lost": sum(1 for u in leans if u < 0)}
    unders = [x["underUnits"] for x in fin if "underUnits" in x]
    out["wind"] = {"n": len(unders), "units": round(sum(unders), 2),
                   "won": sum(1 for u in unders if u > 0), "lost": sum(1 for u in unders if u < 0)}
    by = []
    for wk in sorted({x["wk"] for x in rows}):
        f = [x for x in fin if x["wk"] == wk]
        if not f:
            continue
        lu = [x["mkt"]["leanUnits"] for x in f if "mkt" in x and "leanUnits" in x["mkt"]]
        wu = [x["underUnits"] for x in f if "underUnits" in x]
        by.append({"wk": wk, "games": len(f),
                   "eloRight": sum(1 for x in f if x.get("eloRight")),
                   "mktRight": sum(1 for x in f if x.get("mkt", {}).get("mktRight")),
                   "decided": sum(1 for x in f if "eloRight" in x),
                   "leanN": len(lu), "leanUnits": round(sum(lu), 2),
                   "windN": len(wu), "windUnits": round(sum(wu), 2)})
    out["byWeek"] = by
    return out


def team_history(recs, season: int, ratings: dict, today: str) -> dict:
    """Each team's Elo before every played game of the last two seasons, then now:
    [date, rating, opponent, season]."""
    hist = defaultdict(list)
    for r in recs:
        g = r["g"]
        if g["season"] < season - 1 or g["hs"] is None:
            continue
        hist[g["home"]].append([g["date"], round(r["rh"], 1), g["away"], g["season"]])
        hist[g["away"]].append([g["date"], round(r["ra"], 1), g["home"], g["season"]])
    for t, v in ratings.items():
        hist[t].append([today, round(v, 1), None, season])
    return hist


def team_table(games, model_run, season: int, ratings: dict) -> list:
    fin = [g for g in games if g["season"] == season and g["hs"] is not None]
    last_wk = max((g["week"] for g in fin), default=None)
    prev = {}
    if last_wk is not None:
        cut = [g for g in games if g["season"] < season
               or (g["season"] == season and g["week"] < last_wk)]
        prev = model_run(cut)[1]
    rec = defaultdict(lambda: [0, 0, 0])
    for g in fin:
        for t, pf, pa in ((g["home"], g["hs"], g["as"]), (g["away"], g["as"], g["hs"])):
            rec[t][0 if pf > pa else 1 if pf < pa else 2] += 1
    rows = []
    for t, v in sorted(ratings.items(), key=lambda kv: -kv[1]):
        if t not in TEAM_NAME:
            continue
        w, l, ti = rec[t]
        rows.append({"team": t, "name": TEAM_NAME[t], "rating": round(v, 1),
                     "delta": round(v - prev.get(t, v), 1) if prev else 0.0,
                     "record": f"{w}-{l}" + (f"-{ti}" if ti else "")})
    return rows, last_wk


def pick_model(season: int, refresh: bool):
    """The QB + team-efficiency model when its settings and stats are available, else the
    original Elo. Returns (run(games) -> (recs, ratings), blend weight, home field, name)."""
    saved = json.loads(PARAMS.read_text(encoding="utf-8"))
    try:
        ensure_stats(season, refresh_current=refresh)
        m = QBModel()
        return m.run, m.blend_w, m.params.get("hfa", 55.0), "qb+epa"
    except Exception as exc:
        print(f"  QB model unavailable ({exc}); using the original Elo")
        params = saved["params"]
        return (lambda gs: run(gs, **params)[:2]), saved["blend_w"], params.get("hfa", 55.0), "elo"


def build(now: datetime, refresh_stats: bool = False, pregame: bool = False) -> dict:
    """pregame: a game-day check; if a game kicks off within alerts.PREGAME_HOURS, pull fresh prices even if the
    odds cache is recent (3 credits), so the last look before kickoff uses current Kalshi/Polymarket prices."""
    games = load(DATA)
    season = max(g["season"] for g in games)
    model_run, blend_w, hfa, model_name = pick_model(season, refresh_stats)
    recs, ratings = model_run(games)
    wind_log = update_wind_log(games, season, now)
    soon = pregame and any(g["season"] == season and g["hs"] is None
                           and now < kickoff_ct(g) <= now + timedelta(hours=alerts.PREGAME_HOURS) for g in games)
    if soon:
        print("Game-day check: a game kicks off soon, pulling fresh prices.")
    odds = get_odds(force=soon)            # None unless ODDS_API_KEY is set or a cache exists
    shop = match_games(odds, games, TEAM_NAME)
    # Kalshi/Polymarket moneylines straight from their free feeds (no key, so GitHub gets them too)
    import exchanges
    live = exchanges.current(games, TEAM_NAME)
    add_live_exchanges(shop, live, games)
    if shop:
        log_snapshots(shop, games)

    sigma = fit_sigma(games, DEV["spread"])
    shifts = {"wind": fit_wind_shift(games, season), "lean": fit_lean_shift(recs, blend_w, season),
              "spread": fit_spread_shift(recs, blend_w, sigma, season), "sigma": sigma}
    record = model_record(recs, blend_w, sigma, season)
    rows = [game_row(r, blend_w, wind_log, shop, now, shifts) for r in recs if r["g"]["season"] == season]
    # every suggestion is logged the first time it's shown, then graded at that price (picks.py)
    pick_log = P.update_log(rows, now.isoformat(timespec="minutes"))
    P.apply_log(rows, {g["gid"]: g for g in games}, pick_log)
    # key injuries on each card (ESPN feed; same "key player" rule as the phone alerts)
    try:
        import injury_watch
        inj = injury_watch.card_injuries(season, TEAM_NAME)
        for x in rows:
            if x["status"] != "final":
                x["injuries"] = {side: inj.get(x[side], [])[:6] for side in ("away", "home")}
    except Exception as exc:
        inj = None
        print(f"  injury feed unavailable ({exc})")
    unplayed = [x for x in rows if x["status"] != "final"]
    current = unplayed[0]["wk"] if unplayed else rows[-1]["wk"]
    teams, last_wk = team_table(games, model_run, season, ratings)
    hist = team_history(recs, season, ratings, now.date().isoformat())
    for t in teams:
        t["hist"] = hist[t["team"]]
    return {
        "updated": now.isoformat(timespec="minutes"),
        "updatedLabel": f"{now:%a} {now:%b} {now.day}, {now.strftime('%I:%M').lstrip('0')} {now:%p} CT",
        "season": season, "currentWeek": current, "deltaWeek": last_wk,
        "blendW": blend_w, "hfa": round(hfa, 1), "windMph": WIND_MPH, "model": model_name,
        "oddsFetched": odds["fetched"] if odds else None, "oddsGames": len(shop), "gapEv": GAP_EV,
        "gapBooks": GAP_MIN_BOOKS, "exchangeGames": len(live), "pickShifts": shifts, "injuriesOk": inj is not None,
        "modelMinEdge": MODEL_MIN_EDGE, "modelRecord": record, "unitPct": P.UNIT_PCT,
        "fees": EXCHANGE_FEE,
        "games": rows, "summary": dict(season_summary(rows), picks=P.scoreboard(rows),
                                       pickLogStarted=pick_log.get("_meta", {}).get("started"),
                                       models=season_models(games, season, recs, blend_w)),
        "teams": teams,
    }


def _between(text: str, start: str, end: str) -> str:
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0:
        sys.exit(f"Couldn't find {start} ... {end} in site/index.html")
    return text[i + len(start):j]


def bust_cache(stamp: str) -> None:
    """Tag asset links in site/*.html with a version (?v=...) so browsers fetch the new
    files after an update instead of reusing a saved copy (GitHub Pages lets them keep
    files for 10 minutes). Code files and the tab icon get a content hash; data.js gets the build stamp.
    (Browsers keep tab icons especially long: Edge kept showing the site's first, green favicon.svg.)"""
    h = lambda *p: hashlib.sha1(SITE.joinpath(*p).read_bytes()).hexdigest()[:8]
    ver = {"assets/app.js": h("assets", "app.js"), "assets/style.css": h("assets", "style.css"),
           "tab-icon.svg": h("tab-icon.svg"), "data.js": re.sub(r"\D", "", stamp)}
    pat = re.compile(r'(assets/app\.js|assets/style\.css|tab-icon\.svg|data\.js)(\?v=[^"]*)?"')
    for page in SITE.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        new = pat.sub(lambda m: f'{m.group(1)}?v={ver[m.group(1)]}"', text)
        if new != text:
            page.write_text(new, encoding="utf-8")


def write_site(data: dict) -> Path:
    """site/ is the website: static pages + assets, plus data.js written here.
    build/artifact-index.html is site/index.html without its document wrapper,
    because claude.ai adds its own when the page is published as an Artifact."""
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    (SITE / "data.js").write_text(f"window.EDGE={blob};\n", encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") == "true":     # public site only; claude.ai pushes new versions itself
        bust_cache(data["updated"])
    index = (SITE / "index.html").read_text(encoding="utf-8")
    ARTIFACT_INDEX.parent.mkdir(exist_ok=True)
    head = _between(index, "<!--head-->", "<!--/head-->").strip()
    ARTIFACT_INDEX.write_text(head + "\n" + _between(index, "<!--body-->", "<!--/body-->").strip() + "\n",
                              encoding="utf-8")
    return SITE / "data.js"


def main() -> None:
    if "--fetch" in sys.argv:
        try:
            fetch_games()
        except Exception as exc:
            print(f"Download failed ({exc}); using the existing data/games.csv")
    now = now_central()
    try:                                     # injury news first: it may pull fresh odds for the build
        import injury_watch
        import alerts as _alerts
        if _alerts.topic():
            if "--fetch" in sys.argv:
                injury_watch.refresh_current_files(now.year if now.month >= 3 else now.year - 1)
            n = injury_watch.run(now)
            if n:
                print(f"Sent {n} injury alert(s).")
    except Exception as exc:
        print(f"Injury watch failed ({exc}); continuing with the rebuild.")
    pregame = "--pregame" in sys.argv        # game-day check shortly before kickoff (scheduled task)
    data = build(now, refresh_stats="--fetch" in sys.argv, pregame=pregame)
    out = write_site(data)
    try:
        sent = alerts.run(data)            # phone alerts via ntfy; does nothing without a channel
        if pregame:
            sent += alerts.pregame(data)   # one "Kickoff soon" summary per kickoff window
        if sent:
            print(f"Sent {sent} phone alert(s).")
    except Exception as exc:
        print(f"Phone alerts failed ({exc}); the site was still rebuilt.")
    s = data["summary"]
    wk = [x for x in data["games"] if x["wk"] == data["currentWeek"]]
    print(f"Wrote {out.relative_to(ROOT)}: {data['season']} week {data['currentWeek']} "
          f"({len(wk)} games, {sum(1 for x in wk if 'mkt' in x)} with lines, "
          f"{sum(1 for x in wk if x.get('signal') == 'under')} wind under signals). "
          f"Season: {s['final']} final; wind unders {s['wind']['won']}-{s['wind']['lost']} "
          f"({s['wind']['units']:+.2f}u); Elo leans {s['lean']['units']:+.2f}u on {s['lean']['n']}.")


if __name__ == "__main__":
    main()
