import os
import time
import requests
from datetime import datetime, timedelta

# -------- Config --------
CONFIG = {
    "origins": ["AMS"],   # Amsterdam
    "destination": "KBV", # Krabi
    "outbound_dates": ["2026-04-18", "2026-04-19"],
    "return_dates": ["2026-05-04", "2026-05-05"],
    "max_total_duration_hours": 20,
    "max_stops": 1,
    "currency": "EUR",
    "price_threshold_eur": None,  # ignored now
    "adults": 1,
    "children": [],
    "timeout_seconds": 60
}

# -------- Airline lookup --------
AIRLINES = {
    "KL": "KLM",
    "QR": "Qatar Airways",
    "EK": "Emirates",
    "TG": "Thai Airways",
    "SQ": "Singapore Airlines",
    "LH": "Lufthansa",
    "LX": "SWISS",
    "AF": "Air France",
    "EY": "Etihad Airways",
    "TK": "Turkish Airlines",
    # add more as needed
}

def get_airline_name(code):
    return AIRLINES.get(code, code)  # fallback to code if not mapped

# -------- Env Vars --------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")

def log(msg):
    print(msg, flush=True)

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ Telegram not configured.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
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

# -------- Google Flights link generator --------
def build_google_flights_url(origin, destination, depart, ret):
    return f"https://www.google.com/travel/flights?q=Flights+from+{origin}+to+{destination}+on+{depart}+returning+{ret}"

# -------- Helpers --------
def parse_duration(duration_str):
    # Example: "PT11H30M"
    hours, minutes = 0, 0
    if "H" in duration_str:
        hours = int(duration_str.split("T")[1].split("H")[0])
    if "M" in duration_str:
        minutes = int(duration_str.split("H")[-1].replace("M", ""))
    return f"{hours}h {minutes}m"

def format_segment(segment):
    dep_time = datetime.fromisoformat(segment["departure"]["at"]).strftime("%Y-%m-%d %H:%M")
    arr_time = datetime.fromisoformat(segment["arrival"]["at"]).strftime("%Y-%m-%d %H:%M")
    airline = get_airline_name(segment["carrierCode"])
    return f"{segment['departure']['iataCode']} ({airline}) {dep_time} → {segment['arrival']['iataCode']} {arr_time}"

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
                    for o in offers:
                        o["_origin"] = origin
                        o["_depart"] = depart
                        o["_return"] = ret
                    all_offers.extend(offers)

    if not all_offers:
        msg = "✅ Workflow finished.\n❌ No offers found."
        log(msg)
        send_telegram_message(msg)
        return

    # Sort by price
    all_offers.sort(key=lambda o: float(o["price"]["total"]))
    best_offers = all_offers[:5]

    lines = ["✅ Workflow finished.", "📊 Top 5 cheapest flights:\n"]
    for i, o in enumerate(best_offers, 1):
        price = o["price"]["total"]
        depart = o["_depart"]
        ret = o["_return"]
        origin = o["_origin"]
        destination = CONFIG["destination"]

        # Outbound
        itin_out = o["itineraries"][0]
        duration_out = parse_duration(itin_out["duration"])
        segs_out = [format_segment(s) for s in itin_out["segments"]]
        stops_out = len(itin_out["segments"]) - 1

        # Return
        itin_back = o["itineraries"][1]
        duration_back = parse_duration(itin_back["duration"])
        segs_back = [format_segment(s) for s in itin_back["segments"]]
        stops_back = len(itin_back["segments"]) - 1

        link = build_google_flights_url(origin, destination, depart, ret)

        lines.append(
            f"{i}️⃣ 💶 {price} {CONFIG['currency']}\n"
            f"   🛫 Outbound ({duration_out}, {stops_out} stops)\n"
            f"   " + "\n   ".join(segs_out) + "\n"
            f"   🛬 Return ({duration_back}, {stops_back} stops)\n"
            f"   " + "\n   ".join(segs_back) + "\n"
            f"   📅 Outbound: {depart}\n"
            f"   📅 Return: {ret}\n"
            f"   🔗 [View offer]({link})\n"
        )

    msg = "\n".join(lines)
    log(msg)
    send_telegram_message(msg)

if __name__ == "__main__":
    main()
