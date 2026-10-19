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

    def test_candidate_pair_batches_and_filters_unrequested_tokens(self):
        def profile(address):
            return {"chainId": "solana", "tokenAddress": address}
        profiles = [profile("valid-" + str(i)) for i in range(31)]
        def mocked_get(url, **kwargs):
            self.assertIn("/tokens/v1/solana/", url)
            addresses = set(url.rsplit("/", 1)[-1].split(","))
            data = [{
                "chainId": "solana",
                "pairAddress": "pool-" + address,
                "baseToken": {"address": address},
            } for address in addresses]
            data.append({"chainId": "solana", "pairAddress": "fake",
                         "baseToken": {"address": "unrequested"}})
            return data
        with patch.object(main, "get_json", side_effect=mocked_get) as getter:
            pairs = main.candidate_pairs(profiles)
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(len(pairs), 31)
        self.assertNotIn("fake", {pair["pairAddress"] for pair in pairs})

    def test_seen_telegram_alert_remains_in_tradebot_feed(self):
        pair = {
            "chainId": "solana",
            "baseToken": {"name": "FrogArmy", "symbol": "FROGARMY",
                          "address": "token-frog"},
            "pairAddress": "pool-frog",
            "pairCreatedAt": int((time.time() - 3600) * 1000),
            "liquidity": {"usd": 22000},
            "volume": {"h24": 35000},
        }
        with patch.object(main, "candidate_pairs", return_value=[pair]):
            matches, watchlist, alerts = main.scan_candidates(
                [("frogarmy", 5, "Google News")], {"token-frog"},
                profiles=[{"chainId": "solana", "tokenAddress": "token-frog"}])
        self.assertEqual(len(matches), 1)
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(alerts, [])

    def test_multiple_pools_deduplicated_into_best_watchlist(self):
        token = {"name": "FrogArmy", "symbol": "FROGARMY", "address": "token-frog"}
        def pool(name, vol):
            return {"chainId": "solana", "baseToken": token, "pairAddress": name,
                    "pairCreatedAt": int((time.time() - 3600) * 1000),
                    "liquidity": {"usd": 25000}, "volume": {"h24": vol}}
        with patch.object(main, "candidate_pairs",
                          return_value=[pool("p1", 12000), pool("p2", 25000)]):
            matched, watchlist, alerts = main.scan_candidates(
                [("frogarmy", 5, "Reddit")], set(), profiles=[])
        self.assertEqual(len(matched), 1)
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(watchlist["token-frog"]["volume"], 25000)
        self.assertEqual(len(alerts), 1)

    def test_feed_still_published_with_telegram_notifications_off(self):
        saved_state = {"owner": "999", "enabled": False}
        with patch.object(main, "TOKEN", ""), patch.object(main, "load_state", return_value=saved_state), \
                patch.object(main, "save_state") as saved, \
                patch.object(main, "trend_signals", return_value=[]), \
                patch.object(main, "scan_candidates", return_value=({}, {}, [])), \
                patch.object(main, "publish_signals") as publish, \
                patch.object(main, "send") as sending:
            main.run()
        publish.assert_called_once()
        saved.assert_called_once()
        sending.assert_not_called()

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

    def test_watchlist_candidate_liquidity_filter(self):
        pair = {
            "chainId": "solana",
            "baseToken": {"name": "Example", "symbol": "EXM", "address": "example-address"},
            "pairCreatedAt": int((time.time() - 3600) * 1000),
            "liquidity": {"usd": 1000},
            "volume": {"h24": 9000}
        }
        self.assertIsNone(main.watchlist_candidate(pair))

    def test_digest_content(self):
        item = {
            "name": "Example", "symbol": "EXM", "age": 2.5,
            "liquidity": 20000, "volume": 40000,
            "address": "example-address",
            "url": "https://dexscreener.com/solana/example"
        }
        text = main.daily_digest_text([], [item], 0)
        self.assertIn("Example", text)
        self.assertIn("kein bestätigter Narrative-Match", text)

    def test_digest_empty_watchlist(self):
        self.assertIn("keine geeigneten", main.daily_digest_text([], [], 0))

    def test_expired_social_cache_is_not_reused(self):
        state = {"sources": {"Reddit": {"updated_at": 1000, "version": 2,
                                        "terms": {"oldtrend": 5}}}}
        with patch.object(main.time, "time", return_value=1000 + 7 * 3600):
            result = main.cached_source_terms(state, "Reddit", lambda: {})
        self.assertEqual(result, {})

    def test_failed_telegram_alert_is_retryable_and_feed_is_published(self):
        pair = {
            "chainId": "solana",
            "baseToken": {"name": "FrogArmy", "symbol": "FROGARMY",
                          "address": "token-frog"},
            "pairAddress": "pool-frog",
            "pairCreatedAt": int((time.time() - 3600) * 1000),
            "liquidity": {"usd": 22000},
            "volume": {"h24": 35000}
        }
        state = {"owner": "123", "enabled": True}
        with patch.object(main, "TOKEN", "not-a-real-token"), \
                patch.object(main, "load_state", return_value=state), \
                patch.object(main, "register_commands"), \
                patch.object(main, "handle_commands"), \
                patch.object(main, "save_state") as saved, \
                patch.object(main, "trend_signals", return_value=[("frogarmy", 5, "Reddit")]), \
                patch.object(main, "candidate_pairs", return_value=[pair]), \
                patch.object(main, "candidates", return_value=[]), \
                patch.object(main, "publish_signals") as published, \
                patch.object(main, "send", side_effect=RuntimeError("Telegram unavailable")):
            main.run()
        published.assert_called_once()
        saved.assert_called_once()
        self.assertEqual(state["seen"], [])
        self.assertEqual(state["alerts_sent"], 0)

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
