# Narrative Radar

Telegram alert bot for emerging crypto narratives and recently listed Solana pairs. It reads the public Bluesky Discover feed, Reddit community RSS, CoinGecko trending coins and crypto-related Google News headlines, optionally checks X recent search only when paid API access is explicitly enabled, and compares those signals with recently profiled or boosted tokens on DexScreener.

No wallet connection, trade execution or paid hosting is required. This is an experimental keyword monitor, not investment advice or a scam detector.

## Activate your Telegram bot

1. Open [@BotFather](https://t.me/BotFather). If you shared a bot token, revoke it with `/revoke` and generate a replacement.
2. In this GitHub repository, open **Settings → Environments → env → Environment secrets**.
3. Store the current token in an environment secret named `TELEGRAM_BOT_TOKEN`. Never commit it to the repository or send it in chat.
4. Open your Telegram bot, send `/start`, then open **Actions → Narrative Radar → Run workflow** on GitHub.
5. The next successful workflow run answers `/start` and enables alerts for the first private chat that starts the bot. The separate **Narrative Radar Auto** workflow attempts a scan every five minutes, although GitHub can delay or drop scheduled jobs.

**Group chat:** The bot also posts every alert to the Telegram group set in `TELEGRAM_GROUP_ID` (workflow default `-1004448227091`, overridable via the repository variable `TELEGRAM_GROUP_ID`). In that group `/top`, `/status`, `/test`, `/start` and `/stop` work as well (with privacy mode use `/top@YourBot` if other bots are present). `/stop` in the group pauses only the group; the private owner chat keeps receiving alerts and vice versa. Other groups are ignored.

Optional security setting: set the `TELEGRAM_CHAT_ID` environment secret to your numeric Telegram chat ID to restrict the bot to that chat before any `/start` command. Without this value, **the first private chat to run `/start` becomes the owner**. Make sure you send `/start` yourself before running the workflow and preferably configure `TELEGRAM_CHAT_ID`.

## Commands

- `/start` — enable notifications
- `/status` — last scan, number of scanned candidates and separate narrative/momentum alert counters
- `/top` — show the latest 3 momentum signals and observation-only new pools on Telegram
- `/test` — send a Telegram test notification on the next GitHub Actions run
- `/stop` — pause notifications
- `/help` — command list

Commands are processed by GitHub Actions on its next scheduled run, so replies are **not instant**. Scheduled jobs may be delayed or skipped under GitHub load.

## Data sources

- Bluesky public Discover feed, filtering crypto and Solana posts (no account or API key, best effort; not a platform-wide search)
- Reddit public RSS feed from r/solana (best effort; may be rate-limited)
- CoinGecko trending coins (public data, best effort)
- Google News RSS search for crypto and memecoin headlines (public data, best effort)
- DexScreener newest profiles, latest/top paid boosts and community takeovers, plus batch token-pair metrics
- GeckoTerminal public Solana new-pool feed (up to 2 pages per scan), independent of paid promotions; best effort, no API key, free-tier rate limits apply
- X recent search (optional paid API; requires both `X_BEARER_TOKEN` and the Actions variable `ENABLE_X_API=true`)

The bot does **not** browse a logged-in X account or scrape the X website. The free mode does not claim to directly monitor X trends. Public Bluesky and Reddit trend terms are refreshed at most once every 30 minutes, cached between checks, and counted only when repeated in multiple items. No social-media login or cookies are needed.

### Optional X API setup and spending control

Create an app in [X Developer Console](https://console.x.com), obtain its read-only Bearer Token, and store it under **Settings → Environments → env → Environment secrets** as `X_BEARER_TOKEN`. The token alone never triggers paid requests. To activate X polling, separately create an **Environment variable** named `ENABLE_X_API` with the value `true`. The default is `false`.

With X enabled, the bot fetches at most **10 posts once per six hours**, using the cached terms for intermediate scans. GitHub Actions cache is best effort; reset caches or simultaneous workflow runs can cause additional API reads. The six-hour interval is configurable with `X_REFRESH_HOURS` but cannot be set below 6 hours in code. X prices public post reads on a pay-per-use basis. Set a **spending limit** in X Developer Console and keep automatic credit recharges disabled to avoid surprise bills. If you require 100% free operation, leave `ENABLE_X_API=false` and do not fund X API credits.


## More discoveries without X API or Telegram spam

The bot now monitors two separate types of events:

- **Narrative match:** A newly listed Solana token's name/symbol matches a term from public news, CoinGecko and optional Bluesky/Reddit. Telegram alerts and TradeBot auto-analysis retain their existing independent eligibility checks.
- **Early momentum:** A **market-data-only observation**; no social-media narrative is claimed. A pool must be at most 24 hours old, with at least $12,000 liquidity, $25,000 volume over 24 h, $8,000 volume over the last hour, at least 25 buys **and** 10 sells in that hour, a buy/sell ratio of at least 1.2, a one-hour price rise between 8% and 120%, and no steeper than −15% change in the last five minutes. It must also clear a configurable heuristic score. This is a monitoring filter, **not** a prediction, security audit or buy recommendation. Volume and price movements can be manipulated. These signals are added separately to the public JSON as `momentum` and **are not submitted as automatically actionable Narrative Radar matches to TradeBot**.

By default momentum alerts are enabled (`MOMENTUM_ALERTS=true`) with **at most two per successful scan and six per UTC day**. The bot remembers alerted mint addresses for 72 hours, so different pools for one token do not cause repeat alerts. These controls can be changed through GitHub environment variables `MOMENTUM_ALERTS_PER_RUN`, `MOMENTUM_ALERTS_PER_DAY` and `MOMENTUM_MIN_SCORE`. If Telegram delivery fails, an alert is not marked as sent.

The `/top` command returns the last saved momentum candidates plus a short list of new pools even when no strict narrative match exists. Note that commands are processed only when a GitHub Actions scan actually runs.

The public GeckoTerminal API is free but can be rate limited or temporarily unavailable. If a source fails, the other sources continue. The DexScreener token lookup remains grouped into batches of up to 30 addresses, with 120 addresses inspected per default scan (GitHub variable `MAX_TOKENS_PER_RUN` can override this). This is **not** a guarantee of complete Solana coverage.

## Automatic Telegram messages

The bot sends a daily Telegram market report when a scan runs and the report has not been sent for the current UTC day. It also sends separate, rate-capped momentum notifications for qualifying market activity. It contains up to three recently detected Solana pools ranked by observed 24-hour trading volume, including name, contract, liquidity and DexScreener URL. **These are not verified narrative matches, audited projects or investment recommendations.** Set `DAILY_REPORT=false` as a GitHub environment variable to disable this message. The first successful run after enabling daily reporting sends the first report. Strict narrative-match alerts are separate and continue to run.

**Important:** Two GitHub workflows exist: `Narrative Radar` for push/manual tests and `Narrative Radar Auto` for five-minute scheduled scans. If the GitHub Actions list contains no runs whose Event is `schedule`, automatic monitoring is not taking place. As of the October 19, 2026 checks, the recorded runs were push/manual-triggered, so timely unattended alerts cannot yet be guaranteed. Check **Actions → Narrative Radar Auto** to ensure it is enabled, then check GitHub's scheduling status; scheduled workflows are best effort, and a successful manual run does not prove automatic scheduling works.

## Connection to TradeBot

The public feed at [signals/latest.json](signals/latest.json) is read by the always-running [TradeBot](https://github.com/jsnuwu/TradeBot) via its read-only Narrative Radar bridge. The feed contains trend terms, explicit token-name matches and a separate informational Solana watchlist. No Telegram or wallet secret is shared between repositories. The TradeBot automatically submits only **confirmed narrative matches** to its existing token analysis (subject to the user's saved settings, security controls and risk limits). **Watchlist-only entries are never bought solely for being boosted or appearing on DexScreener.**

The radar feed keeps matching tokens in the JSON even after a Telegram alert was delivered; Telegram alerts themselves remain deduplicated by token. A failure, disabled Telegram notification, or missing Telegram token no longer stops the JSON feed from being generated.

Pairs are requested from the [documented DexScreener batch endpoint](https://docs.dexscreener.com/api/reference), up to 30 token addresses per request, to reduce load compared with individual per-token requests. Pool candidates are deduplicated by token for the shared watchlist.

### Scheduled scans and fallback

GitHub Actions attempts the recurring scan every five minutes, but this is **not guaranteed**. Check the Actions event column for actual `schedule` events. If none occur, manually run [Narrative Radar Auto](.github/workflows/scheduled.yml) using *Run workflow*. The workflow also accepts `repository_dispatch` with event type `radar-scan` from a trusted external scheduler. That optional fallback requires a GitHub token with Actions permissions and must be configured securely; do not put such a token in this repo or share it in chat. The feed is deliberately considered stale by TradeBot after 45 minutes without a successful publication.

## Detection

For each new candidate Solana pair, the bot matches trend terms against token name/symbol and requires pool age no more than 72 hours, liquidity of at least $8,000 and 24-hour volume of at least $3,000. These numbers can be overridden with GitHub Actions variables named `MAX_AGE_HOURS`, `MIN_LIQUIDITY_USD`, and `MIN_VOLUME_24H_USD`. The maximum number of alerts per run is five.

DexScreener profiles and boosts are not an exhaustive listing of newly minted tokens, and boosts may be paid promotion. News/trend availability, API limits, name matches and market metrics can yield missing or false alerts. Verify contract permissions, liquidity risks, wallet concentration and social links independently.

## Running locally

Requires Python 3.12+.

```bash
python -m pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="YOUR_NEW_TOKEN"
python main.py
```

An optional `TELEGRAM_CHAT_ID` environment variable can preselect the owner. Runtime state is in `.state/state.json` and is excluded from Git. GitHub Actions uses an Actions cache to carry state between runs; cache expiration or eviction can reset seen-alert history or subscription state. Setting `TELEGRAM_CHAT_ID` makes access recovery easier.

## Operations

Use **Actions → Narrative Radar Auto → Run workflow** for a manual scan and verify scheduled events appear afterward. Open the job logs to troubleshoot missing secrets or upstream API errors. Standard GitHub-hosted Actions runners are free for public repositories within GitHub's current policy.

No API token should be placed in any tracked file, workflow definition, commit or issue.
