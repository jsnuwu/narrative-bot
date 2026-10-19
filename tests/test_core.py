import time
import unittest
from unittest.mock import patch

import main

class TestNarrativeRadar(unittest.TestCase):
    def test_extract_terms(self):
        terms = main.extract_terms("The #FrogArmy is trending, $FROGARMY launches on Solana")
        self.assertIn("frogarmy", terms)
        self.assertNotIn("solana", terms)

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
