"""Wind forecasts freeze at kickoff; phone alerts go out once per signal. No network: the
forecast and ntfy calls are replaced with stubs, and logs go to a temp folder."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import alerts  # noqa: E402
import weekly  # noqa: E402


def game(gid, date, time):
    return {"gid": gid, "season": 2026, "date": date, "time": time, "hs": None, "as": None,
            "roof": "outdoors", "sid": "BUF00", "stadium": "Highmark Stadium"}


def hourly(mph):
    return {f"2026-10-{d:02d}T{h:02d}:00": mph for d in (10, 11) for h in range(24)}


class WindLogFreezes(unittest.TestCase):
    def test_kicked_off_game_keeps_its_last_forecast(self):
        now = datetime(2026, 10, 10, 12, 0)                 # Central
        started = game("g_started", "2026-10-10", "12:00")  # 12:00 ET = 11:00 CT, already kicked off
        upcoming = game("g_up", "2026-10-11", "13:00")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "wind_log.json"
            log.write_text(json.dumps({"g_started": {"wind": 5.0, "src": "live", "asof": "x"}}))
            with mock.patch.object(weekly, "WIND_LOG", log), \
                 mock.patch.object(weekly, "forecast", lambda lat, lon: hourly(20.0)), \
                 mock.patch.object(weekly, "fetch", lambda url: {"hourly": {"time": [], "wind_speed_10m": []}}):
                out = weekly.update_wind_log([started, upcoming], 2026, now)
        self.assertEqual(out["g_started"]["wind"], 5.0)     # frozen at kickoff
        self.assertEqual(out["g_up"]["wind"], 20.0)         # still refreshing


class OddsLog(unittest.TestCase):
    def test_exchange_only_prices_log_twice(self):
        """On GitHub there's no odds key: prices come only from the exchanges' feeds (no "fetched").
        The second run used to crash with KeyError: 'fetched' (Oct 5, 2026)."""
        import odds
        g = {"gid": "g1"}
        snap = lambda t: {"books": 0, "fair": {"home": 0.5}, "ml": {}, "live": t}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(odds, "LOG", Path(tmp) / "odds_log.json"):
            odds.log_snapshots({"g1": snap("2026-10-05T12:00:00+00:00")}, [g])
            odds.log_snapshots({"g1": snap("2026-10-05T15:00:00+00:00")}, [g])
            log = json.loads(odds.LOG.read_text(encoding="utf-8"))
        self.assertEqual(log["g1"]["first"]["live"], "2026-10-05T12:00:00+00:00")
        self.assertEqual(log["g1"]["last"]["live"], "2026-10-05T15:00:00+00:00")


def data(signals, now="2026-10-09T12:00"):
    games = []
    for gid, sig in signals.items():
        games.append({"id": gid, "status": "upcoming", "koIso": "2026-10-11T12:00", "awayName": "Bears",
                      "homeName": "Packers", "ko": "Sun Oct 11 · 12:00 PM CT", "wind": 14.0 if sig else 4.0,
                      "signal": "under" if sig else None, "total": {"line": 44.5}, "gaps": []})
    return {"updated": now, "games": games}


class AlertsOnce(unittest.TestCase):
    def run_alerts(self, d, state, sent):
        with mock.patch.object(alerts, "STATE", state), \
             mock.patch.object(alerts, "topic", lambda create=False: "test-channel"), \
             mock.patch.object(alerts, "send", lambda title, body, tags="", click="": sent.append(title)):
            return alerts.run(d)

    def test_summary_then_once_per_signal_then_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, sent = Path(tmp) / "alerts_sent.json", []
            self.run_alerts(data({"g1": True}), state, sent)
            self.assertEqual(sent, ["Beatn' the Books alerts are on"])              # first run: summary only
            self.run_alerts(data({"g1": True}), state, sent)
            self.assertEqual(len(sent), 1)                                    # nothing new, nothing sent
            self.run_alerts(data({"g1": True, "g2": True}), state, sent)
            self.assertEqual(sent[-1], "Wind UNDER: Bears @ Packers")          # new signal
            self.run_alerts(data({"g1": True, "g2": False}), state, sent)
            self.assertTrue(sent[-1].startswith("Wind signal gone"))           # forecast calmed
            self.run_alerts(data({"g1": True, "g2": True}), state, sent)
            self.assertTrue(sent[-1].startswith("Wind UNDER again"))           # and came back

    def test_no_wind_alert_more_than_72_hours_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, sent = Path(tmp) / "alerts_sent.json", []
            self.run_alerts(data({}), state, sent)                            # summary
            self.run_alerts(data({"g1": True}, now="2026-10-05T12:00"), state, sent)
            self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
