import os
import json
import requests
import re

# ---------------- Config ----------------
DEFAULT_CONFIG = {
    "origins": ["AMS", "BRU", "DUS"],
    "destinations": ["HKT", "KBV", "USM"],  # Phuket, Krabi, Koh Samui
    "outbound_dates": ["2025-04-17", "2025-04-18", "2025-04-19"],
    "return_dates":   ["2025-05-03", "2025-05-04", "2025-05-05"],
    "max_total_duration_hours": 20,   # per direction (outbound AND return)
    "max_stops": 1,                   # per direction
    "currency": "EUR",
    "adults": 1,                      # simplify while debugging
    "children": [],                   # add later via POST body if needed
    "timeout_seconds": 30,            # network timeout (doesn't change results)
    "results_limit": 3                # top N cheapest to send
}

def load_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f) or {}
        merged = DEFAULT_CONFIG.copy()
        merged.update(user_cfg)
        return merged
    return DEFAULT_CONFIG

CONFIG = load_config()

# ---------------- Env ----------------
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AMADEUS_HOST = os.getenv("AMADEUS_HOST", "https://api.amadeus.com")

if not all([AMADEUS_API_KEY, AMADEUS_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    raise SystemExit("❌ ERROR: Missing required environment variables.")

# ---------------- Utils ----------------
def telegram_send(msg: str):
    """Send a single Telegram message."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=15)
    except Exception as e:
        print(f"⚠️ Telegram send failed: {e}")

def get_access_token():
    url = f"{AMADEUS_HOST}/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    r = requests.post(url, data=data, timeout=CONFIG["timeout_seconds"])
    r.raise_for_status()
    return r.json()["access_token"]

ISO_DUR_RE = re.compile(r"^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?$")
def iso_duration_to_hours(iso: str) -> float:
    """
    Convert ISO-8601 duration like 'PT17H30M' to hours (float).
    Handles optional days/hours/minutes.
    """
    m = ISO_DUR_RE.match(iso)
    if not m:
        return 9999.0
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    mins = int(m.group(3) or 0)
    return days * 24 + hours + mins / 60.0

def stops_in_itinerary(itinerary: dict) -> int:
    """Number of layovers = segments - 1"""
    segs = itinerary.get("segments", [])
    return max(0, len(segs) - 1)

# ---------------- API call ----------------
def search_flights(token, origin, dest, dep, ret):
    """
    Use GET Flight Offers Search.
    Note: Amadeus does NOT support 'max 1 stop' as a query param. We fetch and filter locally.
    """
    url = f"{AMADEUS_HOST}/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep,
        "returnDate": ret,
        "adults": CONFIG["adults"],
        "currencyCode": CONFIG["currency"],
        "max": 50,  # how many offers to return
        # Do NOT include 'maxNumberOfStops' (not supported) -> filter locally
    }
    r = requests.get(url, headers=headers, params=params, timeout=CONFIG["timeout_seconds"])
    status = r.status_code
    if status != 200:
        # Return structured error so we can report it later
        try:
            err = r.json()
        except Exception:
            err = {"error": r.text[:300]}
        return [], {"status": status, "error": err}
    data = r.json().get("data", [])
    return data, {"status": status, "error": None}

# ---------------- Main ----------------
def main():
    # Acquire token
    try:
        token = get_access_token()
    except Exception as e:
        telegram_send(f"❌ Failed to get Amadeus token: {e}")
        return

    all_raw = 0
    kept = []
    # counters to explain *why* offers were dropped
    dropped_by_stops = 0
    dropped_by_duration = 0

    debug_rows = []          # per-combo summary lines
    status_buckets = {}      # {status_code: count}
    error_samples = {}       # {status_code: sample_error_text}

    for origin in CONFIG["origins"]:
        for dest in CONFIG["destinations"]:
            for dep in CONFIG["outbound_dates"]:
                for ret in CONFIG["return_dates"]:
                    offers, meta = search_flights(token, origin, dest, dep, ret)
                    status_buckets[meta["status"]] = status_buckets.get(meta["status"], 0) + 1
                    if meta["error"] and meta["status"] != 200:
                        # Keep a short sample
                        if meta["status"] not in error_samples:
                            error_samples[meta["status"]] = str(meta["error"])[:300]

                    raw_count = len(offers)
                    all_raw += raw_count

                    # Client-side filtering (≤1 stop per direction, ≤20h per direction)
                    for o in offers:
                        itins = o.get("itineraries", [])
                        if len(itins) < 2:
                            # round-trips should have 2 itineraries; if not, keep but mark as suspicious
                            pass

                        # per-direction checks
                        too_many_stops = False
                        too_long = False
                        for it in itins:
                            if stops_in_itinerary(it) > CONFIG["max_stops"]:
                                too_many_stops = True
                                break
                            if iso_duration_to_hours(it.get("duration", "PT0H")) > CONFIG["max_total_duration_hours"]:
                                too_long = True
                                break

                        if too_many_stops:
                            dropped_by_stops += 1
                            continue
                        if too_long:
                            dropped_by_duration += 1
                            continue

                        # if passed, collect minimal info for later sorting
                        kept.append({
                            "origin": origin,
                            "dest": dest,
                            "dep": dep,
                            "ret": ret,
                            "price": float(o["price"]["total"]),
                            "carrier": o["itineraries"][0]["segments"][0]["carrierCode"],
                            "duration_out": itins[0]["duration"] if itins else "",
                            "duration_back": itins[1]["duration"] if len(itins) > 1 else ""
                        })

                    debug_rows.append(f"{origin}→{dest} {dep}/{ret}: {raw_count} offers (HTTP {meta['status']})")

    # Build result message (compact)
    lines = []
    lines.append("✅ Workflow finished.\n")

    # Status overview
    lines.append("📊 API status summary:")
    for code in sorted(status_buckets.keys()):
        lines.append(f"  • HTTP {code}: {status_buckets[code]} searches")
    if error_samples:
        lines.append("🧪 Sample errors:")
        for code, err in error_samples.items():
            lines.append(f"  • HTTP {code} sample: {err}")

    # Per-combo summary (first 20 lines to avoid spam)
    lines.append("\n🔎 Per-search offer counts (first 20):")
    for row in debug_rows[:20]:
        lines.append(f"  • {row}")
    hidden = max(0, len(debug_rows) - 20)
    if hidden:
        lines.append(f"  … plus {hidden} more combinations.")

    # Filtering explanation
    lines.append("\n🧹 Filter impact (client-side):")
    lines.append(f"  • Raw offers fetched: {all_raw}")
    lines.append(f"  • Dropped (stops > {CONFIG['max_stops']} per direction): {dropped_by_stops}")
    lines.append(f"  • Dropped (duration > {CONFIG['max_total_duration_hours']}h per direction): {dropped_by_duration}")
    lines.append(f"  • Kept after filters: {len(kept)}")

    # Top N cheapest overall (no price threshold)
    if kept:
        kept.sort(key=lambda x: x["price"])
        topn = kept[:CONFIG.get("results_limit", 3)]
        lines.append("\n💸 Top cheapest flights:")
        for i, f in enumerate(topn, 1):
            lines.append(
                f"  {i}. {f['origin']}→{f['dest']} ({f['dep']} / {f['ret']}) "
                f"{f['carrier']}  out:{f['duration_out']} back:{f['duration_back']}  €{f['price']:.2f}"
            )
    else:
        lines.append("\n❌ No flights survived filters (or API returned none).")

    telegram_send("\n".join(lines))

if __name__ == "__main__":
    main()
