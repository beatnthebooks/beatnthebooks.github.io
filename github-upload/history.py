"""
history.py
==========
Test betting at the OPENING line instead of the close, using the aussportsbetting.com
NFL spreadsheet (data/nfl_odds_history.xlsx: open / min / max / close for moneyline,
spread and total since 2006). Terms: personal use only; never republish the raw data.

Questions, fixed before running:
  A. How much more accurate is the closing moneyline than the opening one?
  B. Elo leans (the site's rule: 22% Elo + 78% market, bet the side that's +EV) priced at
     the OPEN vs the CLOSE. Also closing-line value (CLV): how often the line moved
     toward the bet by kickoff. Beating the close more than half the time would mean
     Elo knows something the opening line doesn't.
  C. Wind unders (outdoor/open roof, wind >= 10 mph) at the opening total vs the closing
     total, and how far totals move for windy vs calm games. Wind here is the RECORDED
     game wind (the only wind history before 2022), so this flatters the signal.

Results are split by the spreadsheet's data source, because each source "opens" at a
different time and price: footballlocks (2006-13), Pinnacle (2014-17), bet365 (2018-24),
betr (2025-).

Usage:  py history.py
Standard library only.
"""

from __future__ import annotations

import json
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from edge_lab import load
from rift_real import TEAM_NAME, run

ROOT = Path(__file__).resolve().parent
XLSX = ROOT / "data" / "nfl_odds_history.xlsx"
PARAMS = ROOT / "results" / "current_ratings.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NICK = {v: k for k, v in TEAM_NAME.items()} | {"Redskins": "WAS", "Football Team": "WAS"}
COLS = {"date": "A", "home": "B", "away": "C", "hs": "D", "as": "E",
        "hml_o": "I", "hml_c": "L", "aml_o": "M", "aml_c": "P",
        "hline_o": "Q", "hline_c": "T", "tot_o": "AG", "tot_c": "AJ",
        "over_o": "AK", "over_c": "AN", "under_o": "AO", "under_c": "AR"}
BLEND_W = 0.22
WIND = 10.0


def source(season: int) -> str:
    if season <= 2013:
        return "footballlocks 2006-13"
    if season <= 2017:
        return "Pinnacle 2014-17"
    if season <= 2024:
        return "bet365 2018-24"
    return "betr 2025-"


# ----------------------------------------------------------------------
# Load + match
# ----------------------------------------------------------------------

def read_xlsx(path: Path = XLSX) -> list[dict]:
    z = zipfile.ZipFile(path)
    ss = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
          for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for r in root.find("m:sheetData", NS).findall("m:row", NS)[1:]:
        cell = {}
        for c in r.findall("m:c", NS):
            v = c.find("m:v", NS)
            if v is not None:
                cell[re.match(r"[A-Z]+", c.get("r")).group()] = ss[int(v.text)] if c.get("t") == "s" else v.text
        rec = {}
        for k, col in COLS.items():
            val = cell.get(col)
            if k in ("home", "away"):
                rec[k] = val
            else:
                try:
                    rec[k] = float(val)
                except (TypeError, ValueError):
                    rec[k] = None
        if rec["date"] is None or not rec["home"]:
            continue
        rec["date"] = date(1899, 12, 30) + timedelta(days=int(rec["date"]))
        rows.append(rec)
    return rows


def code(full: str) -> str | None:
    for nick, c in NICK.items():
        if full.endswith(nick):
            return c
    return None


def match(rows: list, games: list) -> list:
    """Pair spreadsheet rows with nflverse games: same teams, dates within 2 days
    (the spreadsheet uses Australian dates)."""
    by_pair = defaultdict(list)
    for g in games:
        if g["hs"] is not None:
            by_pair[(g["home"], g["away"])].append(g)
    out = []
    for r in rows:
        h, a = code(r["home"]), code(r["away"])
        for g in by_pair.get((h, a), []) + by_pair.get((a, h), []):
            if abs((date.fromisoformat(g["date"]) - r["date"]).days) <= 2:
                flip = g["home"] != h          # neutral-site games can list teams the other way
                out.append({"g": g, "r": r, "flip": flip})
                break
    return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def fair(dh, da):
    if not dh or not da or dh <= 1 or da <= 1:
        return None
    qh, qa = 1 / dh, 1 / da
    return qh / (qh + qa)


def side_prices(m, when):
    """(home decimal, away decimal, home fair) in nflverse home/away orientation."""
    r = m["r"]
    dh, da = r[f"hml_{when}"], r[f"aml_{when}"]
    if m["flip"]:
        dh, da = da, dh
    return dh, da, fair(dh, da)


def stats(rets):
    n = len(rets)
    if not n:
        return "  no bets"
    mu = sum(rets) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / max(1, n - 1))
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    return f"{n:>5} bets  ROI {mu * 100:+6.1f}%  (t = {t:+.2f})"


def ll(p, y):
    p = min(1 - 1e-9, max(1e-9, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    rows = read_xlsx()
    games = load()
    params = json.loads(PARAMS.read_text(encoding="utf-8"))["params"]
    recs, _, _ = run(games, **params)
    p_elo = {id(r["g"]): r["p"] for r in recs}
    ms = match(rows, games)
    print(f"Spreadsheet rows: {len(rows)}  ·  matched to nflverse games: {len(ms)}")
    # Before 2014 the sheet has ONE price per game (filed as "open", timing unknown, no close),
    # so those seasons can't answer an open-vs-close question.
    ms = [m for m in ms if m["g"]["season"] >= 2014]
    print(f"Used for open vs close (2014 on): {len(ms)}")

    # ---- data check against nflverse closing lines ----
    print("\nDATA CHECK · spreadsheet close vs nflverse close")
    by = defaultdict(lambda: [[], [], 0])
    for m in ms:
        g, r = m["g"], m["r"]
        s = source(g["season"])
        hl = r["hline_c"]
        if hl is not None and g["spread"] is not None:
            nv = -hl if not m["flip"] else hl
            by[s][0].append(abs(nv - g["spread"]))
        _, _, fc = side_prices(m, "c")
        if fc is not None and g["hml"] and g["aml"]:
            qh, qa = 1 / (1 + (g["hml"] / 100 if g["hml"] > 0 else 100 / -g["hml"])), \
                     1 / (1 + (g["aml"] / 100 if g["aml"] > 0 else 100 / -g["aml"]))
            by[s][1].append(abs(fc - qh / (qh + qa)))
        by[s][2] += 1
    for s in sorted(by):
        sp, mlp, n = by[s]
        same = sum(1 for x in sp if x <= 0.5) / len(sp) if sp else 0
        print(f"  {s:<22} {n:>5} games · spread within 0.5 pt {same * 100:5.1f}% · "
              f"mean |win% gap| {sum(mlp) / max(1, len(mlp)) * 100:4.1f} pts")

    # ---- A. open vs close accuracy ----
    print("\nA. MONEYLINE ACCURACY · opening vs closing no-vig price (log loss, lower is better)")
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for m in ms:
        g = m["g"]
        if g["hs"] == g["as"]:
            continue
        _, _, fo = side_prices(m, "o")
        _, _, fc = side_prices(m, "c")
        if fo is None or fc is None:
            continue
        y = 1.0 if g["hs"] > g["as"] else 0.0
        a = acc[source(g["season"])]
        a[0] += ll(fo, y); a[1] += ll(fc, y); a[2] += 1
    for s in sorted(acc):
        o, c, n = acc[s]
        print(f"  {s:<22} {n:>5} games · open {o / n:.4f} · close {c / n:.4f} · "
              f"close better by {(o - c) / n * 1000:+.1f} per 1000")

    # ---- B. Elo leans at open vs close ----
    print(f"\nB. ELO LEANS ({int(BLEND_W * 100)}% Elo + market, bet the +EV side) · open vs close")
    res = defaultdict(lambda: {"o": [], "c": [], "clv": []})
    for m in ms:
        g = m["g"]
        p = p_elo[id(g)]
        y = None if g["hs"] == g["as"] else g["hs"] > g["as"]
        for when in ("o", "c"):
            dh, da, f = side_prices(m, when)
            if f is None:
                continue
            bl = BLEND_W * p + (1 - BLEND_W) * f
            evh, eva = bl * dh - 1, (1 - bl) * da - 1
            if max(evh, eva) <= 0:
                continue
            home = evh >= eva
            ret = 0.0 if y is None else ((dh if home else da) - 1 if y == home else -1.0)
            res[source(g["season"])][when].append(ret)
            if when == "o":
                _, _, fc = side_prices(m, "c")
                if fc is not None and fc != f:
                    moved_our_way = (fc > f) if home else (fc < f)
                    res[source(g["season"])]["clv"].append(moved_our_way)
    for s in sorted(res):
        d = res[s]
        clv = sum(d["clv"]) / len(d["clv"]) * 100 if d["clv"] else float("nan")
        print(f"  {s:<22} at open: {stats(d['o'])}")
        print(f"  {'':<22} at close:{stats(d['c'])}")
        print(f"  {'':<22} line moved toward the lean by kickoff: {clv:.1f}% of {len(d['clv'])} moved lines")

    # ---- C. wind unders at open vs close ----
    print(f"\nC. WIND UNDERS (outdoor, recorded wind >= {WIND:.0f} mph) · open vs close")
    wres = defaultdict(lambda: {"o": [], "c": [], "move_w": [], "move_calm": []})
    for m in ms:
        g, r = m["g"], m["r"]
        if g["roof"] not in ("outdoors", "open") or g["wind"] is None:
            continue
        s = source(g["season"])
        if r["tot_o"] is not None and r["tot_c"] is not None:
            (wres[s]["move_w"] if g["wind"] >= WIND else wres[s]["move_calm"]).append(r["tot_c"] - r["tot_o"])
        if g["wind"] < WIND:
            continue
        total = g["hs"] + g["as"]
        for when, line, dec in (("o", r["tot_o"], r["under_o"]), ("c", r["tot_c"], r["under_c"])):
            if line is None or not dec or dec <= 1:
                continue
            wres[s][when].append(0.0 if total == line else (dec - 1 if total < line else -1.0))
    for s in sorted(wres):
        d = wres[s]
        mw = sum(d["move_w"]) / len(d["move_w"]) if d["move_w"] else float("nan")
        mc = sum(d["move_calm"]) / len(d["move_calm"]) if d["move_calm"] else float("nan")
        print(f"  {s:<22} under at open: {stats(d['o'])}")
        print(f"  {'':<22} under at close:{stats(d['c'])}")
        print(f"  {'':<22} total moved open->close: windy {mw:+.2f} pts · calm {mc:+.2f} pts")


if __name__ == "__main__":
    main()
