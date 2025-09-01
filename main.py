import os
import json
import requests
from datetime import datetime

# -------- Config --------
DEFAULT_CONFIG = {
    "origins": ["AMS"],
    "destinations": ["BKK"],   # use plural to allow multiple destinations
    "outbound_dates": ["2025-04-17"],
    "return_dates": ["2025-05-03"],
    "adults": 1,
    "children": [],
    "currency": "EUR",
    "max_stops": 1,
    "max_total_duration_hours": 20,
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

# -------- Env Vars --------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# -------- Helpers --------
def telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

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

def search_flights(token, origin, destination, dep_date, ret_date):
    url = f"{AMADEUS_HOST}/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": dep_date,
        "returnDate": ret_date,
        "adults": CONFIG["adults"],
        "currencyCode": CONFIG["currency"],
        "max": 50,
        "maxNumberOfStops": CONFIG["max_stops"],
    }
    if CONFIG["children"]:
        params["children"] = len(CONFIG["children"])
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=CONFIG["timeout_seconds"])
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {resp.status_code}", "detail": resp.text}
    except Exception as e:
        return {"error": "Exception", "detail": str(e)}

# -------- Main --------
def main():
    if not (AMADEUS_API_KEY and AMADEUS_API_SECRET and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("❌ Missing env vars")
        return

    token = get_access_token()
    results_summary = []
    all_offers = []

    for origin in CONFIG["origins"]:
        for dest in CONFIG["destinations"]:
            for dep_date in CONFIG["outbound_dates"]:
                for ret_date in CONFIG["return_dates"]:
                    res = search_flights(token, origin, dest, dep_date, ret_date)
                    if "error" in res:
                        results_summary.append(f"{origin}→{dest} {dep_date}/{ret_date}: ❌ {res['error']} {res['detail']}")
                    else:
                        offers = res.get("data", [])
                        if offers:
                            offers_sorted = sorted(offers, key=lambda x: float(x["price"]["total"]))
                            all_offers.extend(offers_sorted[:3])  # keep top 3 per query
                            results_summary.append(f"{origin}→{dest} {dep_date}/{ret_date}: {len(offers)} offers ✅")
                        else:
                            results_summary.append(f"{origin}→{dest} {dep_date}/{ret_date}: 0 offers")

    # Compile Telegram message
    msg = "✅ Workflow finished.\n\n"
    if all_offers:
        msg += "📊 Best offers found:\n"
        top3 = sorted(all_offers, key=lambda x: float(x["price"]["total"]))[:3]
        for i, offer in enumerate(top3, 1):
            price = offer["price"]["total"]
            itinerary = " → ".join([seg["departure"]["iataCode"] for seg in offer["itineraries"][0]["segments"]])
            itinerary += " → " + offer["itineraries"][0]["segments"][-1]["arrival"]["iataCode"]
            msg += f"  {i}. {itinerary} | €{price}\n"
    else:
        msg += "❌ No offers found.\n"

    msg += "\n🧪 Search summary:\n" + "\n".join(results_summary[:10])  # limit to 10 lines
    telegram_message(msg)
    print(msg)

if __name__ == "__main__":
    main()
