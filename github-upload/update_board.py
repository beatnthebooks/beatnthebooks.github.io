"""
update_board.py
===============
Refresh the Edge Board with the latest data in one command:

  1. re-run the Elo model over data/games.csv (every game since 1999)
  2. take the next unplayed games that have closing lines
  3. pull a live wind forecast for outdoor games in the next 8 days (Open-Meteo)
  4. write the real ratings, those games and the wind watch into web/edge-board.html

Usage:
    python3 update_board.py            # reuse the tuned settings in results/current_ratings.json
    python3 update_board.py --retune   # re-tune on 2006-2015 first (a few seconds)

Get fresh data first (nflverse updates games.csv through the season):
    curl -L -o data/games.csv https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv

The board notices the new data the next time it's opened: games and ratings
refresh, and your bankroll / Kelly / influence settings are kept.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from edge_lab import load as edge_load
from rift_real import TEAM_NAME, TRAIN, best_blend, collect, load, run, tune
from wind_check import STADIUMS, WIND_MPH, forecast, game_wind, stadium_key

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "games.csv"
HTML = ROOT / "web" / "edge-board.html"
PARAMS = ROOT / "results" / "current_ratings.json"


def now_central() -> datetime:
    """Current Central time as a naive datetime."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)
    except Exception:            # no tz database (e.g. Windows without tzdata)
        return datetime.now()     # assumes this computer is set to Central time


def kickoff_label(date: str, time: str, now: datetime) -> str:
    """games.csv kickoffs are Eastern; Central is always one hour earlier."""
    ko = datetime.fromisoformat(f"{date}T{time}") - timedelta(hours=1)
    day = "" if ko.date() == now.date() else ko.strftime("%a ")
    label = f"{day}{ko.strftime('%I:%M').lstrip('0')} CT"
    if now >= ko:
        label += " · started"
    return label


def wind_watch(now: datetime, season: int) -> list:
    """Upcoming outdoor / retractable-roof games in the next 8 days with a live
    wind forecast (Open-Meteo, no key). The tested rule: UNDER when the forecast
    wind over the kickoff hour + 3 hours is >= WIND_MPH. See wind_check.py."""
    horizon = (now + timedelta(days=8)).date().isoformat()
    today = now.date().isoformat()
    picks = [dict(g, sid=stadium_key(g)) for g in edge_load(DATA)
             if g["season"] == season and g["hs"] is None and today <= g["date"] <= horizon
             and g["roof"] not in ("dome", "closed")]
    picks = [g for g in picks if g["sid"] in STADIUMS]
    series = {}
    for sid in {g["sid"] for g in picks}:
        lat, lon = STADIUMS[sid]
        try:
            series[sid] = forecast(lat, lon)
        except Exception as exc:            # offline etc.: board still updates
            print(f"  wind forecast unavailable for {sid}: {exc}")
    out = []
    for i, g in enumerate(picks, 1):
        wind = game_wind(series[g["sid"]], g["date"], g["time"]) if g["sid"] in series else None
        roof = g["roof"] or "retractable"
        if wind is None:
            signal = "unknown"
        elif wind < WIND_MPH:
            signal = "none"
        else:
            signal = "under" if roof in ("outdoors", "open") else "roof"
        out.append({
            "id": i, "away": TEAM_NAME[g["away"]], "home": TEAM_NAME[g["home"]],
            "when": kickoff_label(g["date"], g["time"], now), "roof": roof,
            "wind": None if wind is None else round(wind, 1), "signal": signal,
            "total": g["tot"], "underOdds": None if g["uo"] is None else int(g["uo"]),
        })
    return out


def main() -> None:
    games = load(DATA)

    if "--retune" in sys.argv or not PARAMS.exists():
        print("Tuning on 2006-2015 ...")
        core, rest_pts, qb_pen = tune(games)
        params = dict(core, rest_pts=rest_pts, qb_pen=qb_pen)
        recs, _, _ = run(games, **params)
        p_tr, m_tr, o_tr, _ = collect(recs, TRAIN)
        blend_w = best_blend(p_tr, m_tr, o_tr)[0]
    else:
        saved = json.loads(PARAMS.read_text(encoding="utf-8"))
        params, blend_w = saved["params"], saved["blend_w"]

    recs, ratings, info = run(games, **params)
    hfa = info["hfa_now"]
    now = now_central()
    season = max(g["season"] for g in games)
    upcoming = [r for r in recs
                if r["g"]["season"] == season and r["g"]["hs"] is None
                and r["g"]["hml"] is not None and r["g"]["aml"] is not None][:16]

    board_games = []
    for i, r in enumerate(upcoming, 1):
        g = r["g"]
        rest = max(-35.0, min(35.0, params.get("rest_pts", 0) * (g["hrest"] - g["arest"])))
        qb = params.get("qb_pen", 0) * (r["aflag"] - r["hflag"])
        notes = []
        if r["hflag"]:
            notes.append(f"{TEAM_NAME[g['home']]} QB {g['hqbn']} not usual starter")
        if r["aflag"]:
            notes.append(f"{TEAM_NAME[g['away']]} QB {g['aqbn']} not usual starter")
        if rest:
            notes.append(f"rest edge {rest:+.0f}")
        board_games.append({
            "id": i, "away": TEAM_NAME[g["away"]], "home": TEAM_NAME[g["home"]],
            "awayOdds": int(g["aml"]), "homeOdds": int(g["hml"]),
            "when": kickoff_label(g["date"], g["time"], now),
            "adj": round(rest + qb, 1), "note": "; ".join(notes),
            "modelHome": None, "manual": False,
        })

    totals = wind_watch(now, season)

    seed = {
        "ratings": {TEAM_NAME.get(t, t): round(v, 1) for t, v in ratings.items()},
        "homeAdv": round(hfa, 1), "blend": blend_w, "games": board_games,
        "totals": totals, "stamp": now.isoformat(timespec="minutes"),
    }
    html = HTML.read_text(encoding="utf-8")
    line = "const SEED=" + json.dumps(seed, separators=(",", ":")) + ";\n"
    new, n = re.subn(r"const SEED=[^\n]*\n", lambda _m: line, html)
    if n != 1:
        sys.exit("Couldn't find the SEED line in web/edge-board.html")
    HTML.write_text(new, encoding="utf-8")

    PARAMS.parent.mkdir(exist_ok=True)
    PARAMS.write_text(json.dumps({"params": params, "blend_w": blend_w,
                                  "hfa_now": hfa, "ratings": seed["ratings"]}, indent=2),
                      encoding="utf-8")
    flagged = sum(1 for t in totals if t["signal"] == "under")
    print(f"Board updated: {len(seed['ratings'])} team ratings, "
          f"{len(board_games)} upcoming games, {len(totals)} outdoor games on the wind watch "
          f"({flagged} under signals) (stamp {seed['stamp']}).")


if __name__ == "__main__":
    main()
