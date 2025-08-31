import os
import json
import requests

# -------- Config --------
DEFAULT_CONFIG = {
    "origins": ["AMS", "BRU", "DUS"],
    "destinations": ["KBV", "USM", "HKT"],  # Krabi, Koh Samui, Phuket
    "outbound_dates": ["2025-04-17", "2025-04-18", "2025-04-19"],
    "return_dates": ["2025-05-03", "2025-05-04", "2025-05-05"],
    "prefer_after_18_from_AMS": True,
    "max_total_duration_hours": 20,
    "max_stops": 1,
    "currency": "EUR",
    "price_threshold_eur": 800,
    "adults": 2,
    "children": [],  # 🚨 temporarily disabled to avoid API 400
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

AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")


# ---- Telegram helper ----
def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")


# ---- Amadeus helpers ----
def get_access_token():
    url = f"{AMADEUS_HOST}/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    r = requests.post(url, data=data, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def search_flights(token, origin, destination, dep, ret):
    url = f"{AMADEUS_HOST}/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": dep,
        "returnDate": ret,
        "adults": CONFIG["adults"],
        "currencyCode": CONFIG["currency"],
        "maxNumberOfStops": CONFIG["max_stops"],
        "max": 50,
    }
    # 🚨 no children param until we fix
    r = requests.get(url, headers=headers, params=params, timeout=20)
    if r.status_code != 200:
        raise Exception(f"API error {r.status_code}: {r.text}")
    return r.json().get("data", [])


def main():
    if not (AMADEUS_API_KEY and AMADEUS_API_SECRET and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("❌ ERROR: Missing required environment variables")
        return

    try:
        token = get_access_token()
    except Exception as e:
        send_telegram(f"❌ Failed to get Amadeus token: {e}")
        return

    found_any = False
    for origin in CONFIG["origins"]:
        for dest in CONFIG["destinations"]:
            for dep in CONFIG["outbound_dates"]:
                for ret in CONFIG["return_dates"]:
                    try:
                        offers = search_flights(token, origin, dest, dep, ret)
                        if not offers:
                            send_telegram(f"ℹ️ No flights found {origin}->{dest} {dep}/{ret}")
                            continue
                        found_any = True
                        sorted_offers = sorted(offers, key=lambda o: float(o["price"]["total"]))
                        top3 = sorted_offers[:3]

                        msg = f"✈️ Top {len(top3)} flights {origin}->{dest} ({dep} / {ret}):\n"
                        for o in top3:
                            price = o["price"]["total"]
                            carrier = o["itineraries"][0]["segments"][0]["carrierCode"]
                            duration = o["itineraries"][0]["duration"]
                            msg += f"- {carrier} {duration} €{price}\n"
                        send_telegram(msg)

                    except Exception as e:
                        send_telegram(f"⚠️ Error on {origin}->{dest} {dep}/{ret}: {e}")

    if not found_any:
        send_telegram("ℹ️ Bot finished — no qualifying offers today.")

if __name__ == "__main__":
    main()
