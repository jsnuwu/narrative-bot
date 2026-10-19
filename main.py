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
X_ENABLED = os.getenv("ENABLE_X_API", "false").lower() == "true"
X_REFRESH_HOURS = max(6, float(os.getenv("X_REFRESH_HOURS", "6")))
LIQUIDITY_MIN = float(os.getenv("MIN_LIQUIDITY_USD", "8000"))
VOLUME_MIN = float(os.getenv("MIN_VOLUME_24H_USD", "3000"))
MAX_AGE_HOURS = float(os.getenv("MAX_AGE_HOURS", "72"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS_PER_RUN", "75"))
MAX_ALERTS = int(os.getenv("MAX_ALERTS_PER_RUN", "5"))
DAILY_REPORT = os.getenv("DAILY_REPORT", "true").lower() == "true"
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
 yahoo finance coindesk cryptoticker podcast weekly newsletter headline headlines
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

def register_commands():
    commands = [
        {"command": "start", "description": "Benachrichtigungen aktivieren"},
        {"command": "status", "description": "Bot-Status anzeigen"},
        {"command": "test", "description": "Testnachricht aufs Handy senden"},
        {"command": "stop", "description": "Benachrichtigungen pausieren"},
        {"command": "help", "description": "Alle Befehle anzeigen"}
    ]
    telegram("setMyCommands", {"commands": commands})
    log.info("Telegram commands registered")

def handle_commands(state):
    offset = int(state.get("offset", 0))
    updates = telegram("getUpdates", {"offset": offset, "limit": 100, "timeout": 0, "allowed_updates": ["message"]})
    log.info("Telegram updates received: %s", len(updates))
    for update in updates:
        state["offset"] = max(int(state.get("offset", 0)), int(update["update_id"]) + 1)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        content = re.sub(r"^/\s+", "/", (message.get("text") or "").strip())
        command = content.split(" ", 1)[0].split("@", 1)[0].lower()
        if not chat_id or chat.get("type") != "private" or command not in {"/start", "/help", "/status", "/stop", "/test"}:
            continue
        owner_id = OWNER or str(state.get("owner", ""))
        if command == "/start" and not owner_id:
            state["owner"] = chat_id
            owner_id = chat_id
        log.info("Processing Telegram command %s", command)
        if chat_id != owner_id:
            send(chat_id, "Dieser Bot ist bereits eingerichtet.")
            continue
        if command == "/stop":
            state["enabled"] = False
            send(chat_id, "Benachrichtigungen pausiert. /start aktiviert sie wieder.")
        elif command == "/test":
            send(chat_id, "🔔 TEST-ALARM\n\nDie Telegram-Benachrichtigungen funktionieren. Dies ist kein echter Token-Fund.")
        elif command == "/status":
            last = state.get("last_scan", "noch nicht")
            sent = int(state.get("alerts_sent", 0))
            send(chat_id, "Narrative Radar\nStatus: " + ("aktiv" if state.get("enabled", True) else "pausiert") + "\nLetzter Scan (UTC): " + last + "\nAlerts gesamt: " + str(sent) + "\nX-Datenquelle: " + ("aktiv (kostenpflichtige API)" if X_TOKEN and X_ENABLED else "deaktiviert") + "\nScans etwa alle 5 Minuten (GitHub Actions).")
        elif command == "/help":
            send(chat_id, "Narrative Radar\n/start - Alerts aktivieren\n/status - Status anzeigen\n/test - Testnachricht senden\n/stop - Alerts pausieren\n/help - Befehle anzeigen\n\nAntworten erfolgen beim naechsten GitHub-Actions-Lauf.")
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

def bluesky_terms():
    terms = Counter()
    try:
        payload = get_json(
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getFeed",
            params={
                "feed": "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot",
                "limit": 100
            }
        )
        for entry in payload.get("feed", []):
            record = (entry.get("post") or {}).get("record") or {}
            content = record.get("text", "")
            if not re.search(r"\b(?:crypto|solana|memecoin|memetoken|token|blockchain|defi)\b|\$[A-Za-z]{3,15}\b", content, re.IGNORECASE):
                continue
            for term in extract_terms(content):
                terms[term] += 1
    except (requests.RequestException, ValueError) as exc:
        log.warning("Bluesky Discover feed unavailable: %s", exc)
    return {term: count for term, count in terms.most_common(70) if count >= 2}

def reddit_terms():
    terms = Counter()
    for subreddit in ("solana",):
        try:
            response = SESSION.get(
                "https://www.reddit.com/r/" + subreddit + "/new/.rss",
                params={"limit": 35},
                timeout=18,
                headers={"User-Agent": "narrative-radar/1.0 personal research bot"}
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            for entry in entries:
                title = entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
                for term in extract_terms(title):
                    terms[term] += 1
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("Reddit %s unavailable: %s", subreddit, exc)
    return {term: count for term, count in terms.most_common(70) if count >= 2}


def cached_source_terms(state, name, fetcher, interval=1800):
    now = time.time()
    cache = state.get("sources", {})
    entry = cache.get(name) or {}
    previous = float(entry.get("updated_at", 0))
    if now - previous >= interval or entry.get("version") != 2:
        terms = fetcher()
        if terms:
            entry = {"updated_at": now, "terms": terms, "version": 2}
            cache[name] = entry
            state["sources"] = cache
            log.info("%s source: %s repeated terms", name, len(terms))
        else:
            if now - previous > 21600:
                entry["terms"] = {}
                log.warning("%s missing for over six hours, discarding stale terms", name)
            else:
                log.warning("%s returned no repeated terms, temporarily retaining recent signals", name)
            entry["updated_at"] = now - interval + min(interval, 300)
            entry["version"] = 2
            cache[name] = entry
            state["sources"] = cache
    return entry.get("terms", {})


def trend_signals(state):
    scores = Counter()
    sources = {}
    if X_ENABLED and X_TOKEN:
        now = time.time()
        previous = float(state.get("x_last_fetch", 0))
        if now - previous >= X_REFRESH_HOURS * 3600:
            state["x_last_fetch"] = now
            try:
                payload = get_json(
                    "https://api.x.com/2/tweets/search/recent",
                    headers={"Authorization": "Bearer " + X_TOKEN},
                    params={"query": '(crypto OR memecoin OR solana OR "AI agent") lang:en -is:retweet', "max_results": 10}
                )
                terms = Counter()
                for post in payload.get("data", []):
                    for term in extract_terms(post.get("text", "")):
                        terms[term] += 2
                state["x_cached_terms"] = dict(terms.most_common(40))
                log.info("X recent search fetched up to 10 posts")
            except (requests.RequestException, ValueError) as exc:
                log.warning("X signal unavailable: %s", exc)
        for term, count in state.get("x_cached_terms", {}).items():
            scores[term] += int(count)
            sources.setdefault(term, "X")
    try:
        response = SESSION.get(NEWS_URL, params={"q": "(solana OR memecoin OR crypto) when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"}, timeout=18)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for item in root.findall(".//item")[:70]:
            headline = (item.findtext("title") or "").rsplit(" - ", 1)[0]
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
    for name, collector in (("Bluesky", bluesky_terms), ("Reddit", reddit_terms)):
        for term, count in cached_source_terms(state, name, collector).items():
            scores[term] += min(int(count), 12)
            sources.setdefault(term, name)
    ranked = [(term, count, sources[term]) for term, count in scores.items() if count >= 2]
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked[:50]

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

def candidate_pairs(profiles):
    addresses = list(dict.fromkeys(
        str(profile.get("tokenAddress") or "").strip()
        for profile in profiles
        if profile.get("chainId") == "solana" and profile.get("tokenAddress")
    ))[:MAX_TOKENS]
    pairs = {}
    for offset in range(0, len(addresses), 30):
        batch = addresses[offset:offset + 30]
        try:
            payload = get_json(DEX_URL + "/tokens/v1/solana/" + ",".join(quote(a, safe="") for a in batch))
            allowed = set(batch)
            for pair in payload if isinstance(payload, list) else []:
                if pair.get("chainId") != "solana":
                    continue
                if str((pair.get("baseToken") or {}).get("address") or "") not in allowed:
                    continue
                key = str(pair.get("pairAddress") or "")
                if key:
                    pairs[key] = pair
        except (requests.RequestException, ValueError) as exc:
            log.warning("DEX batch lookup failed (%s addresses): %s", len(batch), exc)
    log.info("DEX: %s addresses resolved to %s pairs in %s batches",
             len(addresses), len(pairs), (len(addresses) + 29) // 30)
    return list(pairs.values())


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

def watchlist_candidate(pair):
    if pair.get("chainId") != "solana":
        return None
    token = pair.get("baseToken") or {}
    address = str(token.get("address") or "")
    created = pair.get("pairCreatedAt")
    if not address or not created:
        return None
    age = (time.time() * 1000 - float(created)) / 3600000
    if not 0 <= age <= min(MAX_AGE_HOURS, 48):
        return None
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol = float((pair.get("volume") or {}).get("h24") or 0)
    if liq < LIQUIDITY_MIN or vol < VOLUME_MIN:
        return None
    return {
        "address": address,
        "name": str(token.get("name") or "?"),
        "symbol": str(token.get("symbol") or "?"),
        "age": age,
        "liquidity": liq,
        "volume": vol,
        "url": str(pair.get("url") or "https://dexscreener.com/solana/" + address),
        "pair": str(pair.get("pairAddress") or address)
    }


def publish_signals(trends, matched, watchlist):
    output = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "narrative-radar",
        "chain": "solana",
        "trends": [{"term": term, "score": score, "source": source} for term, score, source in trends[:30]],
        "matches": sorted(matched.values(), key=lambda row: (-row["score"], -row["volume_24h_usd"]))[:20],
        "watchlist": sorted(watchlist.values(), key=lambda row: -row["volume"])[:15]
    }
    target = Path("signals/latest.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("Published %s narrative matches and %s watchlist pools", len(output["matches"]), len(output["watchlist"]))
    return output


def daily_digest_text(trends, watchlist, narrative_count):
    lines = [
        "📡 NARRATIVE RADAR - Tagesbericht",
        "",
        "Trendbegriffe beobachtet: " + str(len(trends)),
        "Bestätigte Narrative-Matches in diesem Scan: " + str(narrative_count),
        "",
    ]
    if watchlist:
        lines.append("📈 Neue Solana-Pools nach Handelsvolumen (kein bestätigter Narrative-Match):")
        for i, item in enumerate(watchlist[:3], 1):
            lines.extend([
                "",
                str(i) + ". " + item["name"] + " ($" + item["symbol"] + ")",
                "Alter: " + format(item["age"], ".1f") + " h | Liquidität: $" + format(item["liquidity"], ",.0f"),
                "Volumen 24 h: $" + format(item["volume"], ",.0f"),
                "Contract: " + item["address"],
                item["url"]
            ])
    else:
        lines.append("Aktuell keine geeigneten neuen Solana-Pools in der beobachteten Auswahl.")
    lines.extend([
        "",
        "⚠️ Beobachtung, keine Kaufempfehlung. Token können manipuliert sein; insbesondere bezahlte Boosts sind kein Qualitätssignal.",
        "Für eine sofortige Testmeldung: /test",
        "Alerts pausieren: /stop"
    ])
    return "\n".join(lines)


def scan_candidates(trends, seen, profiles=None):
    profiles = candidates() if profiles is None else profiles
    log.info("Solana candidate tokens: %s", len(profiles))
    matched = {}
    watchlist = {}
    new_alerts = {}
    for pair in candidate_pairs(profiles):
        token = pair.get("baseToken") or {}
        address = str(token.get("address") or "")
        if not address:
            continue
        pool = watchlist_candidate(pair)
        if pool:
            old = watchlist.get(address)
            if old is None or (pool["volume"], pool["liquidity"]) > (old["volume"], old["liquidity"]):
                watchlist[address] = pool
        if not trends:
            continue
        result = alert_for(pair, trends)
        if not result:
            continue
        hits = matching_trends(pair, trends)
        details = {
            "mint": address,
            "name": str(token.get("name") or ""),
            "symbol": str(token.get("symbol") or ""),
            "score": int(result["score"]),
            "trend_terms": [t[0] for t in hits],
            "sources": list(dict.fromkeys(t[2] for t in hits)),
            "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or 0),
            "volume_24h_usd": float((pair.get("volume") or {}).get("h24") or 0),
            "url": str(pair.get("url") or ""),
        }
        old = matched.get(address)
        if old is None or (details["score"], details["volume_24h_usd"]) > (old["score"], old["volume_24h_usd"]):
            matched[address] = details
        if address not in seen:
            previous = new_alerts.get(address)
            candidate = (result["score"], result["vol"], address, result["text"])
            if previous is None or candidate[:2] > previous[:2]:
                new_alerts[address] = candidate
    alerts = sorted(new_alerts.values(), reverse=True)
    return matched, watchlist, alerts


def run():
    state = load_state()
    if TOKEN:
        try:
            register_commands()
            handle_commands(state)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            log.warning("Telegram command processing unavailable; continuing data feed: %s", exc)
    else:
        log.warning("Telegram token missing; scanning for TradeBot feed without Telegram notifications")
    owner = OWNER or str(state.get("owner", ""))
    notify = bool(TOKEN and owner and state.get("enabled", True))
    trends = trend_signals(state)
    log.info("Trend terms: %s", len(trends))
    seen = set(state.get("seen", []))
    matched, watchlist, alerts = scan_candidates(trends, seen)
    publish_signals(trends, matched, watchlist)
    count = 0
    if notify:
        for _, _, key, message in alerts[:MAX_ALERTS]:
            try:
                send(owner, message)
            except (requests.RequestException, RuntimeError) as exc:
                log.warning("Alert delivery failed; will retry later: %s", exc)
                continue
            seen.add(key)
            count += 1
            time.sleep(0.3)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_sent = False
    if notify and DAILY_REPORT and state.get("daily_report_date") != today:
        ranked = sorted(watchlist.values(), key=lambda item: (item["volume"], item["liquidity"]), reverse=True)
        try:
            send(owner, daily_digest_text(trends, ranked, count))
        except (requests.RequestException, RuntimeError) as exc:
            log.warning("Daily digest delivery failed; will retry later: %s", exc)
        else:
            state["daily_report_date"] = today
            daily_sent = True
    state["seen"] = sorted(seen)[-3000:]
    state["last_scan"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    state["alerts_sent"] = int(state.get("alerts_sent", 0)) + count
    save_state(state)
    log.info("Sent %s narrative alerts, daily digest: %s, matched tokens: %s, watchlist: %s",
             count, daily_sent, len(matched), len(watchlist))

if __name__ == "__main__":
    run()
