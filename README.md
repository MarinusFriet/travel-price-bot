# Travel Price Bot (Free stack)
Track flight prices for your specific Amsterdam/Brussels/Düsseldorf → Krabi trip window using **Amadeus Self‑Service API (free tier)**, **GitHub Actions (free for public repos)**, and **Telegram Bot** notifications.

## What it does
- Searches daily across your date windows:
  - Outbound: 2025-04-17 to 2025-04-19
  - Return: 2025-05-03 to 2025-05-05
  - Origins: AMS, BRU, DUS → KBV
- Filters: max 1 stop, total duration ≤ 20 hours, 2 adults + 2 children (ages 3,5).
- Prefers AMS departures after 18:00 (configurable; off for BRU/DUS).
- Sends Telegram alerts with the **cheapest matching options** per origin/date pair (or only if below your price threshold, configurable).

> Uses only free tools: Amadeus Self‑Service monthly free quota, GitHub Actions schedule, Telegram Bot API.

## Quick start
1. **Create accounts/keys (free):**
   - Amadeus for Developers: create an app to get `AMADEUS_API_KEY` and `AMADEUS_API_SECRET` (Self‑Service).  
   - Telegram: talk to **@BotFather** → create bot → get `TELEGRAM_BOT_TOKEN`. Get your `TELEGRAM_CHAT_ID` (see below).

2. **Fork/upload this repo** as **public** on GitHub.

3. **Add GitHub Secrets** (Settings → Secrets and variables → Actions → *New repository secret*):
   - `AMADEUS_API_KEY`
   - `AMADEUS_API_SECRET`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

4. **(Optional) Edit `config.json`** for thresholds or to tweak times/dates/origins.

5. The bot runs **daily at 06:10 UTC** (08:10 Amsterdam) and sends a Telegram message when it finds a qualifying price (or always, if threshold not set). You can also run manually via the “Run workflow” button.

## Get your Telegram chat id
- Start a chat with your bot, send any message (e.g. `/start`).  
- Open: `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates` and find `"chat":{"id": ... }`

## Notes
- Amadeus Self‑Service free tier is enough for this narrow search. You can raise/lower the schedule if needed.
- The script does **not** persist previous prices; it simply alerts cheapest matches per search each run. You can enable thresholds in `config.json` to reduce noise.
- Hidden‑city/throwaway‑ticket tactics aren’t automated here, by design.

## Local test
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export AMADEUS_API_KEY=xxx AMADEUS_API_SECRET=yyy TELEGRAM_BOT_TOKEN=zzz TELEGRAM_CHAT_ID=111
python main.py
```
