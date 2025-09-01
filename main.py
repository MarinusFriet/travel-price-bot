import os
import json
import requests

# -------- Config --------
DEFAULT_CONFIG = {
    "origins": ["AMS", "BRU", "DUS"],
    "destinations": ["USM", "KBV", "HKT"],  # Koh Samui, Krabi, Phuket
    "outbound_dates": ["2025-04-17", "2025-04-18", "2025-04-19"],
    "return_dates": ["2025-05-03", "2025-05-04", "2025-05-05"],
    "prefer_after_17": True,
    "max_total_duration_hours": 20,
    "max_stops": 1,
    "currency": "EUR",
    "adults": 2,
    "children": [],
    "timeout_seconds": 20
}

def load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(user_cfg or {})
        return merged
    return DEFAULT_CONFIG

CONFIG = load_config()

# -------- Env vars --------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")

if not all([AMADEUS_API_KEY, AMADEUS_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    raise SystemExit("❌ ERROR: Missing required environment variables.")

# -------- Helpers --------
def telegram_send(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def get_access_token():
    url = f"{AMADEUS_HOST}/v1/security/oauth2/token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

def search_flights(token, origin, dest, dep, ret):
    url = f"{AMADEUS_HOST}/v2/shopping/flight-offers"
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep,
        "returnDate": ret,
        "adults": CONFIG["adults"],
        "currencyCode": CONFIG["currency"],
        "max": 50,
        "maxNumberOfStops": CONFIG["max_stops"],
    }
    resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 400:
        return []  # bad request, skip this combo
    resp.raise_for_status()
    return resp.json().get("data", [])

# -------- Main logic --------
def main():
    token = get_access_token()
    all_offers = []
    debug_summary = []

    for origin in CONFIG["origins"]:
        for dest in CONFIG["destinations"]:
            for dep in CONFIG["outbound_dates"]:
                for ret in CONFIG["return_dates"]:
                    offers = search_flights(token, origin, dest, dep, ret)
                    debug_summary.append(f"{origin}→{dest} {dep}/{ret}: {len(offers)} offers")
                    all_offers.extend(offers)

    # Sort and pick top 3 cheapest
    sorted_offers = sorted(all_offers, key=lambda o: float(o["price"]["total"]))[:3]

    # Build final message
    msg = "✅ Workflow completed.\n\n"
    msg += "📊 Search summary:\n" + "\n".join(debug_summary[:15])  # show only first 15 lines max
    if len(debug_summary) > 15:
        msg += f"\n... ({len(debug_summary)-15} more combos hidden)"

    if sorted_offers:
        msg += "\n\n💸 Top 3 cheapest flights:\n"
        for i, offer in enumerate(sorted_offers, 1):
            price = offer["price"]["total"]
            itinerary = " → ".join([seg["departure"]["iataCode"] + "-" + seg["arrival"]["iataCode"]
                                    for it in offer["itineraries"] for seg in it["segments"]])
            msg += f"{i}. {price} {CONFIG['currency']} | {itinerary}\n"
    else:
        msg += "\n\n❌ No flights found."

    telegram_send(msg)

if __name__ == "__main__":
    main()
