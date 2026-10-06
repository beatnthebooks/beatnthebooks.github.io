"""
exchanges.py
============
Kalshi and Polymarket prices straight from their free public APIs (no key, no credits).

  py exchanges.py               current moneyline prices for upcoming games
  py exchanges.py --backfill    download hourly price history for every finished NFL game
                                (2025 season on) into data/exchange_history.json
  py exchanges.py --test        the historical test below (results/exchange_test.txt)

Test, fixed before running (2025 season on, finished games only; "the close" = the sportsbooks'
closing moneyline from nflverse, no-vig; prices = what you'd pay: Kalshi's ask, Polymarket's
hourly price + half a cent, plus each exchange's taker fee):
  Q1. Is the exchange price an hour before kickoff as accurate as the sportsbooks' close?
  Q2. Price gaps: an hour before kickoff, bet any side whose exchange price is at least 2% better
      than the sportsbooks' closing fair price. Does it win money?
  Q3. Betting early: the site's model lean (model as of opening day, 28% model + 72% exchange
      price) bought 6 days, 3 days, 1 day and 1 hour before kickoff. Value vs the close and
      actual return.
  Q4. The rest signal from line_move.py (fit on 2014-2024 only) applied to exchange prices 6 days out.

Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "exchange_history.json"
KX = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
POLY_SERIES = ("10187", "12185")             # NFL games: 2025 season, 2026 season
KX_ALIAS = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA"}
POLY_HALF_SPREAD = 0.005                     # Polymarket history is a mid/last price; you pay ~half a cent more
MAX_SPREAD = 0.06                            # wider bid-ask than this = too thin to quote
GAP_EV = 0.02
CHECKPOINTS = (("6 days before", 144), ("3 days before", 72), ("1 day before", 24), ("1 hour before", 1))
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG",
                                      "SEP", "OCT", "NOV", "DEC"), start=1)}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "beatnthebooks/1.0",
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")).timestamp())


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _close(d: dict):
    return _num(d.get("close", d.get("close_dollars")))


def kickoff_utc(g) -> int:
    """games.csv times are US Eastern; DST runs 2nd Sunday of March to 1st Sunday of November."""
    d = date.fromisoformat(g["date"])
    mar = date(d.year, 3, 8 + (6 - date(d.year, 3, 8).weekday()) % 7)
    nov = date(d.year, 11, 1 + (6 - date(d.year, 11, 1).weekday()) % 7)
    off = 4 if mar <= d < nov else 5
    hh, mm = (int(x) for x in g["time"].split(":"))
    return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc).timestamp()) + off * 3600


def fee(cents: float, rate: float) -> float:
    return rate * cents * (1.0 - cents)


def rates():
    from odds import EXCHANGE_FEE
    return EXCHANGE_FEE


# ----------------------------------------------------------------------
# Listing markets
# ----------------------------------------------------------------------

def kalshi_events(status: str, series: str = "KXNFLGAME") -> list:
    out, cur = [], ""
    while True:
        d = get(f"{KX}/events?series_ticker={series}&status={status}&limit=200"
                + ("&with_nested_markets=true" if status == "open" and series == "KXNFLGAME" else "")
                + (f"&cursor={cur}" if cur else ""))
        out += d.get("events", [])
        cur = d.get("cursor")
        if not cur or not d.get("events"):
            return out


def kalshi_game(ev_ticker: str) -> tuple:
    """'KXNFLGAME-25DEC04DALDET' -> (date, 'DALDET')."""
    part = ev_ticker.split("-")[1]
    d = date(2000 + int(part[:2]), MONTHS[part[2:5]], int(part[5:7]))
    return d, part[7:]


# Kalshi's web pages: kalshi.com/markets/<series>/<series page>/<event>, checked Oct 6 2026 (a wrong or closed
# event sends you to the series' first game, so links are only made for events that are listed open)
KX_WEB = {"KXNFLGAME": "nfl-game", "KXNFLSPREAD": "pro-football-spread", "KXNFLTOTAL": "pro-football-total-points"}
KX_KIND = {"KXNFLGAME": "ml", "KXNFLSPREAD": "spread", "KXNFLTOTAL": "total"}


def kalshi_url(event_ticker: str) -> str:
    """'KXNFLTOTAL-26OCT11CINMIA' -> https://kalshi.com/markets/kxnfltotal/pro-football-total-points/kxnfltotal-26oct11cinmia"""
    series = event_ticker.split("-")[0]
    return f"https://kalshi.com/markets/{series.lower()}/{KX_WEB[series]}/{event_ticker.lower()}"


def poly_url(slug: str) -> str:
    """One Polymarket page per game holds its moneyline, spreads and totals."""
    return f"https://polymarket.com/event/{slug}"


def kx_team(code: str, names: dict) -> str | None:
    c = KX_ALIAS.get(code, code)
    return c if c in names else None


def poly_events(series_id: str, closed: bool) -> list:
    out, off = [], 0
    while True:
        d = get(f"{GAMMA}/events?series_id={series_id}&closed={'true' if closed else 'false'}"
                f"&limit=100&offset={off}")
        out += d
        off += 100
        if len(d) < 100:
            return out


def poly_moneyline(ev: dict, nick: dict):
    """(team codes in outcome order, token ids, start ts, market) or None."""
    for m in ev.get("markets", []):
        if m.get("sportsMarketType") != "moneyline":
            continue
        try:
            outs = json.loads(m["outcomes"])
            toks = json.loads(m["clobTokenIds"])
        except (KeyError, TypeError, ValueError):
            return None
        teams = [nick.get(o) for o in outs]
        if None in teams or len(teams) != 2 or not m.get("gameStartTime"):
            return None
        return teams, toks, _ts(m["gameStartTime"]), m
    return None


def nicknames(names: dict) -> dict:
    """Polymarket outcome name -> team code: nicknames ("Rams"), and sometimes codes ("LAR")."""
    out = {v: k for k, v in names.items()} | {k: k for k in names}
    return out | {a: c for a, c in KX_ALIAS.items() if c in names}


def match_game(games_by_pair: dict, t1: str, t2: str, ts: int, hours: float = 36):
    for g in games_by_pair.get(frozenset((t1, t2)), []):
        if abs(kickoff_utc(g) - ts) <= hours * 3600:
            return g
    return None


# ----------------------------------------------------------------------
# Backfill
# ----------------------------------------------------------------------

def backfill(games, names) -> dict:
    hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
    by_pair = defaultdict(list)
    for g in games:
        if g["season"] >= 2025:
            by_pair[frozenset((g["home"], g["away"]))].append(g)
    now = int(time.time())
    nick = nicknames(names)
    unmatched = []

    # Kalshi: one market per team, hourly bid/ask candles
    evs = [] if "--poly-only" in sys.argv else kalshi_events("settled")
    print(f"Kalshi: {len(evs)} settled game events")
    for i, ev in enumerate(evs):
        d, _ = kalshi_game(ev["event_ticker"])
        mk = get(f"{KX}/markets?event_ticker={ev['event_ticker']}").get("markets", [])
        archived = not mk
        if archived:
            mk = get(f"{KX}/historical/markets?event_ticker={ev['event_ticker']}").get("markets", [])
        teams = [kx_team(m["ticker"].split("-")[-1], names) for m in mk]
        if len(mk) != 2 or None in teams:
            unmatched.append(ev["event_ticker"])
            continue
        noon = int(datetime(d.year, d.month, d.day, 17, tzinfo=timezone.utc).timestamp())
        g = match_game(by_pair, teams[0], teams[1], noon, hours=40)
        if g is None:
            continue                                  # preseason, or not in games.csv
        rec = hist.setdefault(g["gid"], {})
        if "kalshi" in rec:
            continue
        side = {}
        for m, t in zip(mk, teams):
            s, e = _ts(m["open_time"]), min(_ts(m["close_time"]), now)
            path = (f"/historical/markets/{m['ticker']}" if archived
                    else f"/series/KXNFLGAME/markets/{m['ticker']}")
            c = get(f"{KX}{path}/candlesticks?start_ts={s}&end_ts={e}&period_interval=60").get("candlesticks", [])
            side["home" if t == g["home"] else "away"] = [         # archived candles say "close",
                [x["end_period_ts"], _close(x["yes_bid"]), _close(x["yes_ask"])] for x in c]   # live ones "close_dollars"
            time.sleep(0.1)
        rec["kalshi"] = side
        if i % 50 == 0:
            print(f"  {i}/{len(evs)}")
            HIST.write_text(json.dumps(hist), encoding="utf-8")

    # Polymarket: one market per game, hourly price of the first outcome
    for sid in POLY_SERIES:
        evs = poly_events(sid, closed=True)
        print(f"Polymarket series {sid}: {len(evs)} closed game events")
        for i, ev in enumerate(evs):
            ml = poly_moneyline(ev, nick)
            if ml is None:
                unmatched.append(ev.get("slug"))
                continue
            teams, toks, start, _ = ml
            g = match_game(by_pair, teams[0], teams[1], start)
            if g is None:
                continue
            rec = hist.setdefault(g["gid"], {})
            if "poly" in rec:
                continue
            pts = []
            for a in range(start - 10 * 86400, start, 5 * 86400):      # 5-day windows
                h = get(f"{CLOB}/prices-history?market={toks[0]}&startTs={a}&endTs={min(start, a + 5 * 86400)}"
                        f"&fidelity=60").get("history", [])
                pts += [[x["t"], x["p"]] for x in h]
                time.sleep(0.1)
            first_home = teams[0] == g["home"]
            rec["poly"] = sorted({t: (p if first_home else 1.0 - p) for t, p in pts}.items())
            if i % 50 == 0:
                print(f"  {i}/{len(evs)}")
                HIST.write_text(json.dumps(hist), encoding="utf-8")
    HIST.write_text(json.dumps(hist), encoding="utf-8")
    real = [u for u in unmatched if u and "-" in u]
    print(f"Saved {len(hist)} games to {HIST.relative_to(ROOT)}. Couldn't read {len(real)} events"
          + (f" (e.g. {', '.join(real[:4])})" if real else ""))
    return hist


# ----------------------------------------------------------------------
# Prices at a moment
# ----------------------------------------------------------------------

def at(series, ts):
    """Last point at or before ts."""
    best = None
    for p in series:
        if p[0] <= ts:
            best = p
        else:
            break
    return best


def quote(rec: dict, venue: str, ts: int, fees: dict):
    """{'mid': home prob, 'home': cost per $1 incl. fee, 'away': ...} or None. Points older than
    3 hours count as missing."""
    if venue == "kalshi":
        k = rec.get("kalshi") or {}
        h, a = at(k.get("home", []), ts), at(k.get("away", []), ts)
        if not h or not a or ts - min(h[0], a[0]) > 3 * 3600 or None in (h[1], h[2], a[1], a[2]):
            return None
        hb, ha, ab, aa = h[1], h[2], a[1], a[2]
        if not (0 < ha < 1 and 0 < aa < 1) or ha - hb > MAX_SPREAD or aa - ab > MAX_SPREAD:
            return None                               # empty or very thin book
        buy_h = min(ha, 1.0 - ab)
        buy_a = min(aa, 1.0 - hb)
        mid_h, mid_a = (hb + ha) / 2, (ab + aa) / 2
        mid = mid_h / (mid_h + mid_a)
    else:
        p = at(rec.get("poly", []), ts)
        if not p or ts - p[0] > 3 * 3600 or not (0.02 < p[1] < 0.98):
            return None
        mid = p[1]
        buy_h, buy_a = mid + POLY_HALF_SPREAD, 1.0 - mid + POLY_HALF_SPREAD
    r = fees["kalshi" if venue == "kalshi" else "polymarket"]
    return {"mid": mid, "home": buy_h + fee(buy_h, r), "away": buy_a + fee(buy_a, r)}


# ----------------------------------------------------------------------
# Live prices (used by the site)
# ----------------------------------------------------------------------

def current(games, names, links: dict | None = None) -> dict:
    """{gid: {"kalshi": {"home": ask, "away": ask}, "polymarket": {...}}} for games not yet played.
    Prices are what you'd pay per $1 contract, before fees.
    links (optional, filled in place): {gid: {"kalshi": {"ml"|"spread"|"total": url}, "polymarket": url}} for every
    open market, thin or not, so the site can send Mason straight to the bet."""
    now = time.time()
    by_pair = defaultdict(list)
    for g in games:
        if g["hs"] is None and kickoff_utc(g) > now:          # not started (no in-game prices)
            by_pair[frozenset((g["home"], g["away"]))].append(g)
    nick = nicknames(names)
    out = defaultdict(dict)
    kx_gid = {}                                                # '26OCT11CINMIA' -> gid
    try:
        for ev in kalshi_events("open"):
            d, _ = kalshi_game(ev["event_ticker"])
            mk = ev.get("markets", [])
            teams = [kx_team(m["ticker"].split("-")[-1], names) for m in mk]
            if len(mk) != 2 or None in teams:
                continue
            noon = int(datetime(d.year, d.month, d.day, 17, tzinfo=timezone.utc).timestamp())
            g = match_game(by_pair, teams[0], teams[1], noon, hours=40)
            if g is None:
                continue
            kx_gid[ev["event_ticker"].split("-", 1)[1]] = g["gid"]
            ba = {("home" if t == g["home"] else "away"): (_num(m.get("yes_bid_dollars")), _num(m.get("yes_ask_dollars")))
                  for m, t in zip(mk, teams)}
            if len(ba) != 2 or any(b is None or a is None or not 0 < a < 1 or a - b > MAX_SPREAD
                                   for b, a in ba.values()):
                continue                                       # empty or thin book
            (hb, ha), (ab, aa) = ba["home"], ba["away"]
            out[g["gid"]]["kalshi"] = {"home": round(min(ha, 1 - ab), 4), "away": round(min(aa, 1 - hb), 4)}
    except Exception as exc:
        print(f"  Kalshi prices unavailable ({exc})")
    if links is not None and kx_gid:                           # the same game's spread and total events
        for series in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL"):
            try:
                evs = ([{"event_ticker": f"KXNFLGAME-{s}"} for s in kx_gid] if series == "KXNFLGAME"
                       else kalshi_events("open", series))
            except Exception as exc:
                print(f"  Kalshi {KX_KIND[series]} links unavailable ({exc})")
                continue
            for ev in evs:
                gid = kx_gid.get(ev["event_ticker"].split("-", 1)[1])
                if gid:
                    links.setdefault(gid, {}).setdefault("kalshi", {})[KX_KIND[series]] = kalshi_url(ev["event_ticker"])
    try:
        for ev in poly_events(POLY_SERIES[-1], closed=False):
            ml = poly_moneyline(ev, nick)
            if ml is None:
                continue
            teams, _, start, m = ml
            g = match_game(by_pair, teams[0], teams[1], start)
            if g is not None and links is not None and ev.get("slug"):
                links.setdefault(g["gid"], {})["polymarket"] = poly_url(ev["slug"])
            bid, ask = _num(m.get("bestBid")), _num(m.get("bestAsk"))
            if g is None or not bid or not ask or not (0 < bid < ask < 1) or ask - bid > MAX_SPREAD:
                continue
            first = "home" if teams[0] == g["home"] else "away"
            other = "away" if first == "home" else "home"
            out[g["gid"]]["polymarket"] = {first: ask, other: round(1.0 - bid, 4)}
    except Exception as exc:
        print(f"  Polymarket prices unavailable ({exc})")
    return dict(out)


# ----------------------------------------------------------------------
# Historical test
# ----------------------------------------------------------------------

def _summary(bets):
    n = len(bets)
    if not n:
        return "    0 bets"
    rets = [b["ret"] for b in bets]
    mu = sum(rets) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / max(1, n - 1))
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    cl = [b["clv"] for b in bets]
    cm = sum(cl) / n
    csd = math.sqrt(sum((x - cm) ** 2 for x in cl) / max(1, n - 1))
    ct = cm / (csd / math.sqrt(n)) if csd else 0.0
    return (f"{n:>4} bets · value vs close {cm * 100:+5.1f}% (t = {ct:+.1f}) · "
            f"actual return {mu * 100:+6.1f}% (t = {t:+.1f})")


def _bet(home, cost, fc, y):
    d = 1.0 / cost
    pc = fc if home else 1.0 - fc
    ret = 0.0 if y is None else (d - 1.0 if y == (1.0 if home else 0.0) else -1.0)
    return {"clv": pc * d - 1.0, "ret": ret}


def test(games):
    import line_move as LM
    import rift_real as R
    from edge_lab import logit, sigmoid
    hist = json.loads(HIST.read_text(encoding="utf-8"))
    fees = rates()
    p_open, blend_w = LM.model_probs(games, at_open=True)
    p_act, _ = LM.model_probs(games, at_open=False)
    by_gid = {g["gid"]: g for g in games}
    rows = []
    for gid, rec in hist.items():
        g = by_gid.get(gid)
        if g is None or g["hs"] is None or g["hml"] is None or g["aml"] is None:
            continue
        fc = R.market_fair(g)
        y = None if g["hs"] == g["as"] else (1.0 if g["hs"] > g["as"] else 0.0)
        rows.append({"g": g, "rec": rec, "ko": kickoff_utc(g), "fc": fc, "y": y})
    print(f"Finished games with exchange history: {len(rows)} "
          f"(Kalshi {sum(1 for r in rows if r['rec'].get('kalshi'))}, "
          f"Polymarket {sum(1 for r in rows if r['rec'].get('poly'))})")

    # Q1 accuracy an hour before kickoff, same games for all three
    print("\nQ1. ACCURACY AN HOUR BEFORE KICKOFF (log loss, lower is better; same games)")
    trip = []
    for r in rows:
        if r["y"] is None:
            continue
        qk = quote(r["rec"], "kalshi", r["ko"] - 3600, fees)
        qp = quote(r["rec"], "poly", r["ko"] - 3600, fees)
        if qk and qp:
            trip.append((qk["mid"], qp["mid"], r["fc"], r["y"]))
    ll = lambda i: sum(-math.log(t[i] if t[3] else 1 - t[i]) for t in trip) / len(trip)
    if trip:
        print(f"  {len(trip)} games · Kalshi {ll(0):.4f} · Polymarket {ll(1):.4f} · sportsbooks' close {ll(2):.4f}")
        gap = [abs(t[0] - t[2]) for t in trip]
        print(f"  average distance from the sportsbooks' close: Kalshi {sum(gap) / len(gap) * 100:.1f} win-% pts, "
              f"Polymarket {sum(abs(t[1] - t[2]) for t in trip) / len(trip) * 100:.1f}")

    # Q2 price gaps an hour before kickoff
    print(f"\nQ2. PRICE GAPS AN HOUR BEFORE KICKOFF (exchange price >= {GAP_EV * 100:.0f}% better than the books' close)")
    for venue in ("kalshi", "poly"):
        bets = []
        for r in rows:
            q = quote(r["rec"], venue, r["ko"] - 3600, fees)
            if not q:
                continue
            for home in (True, False):
                b = _bet(home, q["home" if home else "away"], r["fc"], r["y"])
                if b["clv"] >= GAP_EV:
                    bets.append(b)
        print(f"  {venue:<10}{_summary(bets)}")

    # Q3 model leans at different times
    print(f"\nQ3. MODEL LEANS BOUGHT EARLY ({int(blend_w * 100)}% model + {100 - int(blend_w * 100)}% exchange price)")
    for venue in ("kalshi", "poly"):
        print(f"  {'Kalshi' if venue == 'kalshi' else 'Polymarket'}")
        for label, hrs in CHECKPOINTS:
            bets = []
            for r in rows:
                q = quote(r["rec"], venue, r["ko"] - hrs * 3600, fees)
                if not q:
                    continue
                p = (p_act if hrs <= 1 else p_open)[id(r["g"])]
                bl = blend_w * p + (1 - blend_w) * q["mid"]
                evh, eva = bl / q["home"] - 1, (1 - bl) / q["away"] - 1
                if max(evh, eva) <= 0:
                    continue
                home = evh >= eva
                bets.append(_bet(home, q["home" if home else "away"], r["fc"], r["y"]))
            print(f"    {label:<15}{_summary(bets)}")

    # Q4 the rest signal, fit on 2014-2024 only
    print("\nQ4. REST SIGNAL (line_move.py, fit on 2014-2024 only) · 6 days before")
    import history as H
    lm_games = LM.load()
    lm_rows = LM.build(lm_games, LM.model_probs(lm_games, at_open=True)[0], LM.last_ats(lm_games))
    beta = LM.fit([x for x in lm_rows if x["season"] <= 2024], ["rest"])
    for venue in ("kalshi", "poly"):
        bets = []
        for r in rows:
            q = quote(r["rec"], venue, r["ko"] - 144 * 3600, fees)
            if not q:
                continue
            g = r["g"]
            rest = max(-7.0, min(7.0, g["hrest"] - g["arest"])) / 7.0
            pc = sigmoid(logit(q["mid"]) + beta[0] + beta[1] * rest)
            evh, eva = pc / q["home"] - 1, (1 - pc) / q["away"] - 1
            if max(evh, eva) <= 0:
                continue
            home = evh >= eva
            bets.append(_bet(home, q["home" if home else "away"], r["fc"], r["y"]))
        print(f"  {venue:<10}{_summary(bets)}")


def main():
    import rift_real as R
    from edge_lab import load
    games = load()
    if "--backfill" in sys.argv:
        backfill(games, R.TEAM_NAME)
    elif "--test" in sys.argv:
        test(games)
    else:
        cur = current(games, R.TEAM_NAME)
        by_gid = {g["gid"]: g for g in games}
        for gid, v in sorted(cur.items(), key=lambda kv: by_gid[kv[0]]["date"]):
            g = by_gid[gid]
            print(f"{g['date']} {g['away']:>3} at {g['home']:<3}  " + "  ".join(
                f"{k}: {g['away']} {q.get('away', 0) * 100:.0f}¢ / {g['home']} {q.get('home', 0) * 100:.0f}¢"
                for k, q in v.items()))


if __name__ == "__main__":
    main()
