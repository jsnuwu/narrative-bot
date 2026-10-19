import time
import unittest
from unittest.mock import patch

import main

class TestNarrativeRadar(unittest.TestCase):
    def test_extract_terms(self):
        terms = main.extract_terms("The #FrogArmy is trending, $FROGARMY launches on Solana")
        self.assertIn("frogarmy", terms)
        self.assertNotIn("solana", terms)

    def test_bluesky_signal_counting(self):
        posts = [
            {"post": {"record": {"text": "#FrogArmy on Solana"}}},
            {"post": {"record": {"text": "Crypto fans joining $FROGARMY right now"}}},
            {"post": {"record": {"text": "Another memecoin #FrogArmy update"}}}
        ]
        with patch.object(main, "get_json", return_value={"feed": posts}):
            result = main.bluesky_terms()
        self.assertGreaterEqual(result["frogarmy"], 3)

    def test_reddit_rss_counting(self):
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry><title>$FROGARMY launches</title></entry>
            <entry><title>More on #FrogArmy</title></entry>
        </feed>"""
        with patch.object(main.SESSION, "get") as getter:
            getter.return_value.content = rss
            result = main.reddit_terms()
        self.assertGreaterEqual(result["frogarmy"], 2)

    def test_cached_public_signals(self):
        state = {}
        with patch.object(main.time, "time", return_value=2000):
            first = main.cached_source_terms(state, "Bluesky", lambda: {"frogarmy": 4})
        with patch.object(main.time, "time", return_value=2100):
            second = main.cached_source_terms(state, "Bluesky", lambda: {"other": 7})
        self.assertEqual(first, second)
        self.assertEqual(state["sources"]["Bluesky"]["terms"]["frogarmy"], 4)

    def test_new_pair_alert(self):
        pair = {
            "chainId": "solana",
            "baseToken": {"name": "FrogArmy", "symbol": "FROGARMY", "address": "test-address"},
            "pairCreatedAt": int((time.time() - 3600) * 1000),
            "liquidity": {"usd": 20000},
            "volume": {"h24": 9000},
            "url": "https://dexscreener.com/solana/test-pair"
        }
        signal = [("frogarmy", 5, "Google News")]
        alert = main.alert_for(pair, signal)
        self.assertIsNotNone(alert)
        self.assertIn("FrogArmy", alert["text"])

    def test_old_pair_rejected(self):
        pair = {
            "chainId": "solana",
            "baseToken": {"name": "FrogArmy", "symbol": "FROGARMY", "address": "test-address"},
            "pairCreatedAt": int((time.time() - 5 * 86400) * 1000),
            "liquidity": {"usd": 20000},
            "volume": {"h24": 9000}
        }
        self.assertIsNone(main.alert_for(pair, [("frogarmy", 5, "X")]))

    def test_test_command_sends_alert(self):
        update = {
            "update_id": 400,
            "message": {"chat": {"id": 987, "type": "private"}, "text": "/test"}
        }
        state = {"owner": "987", "enabled": True}
        with patch.object(main, "telegram", return_value=[update]), patch.object(main, "send") as send, patch.object(main, "save_state"):
            main.handle_commands(state)
        send.assert_called_once()
        self.assertIn("TEST-ALARM", send.call_args.args[1])

    def test_x_is_opt_in(self):
        with patch.object(main, "X_TOKEN", "configured"), patch.object(main, "X_ENABLED", False), patch.object(main, "get_json") as getter, patch.object(main.SESSION, "get") as news:
            response = news.return_value
            response.content = b"<rss><channel></channel></rss>"
            main.trend_signals({})
        self.assertTrue(any("/search/trending" in str(call) for call in getter.call_args_list))
        self.assertFalse(any("api.x.com" in str(call) for call in getter.call_args_list))

    def test_first_start_registers_owner(self):
        update = {
            "update_id": 123,
            "message": {"chat": {"id": 987, "type": "private"}, "text": "/start"}
        }
        state = {"enabled": False}
        with patch.object(main, "OWNER", ""), patch.object(main, "telegram", return_value=[update]), patch.object(main, "send") as send, patch.object(main, "save_state"):
            main.handle_commands(state)
        self.assertEqual(state["owner"], "987")
        self.assertTrue(state["enabled"])
        self.assertEqual(state["offset"], 124)
        send.assert_called_once()

if __name__ == "__main__":
    unittest.main()
