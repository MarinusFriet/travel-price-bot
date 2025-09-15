import os
import json
import time
import requests

# -------- Config --------
DEFAULT_CONFIG = {
    "origins": ["AMS"],
    "destinations": ["KBV"],
    "outbound_dates": ["2025-04-18", "2025-04-19"],
    "return_dates": ["2025-05-04", "2025-05-05"],
    "max_total_duration_hours": 24,
    "max_stops": 1,
    "currency": "EUR",
    "price_threshold_eur": None,  # ignored now
    "adults": 1,
    "children": [],
    "timeout_seconds": 60,
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


# -------- Helpers --------
def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}")


def get_access_token():
    url = f"{AMADEUS_HOST}/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    r = requests.post(url, headers=headers, data=data, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


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
    }
    if CONFIG["children"]:
        params["children"] = len(CONFIG["children"])

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=CONFIG["timeout_seconds"])
        resp.raise_for_status()
        return resp.json().get("data", [])
    except requests.exceptions.HTTPError:
        return []
    except Exception as e:
        print(f"⚠️ Exception: {e}")
        return []


def parse_duration(duration_str):
    """Convert ISO8601 duration PT19H30M -> hours as float"""
    hours, minutes = 0, 0
    if "H" in duration_str:
        try:
            hours = int(duration_str.split("T")[-1].split("H")[0])
        except:
            pass
    if "M" in duration_str:
        try:
            mins = duration_str.split("H")[-1].replace("M", "")
            minutes = int(mins)
        except:
            pass
    return hours + minutes / 60.0


def filter_offers(offers):
    filtered = []
    for offer in offers:
        valid = True
        for itin in offer.get("itineraries", []):
            # stops check
            if CONFIG.get("max_stops") is not None:
                stops = len(itin.get("segments", [])) - 1
                if stops > CONFIG["max_stops"]:
                    valid = False
                    break
            # duration check
            dur_str = itin.get("duration", "PT0H0M")
            total_hours = parse_duration(dur_str)
            if total_hours > CONFIG.get("max_total_duration_hours", 999):
                valid = False
                break
        if valid:
            filtered.append(offer)
    return filtered


def format_offer(offer):
    price = offer["price"]["grandTotal"]
    itineraries = offer.get("itineraries", [])
    routes = []
    for itin in itineraries:
        segs = itin.get("segments", [])
        route = f"{segs[0]['departure']['iataCode']}→{segs[-1]['arrival']['iataCode']} ({itin['duration']})"
        routes.append(route)
    return f"💶 {price} EUR | " + " | ".join(routes)


# -------- Main --------
def main():
    missing = [v for v in ["AMADEUS_API_KEY", "AMADEUS_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"] if not os.getenv(v)]
    if missing:
        print(f"❌ ERROR: Missing env vars: {', '.join(missing)}")
        return

    try:
        token = get_access_token()
    except Exception as e:
        send_telegram(f"❌ Failed to authenticate with Amadeus: {e}")
        return

    all_offers = []
    for origin in CONFIG["origins"]:
        for destination in CONFIG["destinations"]:
            for dep_date in CONFIG["outbound_dates"]:
                for ret_date in CONFIG["return_dates"]:
                    offers = search_flights(token, origin, destination, dep_date, ret_date)
                    offers = filter_offers(offers)
                    all_offers.extend(offers)
                    time.sleep(0.2)

    if not all_offers:
        send_telegram("✅ Workflow finished.\n\n❌ No offers found.")
        return

    # sort by price
    all_offers.sort(key=lambda x: float(x["price"]["grandTotal"]))
    top3 = all_offers[:3]

    msg = "✅ Workflow finished.\n\n🎯 Top 3 cheapest flights found:\n"
    for idx, offer in enumerate(top3, 1):
        msg += f"\n{idx}. {format_offer(offer)}"

    send_telegram(msg)


if __name__ == "__main__":
    main()
