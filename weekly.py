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

import alerts
from edge_lab import devig, load
from odds import EXCHANGE_FEE, get_odds, log_snapshots, match_games
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

def ko_label(ko: datetime) -> str:
    return f"{ko:%a} {ko:%b} {ko.day} · {ko.strftime('%I:%M').lstrip('0')} {ko:%p} CT"


def settle(won, dec: float) -> float:
    """Flat 1-unit bet: won True/False/None (push)."""
    return 0.0 if won is None else (dec - 1.0 if won else -1.0)


def game_row(r, blend_w: float, wind_log: dict, shop: dict, now: datetime) -> dict:
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
                       for side, o in s[mk].items() if o.get("ev") is not None and o["ev"] >= GAP_EV]
    mine = (s or {}).get("ml", {})
    fair = (s or {}).get("fair", {}).get("home")
    src = "books" if fair is not None else "nflverse"
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
            m["leanEv"] = round(max(evh, eva) * 100, 1)
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

    # ---- wind watch ----
    w = wind_log.get(g["gid"])
    if w and g["roof"] not in ("dome", "closed"):
        row["wind"] = w["wind"]
        row["windSrc"] = w["src"]
        row["windAsof"] = w["asof"]
        if w["wind"] >= WIND_MPH:
            row["signal"] = "under" if g["roof"] in OUTDOOR else "roof"
            if row["signal"] == "under" and final and g["tot"] is not None and g["uo"]:
                tot = g["hs"] + g["as"]
                won = None if tot == g["tot"] else tot < g["tot"]
                row["underUnits"] = round(settle(won, am_to_dec(g["uo"])), 3)
    if g["wind"] is not None and final:
        row["windRecorded"] = g["wind"]
    return row


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


def team_table(games, params, season: int, ratings: dict) -> list:
    fin = [g for g in games if g["season"] == season and g["hs"] is not None]
    last_wk = max((g["week"] for g in fin), default=None)
    prev = {}
    if last_wk is not None:
        cut = [g for g in games if g["season"] < season
               or (g["season"] == season and g["week"] < last_wk)]
        _, prev, _ = run(cut, **params)
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


def build(now: datetime) -> dict:
    games = load(DATA)
    saved = json.loads(PARAMS.read_text(encoding="utf-8"))
    params, blend_w = saved["params"], saved["blend_w"]
    recs, ratings, info = run(games, **params)
    season = max(g["season"] for g in games)
    wind_log = update_wind_log(games, season, now)
    odds = get_odds()                      # None unless ODDS_API_KEY is set or a cache exists
    shop = match_games(odds, games, TEAM_NAME)
    if shop:
        log_snapshots(shop, games)

    rows = [game_row(r, blend_w, wind_log, shop, now) for r in recs if r["g"]["season"] == season]
    unplayed = [x for x in rows if x["status"] != "final"]
    current = unplayed[0]["wk"] if unplayed else rows[-1]["wk"]
    teams, last_wk = team_table(games, params, season, ratings)
    hist = team_history(recs, season, ratings, now.date().isoformat())
    for t in teams:
        t["hist"] = hist[t["team"]]
    return {
        "updated": now.isoformat(timespec="minutes"),
        "updatedLabel": f"{now:%a} {now:%b} {now.day}, {now.strftime('%I:%M').lstrip('0')} {now:%p} CT",
        "season": season, "currentWeek": current, "deltaWeek": last_wk,
        "blendW": blend_w, "hfa": round(info["hfa_now"], 1), "windMph": WIND_MPH,
        "oddsFetched": odds["fetched"] if odds else None, "oddsGames": len(shop), "gapEv": GAP_EV,
        "fees": EXCHANGE_FEE,
        "games": rows, "summary": season_summary(rows), "teams": teams,
    }


def _between(text: str, start: str, end: str) -> str:
    i, j = text.find(start), text.find(end)
    if i < 0 or j < 0:
        sys.exit(f"Couldn't find {start} ... {end} in site/index.html")
    return text[i + len(start):j]


def bust_cache(stamp: str) -> None:
    """Tag asset links in site/*.html with a version (?v=...) so browsers fetch the new
    files after an update instead of reusing a saved copy (GitHub Pages lets them keep
    files for 10 minutes). Code files get a content hash; data.js gets the build stamp."""
    ver = {"assets/app.js": hashlib.sha1((SITE / "assets" / "app.js").read_bytes()).hexdigest()[:8],
           "assets/style.css": hashlib.sha1((SITE / "assets" / "style.css").read_bytes()).hexdigest()[:8],
           "data.js": re.sub(r"\D", "", stamp)}
    pat = re.compile(r'(assets/app\.js|assets/style\.css|data\.js)(\?v=[^"]*)?"')
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
    data = build(now)
    out = write_site(data)
    try:
        sent = alerts.run(data)            # phone alerts via ntfy; does nothing without a channel
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
