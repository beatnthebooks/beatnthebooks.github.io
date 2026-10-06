"""
picks.py
========
The "Bets to take" on each game card, the log of every suggestion the site made, and the season scoreboard.

  * game_picks(row): every bet on one game, best first by realistic edge (see weekly.real_edge). Wind unders,
    price gaps, and model picks on the moneyline/spread when the model's own edge >= MODEL_MIN_EDGE.
  * update_log(rows): data/pick_log.json keeps each suggestion the FIRST time it appears (price, edge, reasons)
    and its last price before kickoff. Frozen at kickoff, so the record can't be rewritten with hindsight.
  * apply_log(rows, games): finished and in-progress games show the suggestions as logged before kickoff, graded
    at the price first shown: won/lost, and whether that price beat the closing line (the best early sign of a
    real edge). Games played before the log existed (Oct 5, 2026) are reconstructed at closing prices and say so.
  * scoreboard(rows): the season record by kind of bet.

Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

from edge_lab import devig

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "data" / "pick_log.json"
EDGE_FROM = {"wind": 0, "roof": 0, "gap": 1, "lean": 2, "spread": 2}   # whose edge number shows when signals merge
UNIT_PCT = 2.0     # 1 unit = 2% of Mason's Kalshi bankroll (his rule, Oct 5 2026)


def units_for(p: dict) -> float:
    """Stake in units, scaled by how much evidence backs the kind of bet (and, for wind, how good the price is).
    Wind unders are the one tested signal; price gaps are unproven; model picks have lost money historically."""
    if not p.get("good"):
        return 0.0
    main, src = p["edgeFrom"], set(p.get("src", []))
    if main == "wind":
        return 1.5 if p["edge"] >= 6.0 else 1.0
    if main == "roof":                       # same signal, but only matters if the roof is open
        return 0.5
    if main == "gap":
        return 0.75 if src & {"lean", "spread"} else 0.5
    return 0.25                              # model pick on its own
KINDS = ("wind", "gap", "lean", "spread")                              # scoreboard rows (roof counts as wind)


def _pt(x) -> str:
    return f"{float(x):g}"


def _signed(x) -> str:
    return ("+" if x > 0 else "") + _pt(x)


def _price(o: dict) -> dict:
    return {"cents": o["cents"], "book": o["book"]} if o.get("cents") is not None else {"odds": o.get("odds")}


# ----------------------------------------------------------------------
# Picks for one game
# ----------------------------------------------------------------------

def game_picks(row: dict, min_model_edge: float) -> list:
    """Every bet on this game, best first by realistic edge. A bet suggested by two signals is listed once
    with both reasons. 'good' = worth taking (edge > 0, or a model pick strong enough to suggest)."""
    out = []
    team = lambda s: row["homeName"] if s == "home" else row["awayName"]
    final = row["status"] == "final"

    def add(p):
        e = next((x for x in out if x["key"] == p["key"]), None)
        if e is None:
            out.append(p)
            return
        e["src"] += p["src"]
        e["why"] += p["why"]
        if e.get("model") is None and p.get("model") is not None:
            e["model"], e["rec"] = p["model"], p.get("rec")
        e["suggested"] = e["suggested"] or p["suggested"]
        if EDGE_FROM[p["src"][0]] < EDGE_FROM[e["edgeFrom"]]:
            e.update(edge=p["edge"], price=p["price"], dec=p["dec"], edgeFrom=p["src"][0])

    has = lambda key: any(x["key"] == key for x in out)

    wp = row.get("windPick")
    if wp and row.get("signal") in ("under", "roof"):
        kind = "roof" if row["signal"] == "roof" else "wind"
        add({"key": f"total|under|{_pt(wp['point'])}", "mk": "total", "side": "under", "point": wp["point"],
             "text": f"Under {_pt(wp['point'])}", "edge": wp["edge"], "dec": wp["dec"], "edgeFrom": kind,
             "src": [kind], "price": _price(wp), "suggested": False,
             "why": [f"{row['wind']:.0f} mph wind {'forecast at kickoff' if final else 'forecast'}"
                     + (", only if the roof is open" if kind == "roof" else "")]})
    if not final:
        for x in row.get("gaps", []):
            if x["mk"] == "total":
                text = f"{'Over' if x['side'] == 'over' else 'Under'} {_pt(x['point'])}"
            else:
                text = team(x["side"]) + (f" {_signed(x['point'])}" if x["mk"] == "spread" else " to win")
            add({"key": f"{x['mk']}|{x['side']}|{'' if x['mk'] == 'ml' else _pt(x['point'])}", "mk": x["mk"],
                 "side": x["side"], "point": None if x["mk"] == "ml" else x["point"], "text": text,
                 "edge": x["ev"], "dec": x["dec"], "edgeFrom": "gap", "src": ["gap"], "price": _price(x),
                 "suggested": False, "why": [f"{x['ev']:.1f}% cheaper than the sportsbooks’ fair price"]})
    m = row.get("mkt") or {}
    if m.get("lean") and m.get("leanEdge") is not None:
        side, key = m["lean"], f"ml|{m['lean']}|"
        if m["leanEv"] >= min_model_edge or has(key):
            pm = row["pElo"] if side == "home" else 1 - row["pElo"]
            fair = m["fair"] if side == "home" else 1 - m["fair"]
            price = {"cents": m["leanCents"], "book": m["leanBook"]} if m.get("leanCents") is not None \
                else {"odds": m.get("leanOdds")}
            add({"key": key, "mk": "ml", "side": side, "point": None, "text": f"{team(side)} to win",
                 "edge": m["leanEdge"], "dec": m["leanDec"], "edgeFrom": "lean", "src": ["lean"], "price": price,
                 "model": m["leanEv"], "rec": "ml", "suggested": m["leanEv"] >= min_model_edge,
                 "why": [f"our model gives them {round(pm * 100)}% to win, the market {round(fair * 100)}%"]})
    sl = row.get("spreadLean")
    if sl:
        key = f"spread|{sl['side']}|{_pt(sl['point'])}"
        if sl["ev"] >= min_model_edge or has(key):
            mine = row["eloLine"] * (1 if sl["side"] == "home" else -1)
            line = -sl["point"]
            add({"key": key, "mk": "spread", "side": sl["side"], "point": sl["point"],
                 "text": f"{team(sl['side'])} {_signed(sl['point'])}", "edge": sl["edge"], "dec": sl["dec"],
                 "edgeFrom": "spread", "src": ["spread"], "price": _price(sl), "model": sl["ev"], "rec": "spread",
                 "suggested": sl["ev"] >= min_model_edge,
                 "why": [f"our model has them {'winning' if mine >= 0 else 'losing'} by {abs(mine):.1f}; "
                         f"the line says {'winning' if line >= 0 else 'losing'} by {_pt(abs(line))}"]})
    for p in out:
        p["good"] = p["edge"] > 0 or p["suggested"]
        p["src"] = list(dict.fromkeys(p["src"]))
        p["units"] = units_for(p)
    out.sort(key=lambda p: -p["edge"])
    return out


# ----------------------------------------------------------------------
# Grading at the price first shown
# ----------------------------------------------------------------------

def grade(p: dict, g: dict) -> dict:
    """Result (units on a 1-unit bet at p['dec']) and the price vs the closing line for a finished game g
    (nflverse: closing moneyline, spread_line = expected home margin, total, with their odds)."""
    hs, as_, mk, side, pt = g["hs"], g["as"], p["mk"], p["side"], p.get("point")
    if mk == "ml":
        won = None if hs == as_ else (hs > as_) == (side == "home")
    elif mk == "spread":
        margin = (hs - as_) if side == "home" else (as_ - hs)
        won = None if margin + pt == 0 else margin + pt > 0
    else:
        tot = hs + as_
        won = None if tot == pt else (tot < pt if side == "under" else tot > pt)
    out = {"units": 0.0 if won is None else round(p["dec"] - 1 if won else -1.0, 3), "won": won}

    pc = pts = None                     # closing fair chance of this exact bet; points better than the close
    if mk == "ml" and g["hml"] and g["aml"]:
        f = devig(g["hml"], g["aml"])
        pc = f if side == "home" else 1 - f
    elif mk == "spread" and g["spread"] is not None:
        pts = pt - (-g["spread"] if side == "home" else g["spread"])
        if pts == 0 and g["hso"] and g["aso"]:
            f = devig(g["hso"], g["aso"])
            pc = f if side == "home" else 1 - f
    elif mk == "total" and g["tot"] is not None:
        pts = (pt - g["tot"]) if side == "under" else (g["tot"] - pt)
        if pts == 0 and g["oo"] and g["uo"]:
            f = devig(g["oo"], g["uo"])
            pc = f if side == "over" else 1 - f
    if pc is not None:
        out["clv"] = round((pc * p["dec"] - 1) * 100, 1)       # value vs the close, % (> 0 = beat it)
        out["beat"] = out["clv"] > 0
    elif pts:
        out["clvPts"] = pts
        out["beat"] = pts > 0
    return out


# ----------------------------------------------------------------------
# The log
# ----------------------------------------------------------------------

def load_log() -> dict:
    return json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}


def update_log(rows: list, now_iso: str, log: dict | None = None) -> dict:
    """Record each good pick on games not yet started: first sighting kept, last price refreshed."""
    log = load_log() if log is None else log
    changed = "_meta" not in log
    log.setdefault("_meta", {"started": now_iso})            # games kicking off after this are judged by the log
    for r in rows:
        if r["status"] != "upcoming":
            continue                                           # frozen at kickoff
        for p in r.get("picks", []):
            if not p["good"]:
                continue
            snap = {"ts": now_iso, "dec": p["dec"], "price": p["price"], "edge": p["edge"]}
            e = log.setdefault(r["id"], {}).get(p["key"])
            if e is None:
                keep = {k: p[k] for k in ("mk", "side", "point", "text", "src", "edgeFrom", "why", "model", "rec",
                                          "suggested", "units") if k in p}
                log[r["id"]][p["key"]] = {"pick": keep, "first": snap, "last": snap}
                changed = True
            elif e["last"] != snap:
                e["last"] = snap
                changed = True
    if changed:
        LOG.parent.mkdir(exist_ok=True)
        LOG.write_text(json.dumps(log, indent=1, sort_keys=True), encoding="utf-8")
    return log


def apply_log(rows: list, games_by_gid: dict, log: dict) -> None:
    """Started games show their logged suggestions (as first shown); finished games are graded. Finished games
    with nothing logged keep their picks recomputed at the closing price, marked as reconstructed."""
    started = log.get("_meta", {}).get("started")
    for r in rows:
        if r["status"] == "upcoming":
            continue
        g = games_by_gid.get(r["id"])
        entries = log.get(r["id"])
        if entries or (started and r["koIso"] >= started):  # the log was running: it alone says what was shown
            entries = entries or {}
            ps = []
            for key, e in entries.items():
                p = dict(e["pick"], key=key, dec=e["first"]["dec"], price=e["first"]["price"],
                         edge=e["first"]["edge"], good=True, logged=e["first"]["ts"])
                p.setdefault("units", units_for(p))       # picks logged before unit sizing existed
                ps.append(p)
            ps.sort(key=lambda p: -p["edge"])
            r["picks"] = ps
        else:
            for p in r.get("picks", []):
                p["reconstructed"] = True
        if r["status"] == "final" and g is not None and g["hs"] is not None:
            for p in r.get("picks", []):
                if p["good"]:
                    gr = grade(p, g)
                    if p.get("reconstructed"):            # priced at the close already: no closing-line test
                        gr = {"units": gr["units"], "won": gr["won"]}
                    p["grade"] = gr


# ----------------------------------------------------------------------
# Scoreboard
# ----------------------------------------------------------------------

def scoreboard(rows: list) -> dict:
    """Season record of graded suggestions, by the kind of bet whose edge ranked it (wind > gap > model)."""
    out = {k: {"n": 0, "won": 0, "lost": 0, "push": 0, "units": 0.0, "sized": 0.0, "staked": 0.0, "live": 0,
               "beat": 0, "judged": 0, "clvSum": 0.0, "clvN": 0} for k in KINDS + ("all",)}
    for r in rows:
        for p in r.get("picks", []):
            gr = p.get("grade")
            if not gr:
                continue
            kind = "wind" if p["edgeFrom"] == "roof" else p["edgeFrom"]
            for k in (kind, "all"):
                s = out[k]
                s["n"] += 1
                s["units"] += gr["units"]                         # per 1-unit bet (flat)
                size = p.get("units") or units_for(dict(p, good=True))
                s["sized"] += gr["units"] * size                  # as sized by the unit rules
                s["staked"] += size
                s["won" if gr["won"] else "push" if gr["won"] is None else "lost"] += 1
                if not p.get("reconstructed"):
                    s["live"] += 1
                    if gr.get("beat") is not None:
                        s["judged"] += 1
                        s["beat"] += gr["beat"]
                    if gr.get("clv") is not None:
                        s["clvSum"] += gr["clv"]
                        s["clvN"] += 1
    for s in out.values():
        s["units"] = round(s["units"], 3)
        s["sized"], s["staked"] = round(s["sized"], 3), round(s["staked"], 2)
        total = s.pop("clvSum")
        s["clvAvg"] = round(total / s["clvN"], 1) if s["clvN"] else None
    return out
