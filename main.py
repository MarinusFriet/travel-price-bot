import os
import json
import time
import requests

# -------- Config --------
DEFAULT_CONFIG = {
    "origins": ["AMS", "BRU", "DUS"],
    "destination": "KBV",
    "outbound_dates": ["2025-04-17", "2025-04-18", "2025-04-19"],
    "return_dates": ["2025-05-03", "2025-05-04", "2025-05-05"],
    "prefer_after_18_from_AMS": True,
    "max_total_duration_hours": 20,
    "max_stops": 1,
    "currency": "EUR",
    "price_threshold_eur": None,
    "adults": 2,
    "children": [{"id": "2", "age": 3}, {"id": "3", "age": 5}],
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

# -------- Environment variables --------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST")

# -------- Debug: check env vars --------
missing_vars = []
if not AMADEUS_API_KEY: missing_vars.append("AMADEUS_API_KEY")
if not AMADEUS_API_SECRET: missing_vars.append("AMADEUS_API_SECRET")
if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_CHAT_ID: missing_vars.append("TELEGRAM_CHAT_ID")
if not AMADEUS_HOST: missing_vars.append("AMADEUS_HOST")

if missing_vars:
    print("❌ ERROR: Missing required environment variables:")
    for var in missing_vars:
        print(f"   - {var}")
    raise SystemExit("Fix your GitHub Secrets and re-run the workflow.")

print("✅ All required environment variables are present.")


def iso8601_duration_to_hours(dur):
    hours = 0
    num = ''
    for c in dur:
        if c.isdigit():
            num += c
        elif c == 'H':
            hours += int(num or 0); num = ''
        elif c == 'M':
            hours += (int(num or 0))/60.0; num = ''
        elif c == 'S':
            hours += (int(num or 0))/3600.0; num = ''
    return hours

def get_amadeus_token():
    host = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")
    url = f"{host}/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    r = requests.post(url, data=data, timeout=CONFIG["timeout_seconds"])
    r.raise_for_status()
    return r.json()["access_token"]

def search_flights(token, origin, dest, depart_date, return_date):
    host = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")
    url = f"{host}/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": depart_date,
        "returnDate": return_date,
        "adults": CONFIG["adults"],
        "children": len(CONFIG["children"]),
        "currencyCode": CONFIG["currency"],
        "max": 50,
        "maxNumberOfStops": CONFIG["max_stops"],
    }
    r = requests.get(url, headers=headers, params=params, timeout=CONFIG["timeout_seconds"])
    r.raise_for_status()
    return r.json()

def prefers_after_18(origin, offers):
    if origin != "AMS" or not CONFIG.get("prefer_after_18_from_AMS"):
        return offers
    filtered = []
    for offer in offers:
        try:
            seg0 = offer["itineraries"][0]["segments"][0]
            dep_time = seg0["departure"]["at"]
            hour = int(dep_time.split("T")[1][:2])
            if hour >= 18:
                filtered.append(offer)
        except Exception:
            continue
    return filtered or offers

def filter_offers(offers_raw):
    data = offers_raw.get("data", [])
    filtered = []
    for off in data:
        try:
            it0, it1 = off["itineraries"]
            def hours(itin):
                return iso8601_duration_to_hours(itin["duration"])
            if hours(it0) > CONFIG["max_total_duration_hours"] or hours(it1) > CONFIG["max_total_duration_hours"]:
                continue
            def stops(itin): return max(0, len(itin.get("segments", [])) - 1)
            if stops(it0) > CONFIG["max_stops"] or stops(it1) > CONFIG["max_stops"]:
                continue
            filtered.append(off)
        except Exception:
            continue
    return filtered

def choose_cheapest(offers):
    if not offers: return None
    return sorted(offers, key=lambda o: float(o["price"]["grandTotal"]))[0]

def send_telegram(msg):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        print("Telegram not configured; message would be:\\n", msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=CONFIG["timeout_seconds"])
    r.raise_for_status()

def format_offer(origin, dest, d_out, d_ret, offer):
    price = offer["price"]["grandTotal"]; cur = offer["price"]["currency"]
    it0, it1 = offer["itineraries"]
    def legs(it):
        parts = []
        for s in it["segments"]:
            parts.append(f'{s["departure"]["iataCode"]} {s["departure"]["at"][11:16]} → {s["arrival"]["iataCode"]} {s["arrival"]["at"][11:16]} ({s["carrierCode"]}{s.get("number","")})')
        return " | ".join(parts)
    carriers = sorted({s["carrierCode"] for s in it0["segments"] + it1["segments"]})
    txt = (
        f"✈️ <b>{origin} → {dest}</b> ({d_out})  •  <b>Return:</b> {d_ret}\\n"
        f"Carriers: {', '.join(carriers)}\\n"
        f"Outbound: {it0['duration'].replace('PT','')}, stops: {max(0,len(it0['segments'])-1)}\\n"
        f"Return: {it1['duration'].replace('PT','')}, stops: {max(0,len(it1['segments'])-1)}\\n"
        f"Price for 2 adults + 2 children: <b>{price} {cur}</b>\\n"
        f"Legs:\\n• {legs(it0)}\\n• {legs(it1)}"
    )
    return txt

def main():
    if not (AMADEUS_API_KEY and AMADEUS_API_SECRET):
        raise SystemExit("Missing AMADEUS_API_KEY/SECRET env vars.")
    token = get_amadeus_token()
    any_found = False
    for origin in CONFIG["origins"]:
        for d_out in CONFIG["outbound_dates"]:
            for d_ret in CONFIG["return_dates"]:
                try:
                    raw = search_flights(token, origin, CONFIG["destination"], d_out, d_ret)
                    filtered = filter_offers(raw)
                    filtered = prefers_after_18(origin, filtered)
                    best = choose_cheapest(filtered)
                    if best:
                        price = float(best["price"]["grandTotal"])
                        if CONFIG["price_threshold_eur"] is None or price <= CONFIG["price_threshold_eur"]:
                            msg = format_offer(origin, CONFIG["destination"], d_out, d_ret, best)
                            send_telegram(msg)
                            any_found = True
                        time.sleep(0.2)
                except requests.HTTPError as e:
                    print(f"HTTP error on {origin} {d_out}/{d_ret}: {e}")
                except Exception as e:
                    print(f"Error on {origin} {d_out}/{d_ret}: {e}")
    if not any_found:
        print("No qualifying offers found (or all above threshold).")

if __name__ == "__main__":
    main()
