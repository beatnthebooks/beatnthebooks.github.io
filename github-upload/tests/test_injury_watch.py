"""Injury-news alerts: who counts as a key player, no repeats, and a silent first run.
No network: the ESPN feed, odds and phone alerts are replaced with stubs."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import injury_watch as W  # noqa: E402

NAMES = {"CHI": "Bears", "GB": "Packers", "KC": "Chiefs", "LV": "Raiders"}
NOW = datetime(2026, 10, 8, 12, 0)
GAMES = [
    {"gid": "g1", "season": 2026, "week": 5, "date": "2026-10-11", "time": "13:00", "home": "GB", "away": "CHI", "hs": None},
    {"gid": "g2", "season": 2026, "week": 7, "date": "2026-10-25", "time": "13:00", "home": "LV", "away": "KC", "hs": None},
]
SHARES = {("CHI", "Caleb Williams"): (0.98, 0.0), ("CHI", "Kyler Gordon"): (0.0, 0.66),
          ("CHI", "Backup Guy"): (0.10, 0.0), ("GB", "Star Corner"): (0.0, 0.91),
          ("KC", "Far Away"): (0.95, 0.0)}


def value(season, week, team, name):
    return SHARES.get((team, name), (0.0, 0.0))


def feed(**status):
    rows = [("Chicago Bears", "Caleb Williams", "QB"), ("Chicago Bears", "Kyler Gordon", "CB"),
            ("Chicago Bears", "Backup Guy", "WR"), ("Green Bay Packers", "Star Corner", "CB"),
            ("Kansas City Chiefs", "Far Away", "WR")]
    return [{"team_name": t, "name": n, "pos": p, "status": status.get(n.split()[0], "Active"),
             "date": "", "comment": ""} for t, n, p in rows]


class KeyChanges(unittest.TestCase):
    def changes(self, f, prev):
        with mock.patch("weekly.kickoff_ct", lambda g: datetime.fromisoformat(f"{g['date']}T{g['time']}")):
            return W.find_key_changes(f, prev, GAMES, value, 2026, NAMES, NOW)

    def test_only_key_players_with_a_game_this_week(self):
        ch, _ = self.changes(feed(Caleb="Out", Kyler="Doubtful", Backup="Out", Far="Out"), {})
        self.assertEqual(sorted(c["name"] for c in ch), ["Caleb Williams", "Kyler Gordon"])
        qb = next(c for c in ch if c["name"] == "Caleb Williams")
        self.assertTrue(qb["is_qb"])

    def test_no_repeat_once_out(self):
        _, state = self.changes(feed(Caleb="Out"), {})
        ch, _ = self.changes(feed(Caleb="Out"), state)
        self.assertEqual(ch, [])
        ch, _ = self.changes(feed(Caleb="Doubtful"), state)        # Out -> Doubtful is not news
        self.assertEqual(ch, [])

    def test_questionable_to_out_is_news(self):
        _, state = self.changes(feed(Star="Questionable"), {})
        ch, _ = self.changes(feed(Star="Out"), state)
        self.assertEqual([c["name"] for c in ch], ["Star Corner"])


class RunFlow(unittest.TestCase):
    def test_first_run_is_silent_then_alerts_once(self):
        sent = []
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(W, "STATE", Path(tmp) / "state.json"), \
             mock.patch("alerts.topic", lambda create=False: "test-channel"), \
             mock.patch("injuries.snap_values", lambda: value), \
             mock.patch("edge_lab.load", lambda *a, **k: GAMES), \
             mock.patch("rift_real.TEAM_NAME", NAMES), \
             mock.patch("odds.get_odds", lambda force=False: None), \
             mock.patch("odds.setting", lambda name, default="": default), \
             mock.patch("weekly.kickoff_ct", lambda g: datetime.fromisoformat(f"{g['date']}T{g['time']}")):
            send = lambda title, body, tags="": sent.append(title)
            with mock.patch.object(W, "fetch_feed", lambda: feed(Caleb="Out")):
                self.assertEqual(W.run(NOW, send=send), 0)            # baseline: nothing sent
            with mock.patch.object(W, "fetch_feed", lambda: feed(Caleb="Out", Kyler="Out")):
                self.assertEqual(W.run(NOW, send=send), 1)
            with mock.patch.object(W, "fetch_feed", lambda: feed(Caleb="Out", Kyler="Out")):
                self.assertEqual(W.run(NOW, send=send), 0)            # no repeat
        self.assertEqual(sent, ["Injury: Kyler Gordon OUT (Bears CB)"])


if __name__ == "__main__":
    unittest.main()
