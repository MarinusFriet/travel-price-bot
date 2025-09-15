import os
import json
import time
import requests

# -------- Config --------
CONFIG = {
    "origins": ["AMS"],   # Amsterdam
    "destination": "KBV", # Krabi
    "outbound_dates": ["2026-04-18", "2026-04-19"],  # Sat 18 or Sun 19 April 2026
    "return_dates": ["2026-05-04", "2026-05-05"],    # Mon 4 or Tue 5 May 2026
    "max_total_duration_hours": 24,
    "max_stops": 1,
    "currency": "EUR",
    "price_threshold_eur": None,   # No price filter
    "adults": 1,
    "children": [],
    "timeout_seconds": 60
}

# -------- Environment Vars --------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")

# -------- Utils --------
def log(msg):
    print(msg, flush=True)

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ Telegram not configured.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log(f"⚠️ Telegram send failed: {e}")

# -------- Amadeus Auth --------
def get_access_token():
    url = f"{AMADEUS_HOST}/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    resp = requests.post(url, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]

# -------- Flight Search --------
def search_flights(token, origin, destination, depart, ret):
    url = f"{AMADEUS_HOST}/v2/shopping/flight-offers"
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": depart,
        "returnDate": ret,
        "adults": CONFIG["adults"],
        "currencyCode": CONFIG["currency"],
        "max": 50,
    }
    if CONFIG["children"]:
        params["children"] = len(CONFIG["children"])
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=CONFIG["timeout_seconds"])
    if resp.status_code != 200:
        return [], resp.text
    return resp.json().get("data", []), None

# -------- Main --------
def main():
    missing = [k for k, v in {
        "AMADEUS_API_KEY": AMADEUS_API_KEY,
        "AMADEUS_API_SECRET": AMADEUS_API_SECRET,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID
    }.items() if not v]
    if missing:
        raise RuntimeError(f"❌ Missing required environment variables: {missing}")

    token = get_access_token()
    all_offers = []

    for origin in CONFIG["origins"]:
        for depart in CONFIG["outbound_dates"]:
            for ret in CONFIG["return_dates"]:
                log(f"🔎 Searching {origin}→{CONFIG['destination']} {depart}/{ret}")
                offers, error = search_flights(token, origin, CONFIG["destination"], depart, ret)
                if error:
                    log(f"❌ Error: {error}")
                else:
                    all_offers.extend(offers)

    if not all_offers:
        msg = "✅ Workflow finished.\n❌ No offers found."
        log(msg)
        send_telegram_message(msg)
        return

    # Sort by price
    all_offers.sort(key=lambda o: float(o["price"]["total"]))
    best_offers = all_offers[:3]

    lines = ["✅ Workflow finished.\n📊 Top 3 cheapest flights:"]
    for o in best_offers:
        price = o["price"]["total"]
        itineraries = []
        for itin in o["itineraries"]:
            segs = [f"{s['departure']['iataCode']}→{s['arrival']['iataCode']}" for s in itin["segments"]]
            itineraries.append(" - ".join(segs))
        lines.append(f"💶 {price} EUR | {' / '.join(itineraries)}")

    msg = "\n".join(lines)
    log(msg)
    send_telegram_message(msg)

if __name__ == "__main__":
    main()
