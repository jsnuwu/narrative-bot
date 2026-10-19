import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("narrative-bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER = os.getenv("TELEGRAM_CHAT_ID", "").strip()
X_TOKEN = os.getenv("X_BEARER_TOKEN", "").strip()
LIQUIDITY_MIN = float(os.getenv("MIN_LIQUIDITY_USD", "8000"))
VOLUME_MIN = float(os.getenv("MIN_VOLUME_24H_USD", "3000"))
MAX_AGE_HOURS = float(os.getenv("MAX_AGE_HOURS", "72"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS_PER_RUN", "75"))
MAX_ALERTS = int(os.getenv("MAX_ALERTS_PER_RUN", "5"))
STATE_PATH = Path(".state/state.json")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "narrative-radar/1.0 (personal monitoring)"})
STOPWORDS = set("""
crypto cryptocurrency cryptocurrencies bitcoin ethereum solana blockchain trading traders
token tokens coin coins price market markets memecoin memecoins meme launch launched
latest update updates today yesterday tomorrow after before about against first this
that these those with from what when where which their there while into over
under very your have will been being than then once more most some only also
like just news says said report reports share shares rise falls could would should
and for the not are was were has had its but you all any new now out how
who why usd usdt eth btc sol nft defi web3 ai airdrop pump official
""".split())
NEWS_URL = "https://news.google.com/rss/search"
DEX_URL = "https://api.dexscreener.com"

def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["seen"] = list(state.get("seen", []))[-3000:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

def get_json(url, **kwargs):
    response = SESSION.get(url, timeout=18, **kwargs)
    response.raise_for_status()
    return response.json()

def telegram(method, payload):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    response = SESSION.post("https://api.telegram.org/bot" + TOKEN + "/" + method, json=payload, timeout=18)
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected " + method + ": " + str(result.get("description")))
    return result.get("result")

def send(chat_id, text):
    return telegram("sendMessage", {"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True})

def handle_commands(state):
    offset = int(state.get("offset", 0))
    updates = telegram("getUpdates", {"offset": offset, "limit": 100, "timeout": 0, "allowed_updates": ["message"]})
    for update in updates:
        state["offset"] = max(int(state.get("offset", 0)), int(update["update_id"]) + 1)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        command = (message.get("text") or "").strip().split(" ", 1)[0].split("@", 1)[0].lower()
        if not chat_id or chat.get("type") != "private" or command not in {"/start", "/help", "/status", "/stop"}:
            continue
        owner_id = OWNER or str(state.get("owner", ""))
        if command == "/start" and not owner_id:
            state["owner"] = chat_id
            owner_id = chat_id
        if chat_id != owner_id:
            send(chat_id, "Dieser Bot ist bereits eingerichtet.")
            continue
        if command == "/stop":
            state["enabled"] = False
            send(chat_id, "Benachrichtigungen pausiert. /start aktiviert sie wieder.")
        elif command == "/status":
            last = state.get("last_scan", "noch nicht")
            sent = int(state.get("alerts_sent", 0))
            send(chat_id, "Narrative Radar\nStatus: " + ("aktiv" if state.get("enabled", True) else "pausiert") + "\nLetzter Scan (UTC): " + last + "\nAlerts gesamt: " + str(sent) + "\nX-Datenquelle: " + ("aktiv" if X_TOKEN else "nicht konfiguriert") + "\nScans etwa alle 5 Minuten (GitHub Actions).")
        else:
            state["enabled"] = True
            send(chat_id, "✅ Narrative Radar aktiviert!\n\nIch prüfe neue Solana-Token gegen öffentliche Trendsignale und sende passende Treffer.\n\n/status = Status\n/stop = Alerts pausieren\n/start = Aktivieren\n\nDie Antworten kommen beim nächsten GitHub-Actions-Lauf, nicht sofort. X-Suche braucht optional API-Zugang. Kein automatischer Handel.")
    if OWNER:
        state["owner"] = OWNER
    save_state(state)

def clean_term(value):
    value = re.sub(r"[^a-z0-9]+", "", value.lower())
    if len(value) < 3 or len(value) > 24 or value.isdigit() or value in STOPWORDS:
        return ""
    return value

def extract_terms(text):
    text = re.sub(r"https?://\S+", " ", text)
    matches = re.findall(r"(?<![a-zA-Z])[$#][A-Za-z][A-Za-z0-9]{2,20}\b", text)
    matches += re.findall(r"\b[A-Z][A-Za-z0-9]{3,20}\b", text)
    return {term for raw in matches if (term := clean_term(raw))}

def trend_signals():
    scores = Counter()
    sources = {}
    if X_TOKEN:
        try:
            payload = get_json(
                "https://api.x.com/2/tweets/search/recent",
                headers={"Authorization": "Bearer " + X_TOKEN},
                params={"query": '(crypto OR memecoin OR solana OR "AI agent") lang:en -is:retweet', "max_results": 100}
            )
            for post in payload.get("data", []):
                for term in extract_terms(post.get("text", "")):
                    scores[term] += 2
                    sources.setdefault(term, "X")
        except (requests.RequestException, ValueError) as exc:
            log.warning("X signal unavailable: %s", exc)
    try:
        response = SESSION.get(NEWS_URL, params={"q": "(solana OR memecoin OR crypto) when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"}, timeout=18)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall(".//item")[:70]:
            headline = item.findtext("title") or ""
            for term in extract_terms(headline):
                scores[term] += 1
                sources.setdefault(term, "Google News")
    except (requests.RequestException, ET.ParseError) as exc:
        log.warning("News signal unavailable: %s", exc)
    try:
        payload = get_json("https://api.coingecko.com/api/v3/search/trending")
        for entry in payload.get("coins", [])[:15]:
            item = entry.get("item") or {}
            for raw in (item.get("name", ""), item.get("symbol", "")):
                term = clean_term(raw)
                if term:
                    scores[term] += 4
                    sources[term] = "CoinGecko Trending"
    except (requests.RequestException, ValueError) as exc:
        log.warning("CoinGecko signal unavailable: %s", exc)
    ranked = [(term, count, sources[term]) for term, count in scores.items() if count >= 2]
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked[:35]

def candidates():
    results = {}
    for endpoint in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
        try:
            payload = get_json(DEX_URL + endpoint)
            for item in payload if isinstance(payload, list) else []:
                if item.get("chainId") == "solana" and item.get("tokenAddress"):
                    results[item["tokenAddress"]] = item
        except (requests.RequestException, ValueError) as exc:
            log.warning("DEX candidate feed unavailable: %s", exc)
    return list(results.values())[:MAX_TOKENS]

def fetch_pairs(address):
    try:
        pairs = get_json(DEX_URL + "/token-pairs/v1/solana/" + quote(address, safe=""))
        return pairs if isinstance(pairs, list) else []
    except (requests.RequestException, ValueError) as exc:
        log.warning("Pair lookup failed: %s", exc)
        return []

def matching_trends(pair, trends):
    token = pair.get("baseToken") or {}
    fields = [str(token.get("name") or ""), str(token.get("symbol") or "")]
    words = {clean_term(part) for field in fields for part in re.findall(r"[A-Za-z0-9]+", field)}
    joined = {clean_term(field) for field in fields}
    found = [t for t in trends if t[0] in words or t[0] in joined]
    return found[:3]

def alert_for(pair, trends):
    if pair.get("chainId") != "solana":
        return None
    created = pair.get("pairCreatedAt")
    if not created:
        return None
    age = (time.time() * 1000 - float(created)) / 3600000
    if age < 0 or age > MAX_AGE_HOURS:
        return None
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol = float((pair.get("volume") or {}).get("h24") or 0)
    if liq < LIQUIDITY_MIN or vol < VOLUME_MIN:
        return None
    hits = matching_trends(pair, trends)
    if not hits:
        return None
    token = pair.get("baseToken") or {}
    address = token.get("address") or ""
    if not address:
        return None
    text = (
        "🚨 NARRATIVE MATCH\n\n"
        + str(token.get("name") or "?") + " ($" + str(token.get("symbol") or "?") + ")\n"
        + "Trends: " + ", ".join(t[0] + " (" + t[2] + ")" for t in hits) + "\n"
        + "Chain: Solana\n"
        + "Pair-Alter: " + format(age, ".1f") + " h\n"
        + "Liquidität: $" + format(liq, ",.0f") + "\n"
        + "Volumen 24 h: $" + format(vol, ",.0f") + "\n"
        + "Contract: " + address + "\n"
        + "Chart: " + str(pair.get("url") or "https://dexscreener.com/solana/" + address) + "\n\n"
        + "⚠️ Keyword-Abgleich, kein Sicherheitscheck oder Kaufsignal. Contract und Liquidität selbst prüfen."
    )
    return {"text": text, "score": sum(t[1] for t in hits), "vol": vol}

def run():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN secret is required")
    state = load_state()
    handle_commands(state)
    owner = OWNER or str(state.get("owner", ""))
    if not owner or not state.get("enabled", True):
        log.info("Waiting for /start or paused")
        return
    trends = trend_signals()
    log.info("Trend terms: %s", len(trends))
    seen = set(state.get("seen", []))
    alerts = []
    for profile in candidates() if trends else []:
        address = profile.get("tokenAddress")
        for pair in fetch_pairs(address):
            key = pair.get("pairAddress") or address
            if key in seen:
                continue
            result = alert_for(pair, trends)
            if result:
                alerts.append((result["score"], result["vol"], key, result["text"]))
        time.sleep(0.12)
    alerts.sort(reverse=True)
    count = 0
    for _, _, key, message in alerts[:MAX_ALERTS]:
        send(owner, message)
        seen.add(key)
        count += 1
        time.sleep(0.3)
    state["seen"] = sorted(seen)[-3000:]
    state["last_scan"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    state["alerts_sent"] = int(state.get("alerts_sent", 0)) + count
    save_state(state)
    log.info("Sent %s alerts", count)

if __name__ == "__main__":
    run()
