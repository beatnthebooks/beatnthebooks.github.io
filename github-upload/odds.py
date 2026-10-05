"""
odds.py
=======
Live NFL odds from many sportsbooks at once (The Odds API, https://the-odds-api.com),
so the site can show the BEST price for each bet instead of one consensus line.

Setup (once):
  * Free key from the-odds-api.com (Starter plan: 500 credits a month).
  * Save it as a Windows user environment variable named ODDS_API_KEY.
    The key is never written into this project.
  * Optional ODDS_BOOKS: comma-separated bookmaker keys you can actually bet at,
    e.g. "draftkings,fanduel,betmgm". Blank = every US book.
  * Optional ODDS_MIN_HOURS: hours between paid calls (default 6).

Cost: one call returns moneyline + spread + total for every upcoming game and
costs 3 credits. The result is cached in data/odds_cache.json and only
refreshed when it's older than ODDS_MIN_HOURS, so 6 refreshes a day still
cost about 12 credits a day (~370 a month).

Each upcoming game's last snapshot before kickoff is kept in data/odds_log.json,
for comparing the price you could get with the closing price later.

Usage:
    py odds.py            # fetch if the cache is stale, print a line-shopping table
    py odds.py --force    # fetch now (3 credits)

Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "odds_cache.json"
LOG = ROOT / "data" / "odds_log.json"
URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"

# Prediction-market exchanges (where Mason can bet) + sportsbooks that set the fair price.
# Pinnacle is the sharpest book; the rest are the big US books and two low-margin offshore ones.
EXCHANGES = ("kalshi", "polymarket")
FETCH_BOOKS = EXCHANGES + ("pinnacle", "draftkings", "fanduel", "betmgm", "williamhill_us",
                           "betrivers", "lowvig", "betonlineag")

# Taker fee per $1 contract = rate × price × (1 − price).
# Polymarket sports: 0.05 (docs.polymarket.com, Oct 2026). Kalshi: 0.07 is its standard taker
# rate; the fee-schedule PDF couldn't be loaded to confirm. Check a trade ticket and adjust.
EXCHANGE_FEE = {"kalshi": 0.07, "polymarket": 0.05}


def am_to_dec(a: float) -> float:
    return 1.0 + a / 100.0 if a > 0 else 1.0 + 100.0 / abs(a)


def setting(name: str, default: str = "") -> str:
    """Environment variable, falling back to the saved Windows user variable
    (covers programs started before the variable was added)."""
    val = os.environ.get(name, "").strip()
    if not val and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                val = str(winreg.QueryValueEx(h, name)[0]).strip()
        except OSError:
            pass
    return val or default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ----------------------------------------------------------------------
# Fetch + cache
# ----------------------------------------------------------------------

def fetch(key: str) -> dict:
    # Up to 10 named bookmakers cost the same as one region (3 credits for 3 markets).
    q = urllib.parse.urlencode({"apiKey": key, "bookmakers": ",".join(FETCH_BOOKS),
                                "markets": "h2h,spreads,totals",
                                "oddsFormat": "american", "dateFormat": "iso"})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=60) as resp:
        events = json.loads(resp.read().decode("utf-8"))
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
    return {"fetched": _utc_now().isoformat(timespec="seconds"), "events": events,
            "remaining": remaining, "used": used}


def get_odds(force: bool = False) -> dict | None:
    """Cached odds, refreshed when stale and a key is set. None if neither exists."""
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else None
    key = setting("ODDS_API_KEY")
    if not key:
        return cache
    max_age = timedelta(hours=float(setting("ODDS_MIN_HOURS", "6")))
    if cache and not force and _utc_now() - _parse_time(cache["fetched"]) < max_age:
        return cache
    try:
        fresh = fetch(key)
    except Exception as exc:                   # bad key, no network, quota used up
        msg = str(exc).replace(key, "***")
        print(f"  odds fetch failed ({msg}); using the cached odds" if cache
              else f"  odds fetch failed ({msg})")
        return cache
    CACHE.write_text(json.dumps(fresh), encoding="utf-8")
    print(f"  fetched odds for {len(fresh['events'])} games "
          f"(credits left this month: {fresh['remaining']})")
    return fresh


# ----------------------------------------------------------------------
# Line shopping
# ----------------------------------------------------------------------

def my_books() -> set:
    """Where Mason can bet: ODDS_BOOKS if set, else the two prediction-market exchanges."""
    picked = {b.strip().lower() for b in setting("ODDS_BOOKS").split(",") if b.strip()}
    return picked or set(EXCHANGES)


def _fair2(a: float, b: float) -> float:
    """No-vig probability of side a from a two-way sportsbook price."""
    qa, qb = 1 / am_to_dec(a), 1 / am_to_dec(b)
    return qa / (qa + qb)


def _offer(bk: dict, price: float, point=None) -> dict:
    """A price you can take, with the exchange's taker fee folded in."""
    p = 1 / am_to_dec(price)                         # contract cost in dollars
    fee = EXCHANGE_FEE.get(bk["key"], 0.0) * p * (1 - p)
    return {"book": bk["title"], "key": bk["key"], "price": price, "point": point,
            "cents": round(p * 100, 1), "fee": round(fee * 100, 2), "dec": round(1 / (p + fee), 4)}


def _fair_prob(fair: dict, mk: str, side: str, point) -> float | None:
    """Sportsbook fair probability for this exact bet, or None if the line differs."""
    if mk == "ml" and "home" in fair:
        return fair["home"] if side == "home" else 1 - fair["home"]
    if mk == "spread" and "spreadHome" in fair:
        if side == "home" and point == fair["spreadPoint"]:
            return fair["spreadHome"]
        if side == "away" and point == -fair["spreadPoint"]:
            return 1 - fair["spreadHome"]
    if mk == "total" and "over" in fair and point == fair["totalPoint"]:
        return fair["over"] if side == "over" else 1 - fair["over"]
    return None


def summarize(event: dict, mine: set | None = None) -> dict | None:
    """Fair price from the sportsbooks (median no-vig, at the most common line) and the
    best offer on Mason's books for each bet, with EV after fees where the line matches."""
    mine = mine or my_books()
    home, away = event["home_team"], event["away_team"]
    ml, sp, tot = [], {}, {}                        # sportsbook fair probs (sp/tot keyed by point)
    offers, updated = {}, []
    n_ref = n_mine = 0
    for bk in event.get("bookmakers", []):
        is_mine, is_ref = bk["key"] in mine, bk["key"] not in EXCHANGES
        if not (is_mine or is_ref):
            continue
        n_ref += is_ref
        n_mine += is_mine
        updated.append(bk.get("last_update", ""))
        for m in bk.get("markets", []):
            oc = {o["name"]: o for o in m.get("outcomes", [])}
            low = {k.lower(): v for k, v in oc.items()}
            if m["key"] == "h2h" and home in oc and away in oc:
                if is_ref:
                    ml.append(_fair2(oc[home]["price"], oc[away]["price"]))
                if is_mine:
                    for side, team in (("home", home), ("away", away)):
                        offers.setdefault(("ml", side), []).append(_offer(bk, oc[team]["price"]))
            elif m["key"] == "spreads" and home in oc and away in oc:
                hp = oc[home].get("point")
                if is_ref and hp is not None:
                    sp.setdefault(hp, []).append(_fair2(oc[home]["price"], oc[away]["price"]))
                if is_mine:
                    for side, team in (("home", home), ("away", away)):
                        offers.setdefault(("spread", side), []).append(
                            _offer(bk, oc[team]["price"], oc[team].get("point")))
            elif m["key"] == "totals" and "over" in low and "under" in low:
                pt = low["over"].get("point")
                if is_ref and pt is not None:
                    tot.setdefault(pt, []).append(_fair2(low["over"]["price"], low["under"]["price"]))
                if is_mine:
                    for side in ("over", "under"):
                        offers.setdefault(("total", side), []).append(
                            _offer(bk, low[side]["price"], low[side].get("point")))
    if not (n_ref or n_mine):
        return None
    fair = {}
    if ml:
        fair["home"] = round(median(ml), 4)
    if sp:
        pt = max(sp, key=lambda k: (len(sp[k]), -abs(k)))   # the line most books hang
        fair["spreadPoint"], fair["spreadHome"] = pt, round(median(sp[pt]), 4)
    if tot:
        pt = max(tot, key=lambda k: len(tot[k]))
        fair["totalPoint"], fair["over"] = pt, round(median(tot[pt]), 4)
    out = {"books": n_ref, "mine": n_mine, "fair": fair, "ml": {}, "spread": {}, "total": {}}
    for (mk, side), lst in offers.items():
        for o in lst:
            pf = _fair_prob(fair, mk, side, o["point"])
            o["ev"] = None if pf is None else round((pf * o["dec"] - 1) * 100, 1)
        out[mk][side] = max(lst, key=lambda o: (o["ev"] is not None, o["ev"] or 0, o["dec"]))
    out["updated"] = max(updated) if updated else None
    return out


def match_games(odds: dict | None, games: list, team_name: dict) -> dict:
    """{game_id: summary} for unplayed games. Matches on both nicknames and a date
    within a day (the API's kickoff is UTC; games.csv dates are Eastern)."""
    if not odds:
        return {}
    books = my_books()
    fetched = _parse_time(odds["fetched"])
    out = {}
    for ev in odds["events"]:
        ko = _parse_time(ev["commence_time"])
        if ko <= fetched:                     # already started: those are live in-game prices
            continue
        for g in games:
            if g["hs"] is not None:
                continue
            if not (ev["home_team"].endswith(team_name.get(g["home"], "?"))
                    and ev["away_team"].endswith(team_name.get(g["away"], "?"))):
                continue
            gd = datetime.fromisoformat(g["date"]).date()
            if abs((ko.date() - gd).days) <= 1:
                s = summarize(ev, books)
                if s:
                    s["fetched"] = odds["fetched"]
                    out[g["gid"]] = s
                break
    return out


def log_snapshots(shop: dict, games: list) -> None:
    """Per game, the FIRST snapshot seen and the LAST one before kickoff (frozen once the
    game starts), so early-week prices can be compared with the close on Mason's exchanges."""
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}
    changed = False
    for g in games:
        s = shop.get(g["gid"])
        if not s:
            continue
        e = log.get(g["gid"])
        if e is not None and "last" not in e:          # older one-snapshot format
            e = log[g["gid"]] = {"first": e, "last": e}
            changed = True
        if e is None:
            e = {"first": s, "last": s}
        elif e["last"].get("fetched") == s["fetched"]:
            continue
        else:
            e["last"] = s
        log[g["gid"]] = e
        changed = True
    if changed:
        LOG.write_text(json.dumps(log, indent=1, sort_keys=True), encoding="utf-8")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _fmt(o: dict | None, point: str = "") -> str:
    """point: "" (none), "signed" (spreads) or "plain" (totals)."""
    if not o:
        return "—"
    p = ""
    if point and o.get("point") is not None:
        p = f"{o['point']:+g} " if point == "signed" else f"{o['point']:g} "
    ev = "other line" if o.get("ev") is None else f"EV {o['ev']:+.1f}%"
    return f"{p}{o['cents']:.0f}¢+{o['fee']:.1f}¢ fee {o['book']} ({ev})"


def main() -> None:
    from edge_lab import load
    from rift_real import TEAM_NAME
    if not setting("ODDS_API_KEY"):
        print("ODDS_API_KEY isn't set. See the top of odds.py for the one-time setup.")
        if not CACHE.exists():
            return
        print("Showing the last cached odds.\n")
    odds = get_odds(force="--force" in sys.argv)
    games = load()
    shop = match_games(odds, games, TEAM_NAME)
    if not shop:
        print("No upcoming games matched.")
        return
    print(f"Odds fetched {odds['fetched']} UTC · credits left: {odds.get('remaining')}\n")
    for g in games:
        s = shop.get(g["gid"])
        if not s:
            continue
        f = s["fair"]
        fair_txt = []
        if "home" in f:
            fair_txt.append(f"{g['home']} {f['home'] * 100:.1f}%")
        if "spreadPoint" in f:
            fair_txt.append(f"{g['home']} {f['spreadPoint']:+g} covers {f['spreadHome'] * 100:.1f}%")
        if "totalPoint" in f:
            fair_txt.append(f"over {f['totalPoint']:g} {f['over'] * 100:.1f}%")
        print(f"{g['date']}  {TEAM_NAME[g['away']]} @ {TEAM_NAME[g['home']]}  "
              f"(fair from {s['books']} sportsbooks: {'; '.join(fair_txt) or 'none yet'})")
        print(f"   ML      {g['away']} {_fmt(s['ml'].get('away'))}  |  {g['home']} {_fmt(s['ml'].get('home'))}")
        print(f"   spread  {g['away']} {_fmt(s['spread'].get('away'), 'signed')}  |  {g['home']} {_fmt(s['spread'].get('home'), 'signed')}")
        print(f"   total   over {_fmt(s['total'].get('over'), 'plain')}  |  under {_fmt(s['total'].get('under'), 'plain')}")


if __name__ == "__main__":
    main()
