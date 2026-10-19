# Narrative Radar

Telegram alert bot for emerging crypto narratives and recently listed Solana pairs. It reads CoinGecko trending coins and crypto-related Google News headlines, optionally checks X recent search when an X API token is configured, and compares those signals with recently profiled or boosted tokens on DexScreener.

No wallet connection, trade execution or paid hosting is required. This is an experimental keyword monitor, not investment advice or a scam detector.

## Activate your Telegram bot

1. Open [@BotFather](https://t.me/BotFather). If you shared a bot token, revoke it with `/revoke` and generate a replacement.
2. In this GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Create `TELEGRAM_BOT_TOKEN` and paste the **new** token there. Never commit it to the repository or send it in chat.
4. Open your Telegram bot, send `/start`, then open **Actions → Narrative Radar → Run workflow** on GitHub.
5. The next successful workflow run answers `/start` and enables alerts for the first private chat that starts the bot. Future scheduled runs check roughly every five minutes.

Optional security setting: set the `TELEGRAM_CHAT_ID` secret to your numeric Telegram chat ID to restrict the bot to that chat before any `/start` command. Without this value, **the first private chat to run `/start` becomes the owner**. Make sure you send `/start` yourself before running the workflow and preferably configure `TELEGRAM_CHAT_ID`.

## Commands

- `/start` — enable notifications
- `/status` — last scan and number of alerts
- `/stop` — pause notifications
- `/help` — command list

Commands are processed by GitHub Actions on its next scheduled run, so replies are **not instant**. Scheduled jobs may be delayed or skipped under GitHub load.

## Data sources

- CoinGecko trending coins (public data, best effort)
- Google News RSS search for crypto and memecoin headlines (public data, best effort)
- DexScreener newest token profiles and boosts, plus token-pair metrics
- X recent search (optional, needs `X_BEARER_TOKEN` API access; not required for free mode)

The bot does **not** browse a logged-in X account or scrape the X website. The free mode does not claim to directly monitor X trends.

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

Use **Actions → Narrative Radar → Run workflow** for a manual scan. Open the job logs to troubleshoot missing secrets or upstream API errors. Standard GitHub-hosted Actions runners are free for public repositories within GitHub's current policy.

No API token should be placed in any tracked file, workflow definition, commit or issue.
