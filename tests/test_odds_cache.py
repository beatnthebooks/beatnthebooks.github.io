"""The odds cache limits paid calls: a normal run reuses odds younger than ODDS_MIN_HOURS; a forced pull
(game-day check, injury news) still skips if the odds are under FORCE_MIN_MINUTES old. No network: fetch is a stub."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import odds as O  # noqa: E402

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)


class OddsCache(unittest.TestCase):
    def pull(self, age_minutes, force):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "odds_cache.json"
            cache.write_text(json.dumps({"fetched": (NOW - timedelta(minutes=age_minutes)).isoformat(), "events": []}))
            with mock.patch.object(O, "CACHE", cache), mock.patch.object(O, "_utc_now", lambda: NOW), \
                 mock.patch.object(O, "setting", lambda name, default="": "test-key" if name == "ODDS_API_KEY" else default), \
                 mock.patch.object(O, "fetch", lambda key: calls.append(key) or {"fetched": NOW.isoformat(), "events": [],
                                                                                    "remaining": "1", "used": "1"}):
                O.get_odds(force=force)
        return len(calls)

    def test_paid_calls_only_when_needed(self):
        self.assertEqual(self.pull(120, force=False), 0)       # 2 h old: reuse (6 h rule)
        self.assertEqual(self.pull(7 * 60, force=False), 1)    # 7 h old: refresh
        self.assertEqual(self.pull(20, force=True), 0)         # forced, but only 20 min old: no second charge
        self.assertEqual(self.pull(90, force=True), 1)         # forced and 90 min old: refresh


if __name__ == "__main__":
    unittest.main()
