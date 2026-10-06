"""
injury_watch.py
===============
Phone alerts when a key player is newly ruled Out or Doubtful, with a check of whether
Kalshi/Polymarket have caught up with the sportsbooks.

Why: by kickoff the market has fully priced injuries (injuries.py found no edge at the
closing line). The open question is SPEED: sportsbooks re-price within minutes of news;
prediction markets may lag. This catches the news and compares prices right away.

Each run (called by weekly.py):
  1. Read ESPN's public injury feed (updates as news breaks).
  2. Compare with the last run (data/injury_state.json). A player matters if he's newly
     Out/Doubtful AND is a starting QB or plays 60%+ of his team's offensive or defensive
     snaps (this season's snap counts), AND his team plays within 8 days.
  3. For those, force a fresh odds pull (at most MAX_FORCED_FETCHES a day, 3 credits each),
     then report the sportsbooks' fair price before/after and the best Kalshi/Polymarket
     price for each side, after fees, vs the new fair price.
  4. Send it through ntfy (alerts.send). The first run only records a baseline.

Usage:  py injury_watch.py --test     # print what would be sent right now, send nothing
Standard library only.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "injury_state.json"
FEED = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
OUT = {"Out", "Doubtful"}
KEY_SHARE = 0.6
MAX_FORCED_FETCHES = 2          # extra odds pulls per day triggered by injury news


def refresh_current_files(season: int) -> None:
    """Re-download this season's snap counts and injury reports (they grow every week)."""
    base = "https://github.com/nflverse/nflverse-data/releases/download"
    nv = ROOT / "data" / "nflverse"
    nv.mkdir(parents=True, exist_ok=True)
    for kind in ("snap_counts", "injuries"):
        try:
            with urllib.request.urlopen(f"{base}/{kind}/{kind}_{season}.csv", timeout=120) as resp:
                data = resp.read()
            tmp = nv / f"{kind}_{season}.tmp"
            tmp.write_bytes(data)
            tmp.replace(nv / f"{kind}_{season}.csv")
        except Exception as exc:
            print(f"  couldn't refresh {kind}_{season}.csv ({exc})")


def fetch_feed() -> list:
    """[{team_name, name, pos, status, date, comment}] from ESPN's injury feed."""
    with urllib.request.urlopen(FEED, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for t in data.get("injuries", []):
        for e in t.get("injuries", []):
            a = e.get("athlete") or {}
            out.append({"team_name": t.get("displayName", ""), "name": a.get("displayName", ""),
                        "pos": ((a.get("position") or {}).get("abbreviation") or ""),
                        "status": e.get("status", ""), "date": e.get("date", ""),
                        "comment": e.get("shortComment", "")})
    return out


def team_code(display_name: str, team_name: dict) -> str | None:
    for code, nick in team_name.items():
        if display_name.endswith(nick):
            return code
    return None


def next_game(games, team, now):
    from weekly import kickoff_ct
    for g in games:
        if g["hs"] is None and team in (g["home"], g["away"]):
            ko = kickoff_ct(g)
            if now < ko <= now + timedelta(days=8):
                return g
    return None


CARD_STATUSES = ("Out", "Doubtful", "Questionable")     # IR/PUP are long-term: old news, already priced


def card_injuries(season: int, team_name: dict, feed: list | None = None, value=None) -> dict:
    """{team: [key players listed Out/Doubtful/Questionable]} for the game cards, from ESPN's live feed.
    Key = a QB who has been starting, or anyone playing >= KEY_SHARE of offense/defense snaps (same rule as
    the phone alerts). Downloads this season's and last season's snap counts if they're missing (GitHub)."""
    import injuries as I
    nv = ROOT / "data" / "nflverse"
    for yr in (season - 1, season):
        if not (nv / f"snap_counts_{yr}.csv").exists():
            refresh_current_files(yr)
    value = value or I.snap_values()
    feed = fetch_feed() if feed is None else feed
    out = {}
    for e in feed:
        code = team_code(e["team_name"], team_name)
        if not code or not e["name"] or e["status"] not in CARD_STATUSES:
            continue
        off, dfn = value(season, 99, code, e["name"])
        is_qb = e["pos"] == "QB" and off >= 0.5
        if not (is_qb or max(off, dfn) >= KEY_SHARE):
            continue
        out.setdefault(code, []).append({"name": e["name"], "pos": e["pos"], "status": e["status"],
                                         "share": round(max(off, dfn), 2), "qb": is_qb, "note": e["comment"][:160]})
    order = {s: i for i, s in enumerate(CARD_STATUSES)}
    for lst in out.values():
        lst.sort(key=lambda p: (not p["qb"], order[p["status"]], -p["share"]))
    return out


def find_key_changes(feed, prev, games, value, season, team_name, now):
    """Return (changes, new_state). A change = a key player newly Out/Doubtful."""
    state, changes = {}, []
    for e in feed:
        code = team_code(e["team_name"], team_name)
        if not code or not e["name"]:
            continue
        key = f"{code}|{e['name']}"
        state[key] = e["status"]
        if e["status"] not in OUT or prev.get(key) in OUT:
            continue
        off, dfn = value(season, 99, code, e["name"])
        is_qb = e["pos"] == "QB" and off >= 0.5
        if not (is_qb or max(off, dfn) >= KEY_SHARE):
            continue
        g = next_game(games, code, now)
        if not g:
            continue
        changes.append({"team": code, "name": e["name"], "pos": e["pos"], "status": e["status"],
                        "share": max(off, dfn), "side": "offense" if off >= dfn else "defense",
                        "is_qb": is_qb, "game": g, "comment": e["comment"]})
    return changes, state


def describe(c, before, after, team_name):
    """Alert title and body for one change. before/after: odds summaries for the game (or None)."""
    g = c["game"]
    from weekly import ko_label, kickoff_ct
    team, opp = c["team"], (g["away"] if c["team"] == g["home"] else g["home"])
    tn, on = team_name[team], team_name[opp]
    role = "starting QB" if c["is_qb"] else f"plays {round(c['share'] * 100)}% of {c['side']} snaps"
    title = f"Injury: {c['name']} {c['status'].upper()} ({tn} {c['pos']})"
    body = [f"{c['name']} ({role}) is {c['status'].lower()} for {team_name[g['away']]} at "
            f"{team_name[g['home']]}, {ko_label(kickoff_ct(g))}."]
    side_of = lambda code: "home" if code == g["home"] else "away"
    fair = lambda s, code: None if not s or "home" not in s["fair"] else \
        (s["fair"]["home"] if code == g["home"] else 1 - s["fair"]["home"])
    fb, fa = fair(before, team), fair(after, team)
    if fa is not None:
        moved = fb is not None and abs(fa - fb) >= 0.005
        body.append(f"Sportsbooks: {tn} {f'{fb * 100:.0f}% → ' if moved else ''}{fa * 100:.0f}% to win"
                    f"{' (already moved on the news)' if moved else ''}.")
        lines = []
        for code, nm in ((opp, on), (team, tn)):
            o = after["ml"].get(side_of(code))
            if o and o.get("ev") is not None:
                lines.append(f"{nm} {o['cents']:.0f}¢ on {o['book']} ({o['ev']:+.1f}% vs fair)")
        if lines:
            gap = any(after["ml"].get(side_of(code), {}).get("ev", -99) >= 2 for code in (opp, team))
            body.append("Kalshi/Polymarket now: " + "; ".join(lines) + "."
                        + (" Possible lag: check the live order book." if gap else " They look caught up."))
    else:
        body.append("No sportsbook prices for this game yet.")
    return title, " ".join(body)


def run(now: datetime, send=None, test=False) -> int:
    """Check for news, alert, save state. Returns alerts sent (or that would be sent with test)."""
    import alerts
    import injuries as I
    import odds as O
    from edge_lab import load
    from rift_real import TEAM_NAME
    send = send or alerts.send
    if not test and not alerts.topic():
        return 0
    prev_all = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else None
    prev = (prev_all or {}).get("status", {})
    games = load()
    season = max(g["season"] for g in games)
    feed = fetch_feed()
    changes, state = find_key_changes(feed, prev, games, I.snap_values(), season, TEAM_NAME, now)
    forced = (prev_all or {}).get("forced", {})
    today = now.date().isoformat()
    sent = 0
    if test:
        changes = changes[:5]                                  # preview: no baseline rule, no credits spent
    elif prev_all is None:                                     # first real run: baseline only
        changes = []
    for c in changes:
        cache = O.get_odds() if not test else (json.loads(O.CACHE.read_text(encoding="utf-8")) if O.CACHE.exists() else None)
        before = O.match_games(cache, games, TEAM_NAME).get(c["game"]["gid"])
        fresh = cache
        stale = not cache or (O._utc_now() - O._parse_time(cache["fetched"])).total_seconds() > 1200
        if not test and stale and forced.get(today, 0) < MAX_FORCED_FETCHES and O.setting("ODDS_API_KEY"):
            fresh = O.get_odds(force=True)
            if fresh is not cache:
                forced[today] = forced.get(today, 0) + 1
        after = O.match_games(fresh, games, TEAM_NAME).get(c["game"]["gid"]) or before
        title, body = describe(c, before, after, TEAM_NAME)
        if test:
            print(f"{title}\n  {body}\n")
        else:
            send(title, body, "rotating_light")
        sent += 1
    if not test:
        STATE.write_text(json.dumps({"status": state, "forced": {today: forced.get(today, 0)}},
                                    indent=1, sort_keys=True), encoding="utf-8")
    return sent


if __name__ == "__main__":
    if "--test" in sys.argv:
        from update_board import now_central
        n = run(now_central(), test=True)
        print(f"{n} alert(s) would be sent." if n else
              "No new key injuries since the last check (or this is the first check: baseline only).")
