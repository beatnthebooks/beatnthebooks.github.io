"""
wind_check.py
=============
The wind lead from edge_lab.py used games.csv's `wind`, which is the wind
RECORDED at the game (it's blank until a game is played). A bettor only has a
forecast. This script replaces recorded wind with archived forecasts from
Open-Meteo (free, no key) and asks whether the under edge survives.

Rules fixed before looking at any forecast-based result:
  * forecast wind = mean 10 m wind (mph) over the kickoff hour and the 3 hours after
  * bet the UNDER at the closing price when forecast wind >= 10 mph,
    outdoor or open-roof games only
  * compare with the same rule on recorded wind, same games

Forecast sources:
  * historical-forecast API: short-range forecasts, 2022 onward
    (roughly what's known in the hours before kickoff)
  * previous-runs API, `previous_day1`: the forecast made a day earlier,
    available from about late 2024

Downloads are cached in data/wind_forecast_cache.json.

Usage:  python3 wind_check.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

from edge_lab import load
from rift_real import am_to_dec

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "wind_forecast_cache.json"
START = "2022-09-01"
DAY1_START = "2024-09-01"
WIND_MPH = 10.0          # the tested threshold; don't tune it on results

# Approximate coordinates of every stadium that hosted an outdoor/open-roof
# game since 2022 (games.csv stadium_id).
STADIUMS = {
    "ATL97": (33.755, -84.401), "BAL00": (39.278, -76.623), "BOS00": (42.091, -71.264),
    "BUF00": (42.774, -78.787), "CAR00": (35.226, -80.853), "CHI98": (41.862, -87.617),
    "CIN00": (39.095, -84.516), "CLE00": (41.506, -81.700), "DAL00": (32.748, -97.093),
    "DEN00": (39.744, -105.020), "FRA00": (50.069, 8.645), "GER00": (48.219, 11.625),
    "GNB00": (44.501, -88.062), "HOU00": (29.685, -95.411), "IND00": (39.760, -86.164),
    "JAX00": (30.324, -81.637), "KAN00": (39.049, -94.484), "LON00": (51.556, -0.280),
    "LON02": (51.604, -0.066), "MAD01": (40.453, -3.688), "MEX00": (19.303, -99.150),
    "MIA00": (25.958, -80.239), "NAS00": (36.166, -86.771), "NYC01": (40.814, -74.074),
    "PHI00": (39.901, -75.168), "PHO00": (33.528, -112.263), "PIT00": (40.447, -80.016),
    "RIO00": (-22.912, -43.230), "SAO00": (-23.545, -46.474), "SEA00": (47.595, -122.332),
    "SFO01": (37.403, -121.970), "TAM00": (27.976, -82.503), "WAS00": (38.908, -76.864),
}
OUTDOOR = ("outdoors", "open")

# International games can keep the home team's stadium_id (e.g. JAX00 at Tottenham),
# so the stadium name wins when it names one of these venues.
VENUE_BY_NAME = {
    "Tottenham": "LON02", "Wembley": "LON00", "Allianz": "GER00", "Deutsche Bank Park": "FRA00",
    "Bernabeu": "MAD01", "Azteca": "MEX00", "Banorte": "MEX00", "Maracana": "RIO00",
    "Corinthians": "SAO00",
}


def stadium_key(g) -> str:
    for name, sid in VENUE_BY_NAME.items():
        if name in (g.get("stadium") or ""):
            return sid
    return g["sid"]


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def forecast(lat: float, lon: float) -> dict:
    """Live hourly wind forecast (mph, Eastern time) for the next 16 days."""
    h = fetch("https://api.open-meteo.com/v1/forecast?"
              f"latitude={lat}&longitude={lon}&hourly=wind_speed_10m&wind_speed_unit=mph"
              "&timezone=America/New_York&forecast_days=16")["hourly"]
    return dict(zip(h["time"], h["wind_speed_10m"]))


def download(end: str) -> dict:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if cache.get("end") == end:
        return cache
    cache = {"end": end, "short": {}, "day1": {}}
    for sid, (lat, lon) in STADIUMS.items():
        common = (f"latitude={lat}&longitude={lon}&wind_speed_unit=mph"
                  f"&timezone=America/New_York&end_date={end}")
        h = fetch("https://historical-forecast-api.open-meteo.com/v1/forecast?"
                  f"{common}&start_date={START}&hourly=wind_speed_10m")["hourly"]
        cache["short"][sid] = dict(zip(h["time"], h["wind_speed_10m"]))
        d = fetch("https://previous-runs-api.open-meteo.com/v1/forecast?"
                  f"{common}&start_date={DAY1_START}&hourly=wind_speed_10m_previous_day1")["hourly"]
        cache["day1"][sid] = dict(zip(d["time"], d["wind_speed_10m_previous_day1"]))
        print(f"  downloaded {sid}")
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def game_wind(series: dict, date: str, time: str):
    """Mean wind over the kickoff hour and the 3 hours after (games.csv times are Eastern)."""
    hour = int(time[:2])
    vals = []
    for k in range(4):
        hh = hour + k
        if hh > 23:
            break
        v = series.get(f"{date}T{hh:02d}:00")
        if v is not None:
            vals.append(v)
    return sum(vals) / len(vals) if vals else None


def under_return(g) -> float:
    total, line = g["hs"] + g["as"], g["tot"]
    if total == line:
        return 0.0
    return am_to_dec(g["uo"]) - 1.0 if total < line else -1.0


def report(label: str, rets: list) -> None:
    n = len(rets)
    if not n:
        print(f"  {label:<46} no bets")
        return
    mu = sum(rets) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / max(1, n - 1))
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    print(f"  {label:<46}{n:>4} bets  ROI {mu * 100:+6.1f}%  t = {t:+.2f}")


def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy)


def main() -> None:
    games = [g for g in load() if g["date"] >= START and g["hs"] is not None
             and g["roof"] in OUTDOOR and g["tot"] is not None and g["uo"] is not None]
    end = max(g["date"] for g in games)
    print(f"Downloading forecasts through {end} (cached after the first run) ...")
    cache = download(end)

    rows = []
    for g in games:
        sid = stadium_key(g)
        if sid not in STADIUMS:
            continue
        rows.append({"g": g, "fc": game_wind(cache["short"][sid], g["date"], g["time"]),
                     "d1": game_wind(cache["day1"][sid], g["date"], g["time"])})

    both = [r for r in rows if r["fc"] is not None and r["g"]["wind"] is not None]
    print(f"\n{len(rows)} outdoor/open games since {START}; "
          f"{len(both)} have both a forecast and recorded wind")
    print(f"  correlation, forecast vs recorded wind: "
          f"{corr([r['fc'] for r in both], [r['g']['wind'] for r in both]):.2f}")
    print(f"  mean wind: forecast {sum(r['fc'] for r in both) / len(both):.1f} mph, "
          f"recorded {sum(r['g']['wind'] for r in both) / len(both):.1f} mph")

    print("\nUNDER at the closing price, by season group")
    for label, seasons in (("2022-2025", range(2022, 2026)), ("2026 so far", range(2026, 2027))):
        sub = [r for r in rows if r["g"]["season"] in seasons]
        sub_both = [r for r in sub if r in both]
        print(f" {label}")
        report("every outdoor game (baseline)", [under_return(r["g"]) for r in sub])
        report("forecast wind >= 10 mph", [under_return(r["g"]) for r in sub
                                           if r["fc"] is not None and r["fc"] >= 10])
        report("recorded wind >= 10 mph (same games as both)",
               [under_return(r["g"]) for r in sub_both if r["g"]["wind"] >= 10])
        report("forecast wind >= 10 mph (same games as both)",
               [under_return(r["g"]) for r in sub_both if r["fc"] >= 10])
        report("day-before forecast >= 10 mph (late 2024 on)",
               [under_return(r["g"]) for r in sub if r["d1"] is not None and r["d1"] >= 10])

    print("\nBy season, forecast wind >= 10 mph")
    for s in range(2022, 2027):
        report(str(s), [under_return(r["g"]) for r in rows
                        if r["g"]["season"] == s and r["fc"] is not None and r["fc"] >= 10])


if __name__ == "__main__":
    main()
