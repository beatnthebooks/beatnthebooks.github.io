"""
alerts.py
=========
Phone alerts through ntfy (https://ntfy.sh, free, no account): install the ntfy
app and subscribe to the private channel name in ntfy_topic.txt.

Sent by weekly.py after every rebuild, for games that haven't kicked off:
  * a NEW wind under signal (forecast wind >= 10 mph, outdoor/open roof), once kickoff is
    within 72 hours (longer-range wind forecasts are too rough to act on)
  * a NEW price gap (Kalshi/Polymarket >= 2% better than the books' fair price after fees)
  * a wind signal that DISAPPEARED before kickoff (the forecast calmed down)
Each alert goes out once; data/alerts_sent.json remembers what was sent. The very
first run sends one summary instead of an alert per existing signal.

Channel name: env/Windows variable NTFY_TOPIC, else the file ntfy_topic.txt
(gitignored; anyone who knows the name can read the alerts, so keep it private).
Messages hold only game and price info, never bets or account details.

Usage:
    py alerts.py --test     # send a test notification
Standard library only.
"""

from __future__ import annotations

import json
import secrets
import sys
import urllib.request
from pathlib import Path

from odds import setting

ROOT = Path(__file__).resolve().parent
TOPIC_FILE = ROOT / "ntfy_topic.txt"
STATE = ROOT / "data" / "alerts_sent.json"
SITE = "https://claude.ai/artifact/9rX2NXSmzjCCLBjDaZZEPg"
WIND_HOURS = 72        # wind alerts only once kickoff is this close


def topic(create: bool = False) -> str | None:
    t = setting("NTFY_TOPIC")
    if t:
        return t
    if TOPIC_FILE.exists():
        return TOPIC_FILE.read_text(encoding="utf-8").strip() or None
    if create:
        t = "edgeboard-" + secrets.token_urlsafe(18).replace("_", "x")
        TOPIC_FILE.write_text(t + "\n", encoding="utf-8")
        return t
    return None


def send(title: str, body: str, tags: str = "", click: str = SITE) -> None:
    t = topic()
    if not t:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{t}", data=body.encode("utf-8"), method="POST",
        headers={"Title": title.encode("ascii", "replace").decode(), "Tags": tags, "Click": click})
    with urllib.request.urlopen(req, timeout=20):
        pass


def _hours_to_kickoff(g: dict, data: dict) -> float:
    from datetime import datetime
    if not g.get("koIso"):
        return 0.0
    return (datetime.fromisoformat(g["koIso"]) - datetime.fromisoformat(data["updated"])).total_seconds() / 3600


def _signals(data: dict) -> dict:
    """{key: (title, body, tags)} for every live signal on games not yet kicked off.
    Wind only within WIND_HOURS of kickoff: longer-range forecasts are too rough to act on."""
    out = {}
    for g in data["games"]:
        if g["status"] != "upcoming":
            continue
        match = f"{g['awayName']} @ {g['homeName']}"
        if g.get("signal") == "under" and _hours_to_kickoff(g, data) <= WIND_HOURS:
            bu = (g.get("shop") or {}).get("total", {}).get("under")
            if bu:
                vs = "different line from the books" if bu.get("ev") is None else f"{bu['ev']:+.1f}% vs books before the wind edge"
                where = f"Under {bu['point']:g} at {bu['cents']:.0f}¢ on {bu['book']} ({vs})."
            elif g.get("total") and g["total"].get("line") is not None:
                where = f"Under {g['total']['line']:g}."
            else:
                where = "No total posted yet."
            out[f"{g['id']}:wind"] = (
                f"Wind UNDER: {match}",
                f"{g['wind']:.1f} mph forecast · {g['ko']}. {where} Flat 1% stake; re-check the forecast before kickoff.",
                "dash")
        for x in g.get("gaps", []):
            side = {"home": g["homeName"], "away": g["awayName"], "over": "Over", "under": "Under"}[x["side"]]
            line = "" if x["mk"] == "ml" else f" {x['point']:+g}" if x["mk"] == "spread" else f" {x['point']:g}"
            out[f"{g['id']}:gap:{x['mk']}:{x['side']}:{x.get('point')}"] = (
                f"Price gap: {side}{line} at {x['cents']:.0f}c",
                f"{side}{line} at {x['cents']:.0f}¢ on {x['book']}: {x['ev']:+.1f}% vs the sportsbooks' fair price "
                f"after fees. {match} · {g['ko']}. Untested signal; check the live order book first.",
                "moneybag")
    return out


def run(data: dict) -> int:
    """Send alerts for new or vanished signals. Returns how many were sent."""
    if not topic():
        return 0
    live = _signals(data)
    first = not STATE.exists()
    sent = json.loads(STATE.read_text(encoding="utf-8")) if not first else {}
    upcoming = {g["id"] for g in data["games"] if g["status"] == "upcoming"}
    n = 0
    if first:
        winds = sum(1 for k in live if k.endswith(":wind"))
        send("Edge Board alerts are on",
             f"Right now: {winds} wind under signal(s) and {len(live) - winds} price gap(s). "
             "From here you'll get one alert per new signal.", "white_check_mark")
        n += 1
    for key, (title, body, tags) in live.items():
        prev = sent.get(key)
        if prev and prev.get("active", True):
            continue
        if not first:
            send(title.replace("Wind UNDER", "Wind UNDER again") if prev else title, body, tags)
            n += 1
        sent[key] = {"title": title, "active": True}
    for key, info in sent.items():
        gid = key.split(":")[0]
        game = next((g for g in data["games"] if g["id"] == gid), None)
        if (key.endswith(":wind") and info.get("active") and key not in live and gid in upcoming
                and game and game.get("signal") != "under"):          # gone, not just outside the window
            send(info["title"].replace("Wind UNDER", "Wind signal gone"),
                 "The forecast dropped below 10 mph. The under is no longer a wind play.", "leaves")
            info["active"] = False
            n += 1
    STATE.write_text(json.dumps(sent, indent=1, sort_keys=True), encoding="utf-8")
    return n


if __name__ == "__main__":
    if "--test" in sys.argv:
        if not topic():
            sys.exit("No channel yet. Run `py weekly.py` once, or create ntfy_topic.txt.")
        send("Edge Board test", "If you can read this, phone alerts work.", "white_check_mark")
        print("Test notification sent.")
