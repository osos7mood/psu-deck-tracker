"""
Collects live parking availability for Penn State's five gated decks
and appends one row per deck to data/deck_status.csv.

Run manually:  python collector.py
Runs automatically every 10 minutes via GitHub Actions.
"""
import csv
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://api.mistall.com/v3/frame/5110/"
DECKS = {
    "East": "mParkStyleEastDeckSWARCO",
    "West": "mParkStyleWestDeck",
    "Eisenhower": "mParkStyleEisenhowerDeck",
    "HUB": "mParkStyleHubDeckSWARCO",
    "Nittany": "mParkStyleNittanyDeckSWARCO",
}
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "deck_status.csv")
FIELDS = ["timestamp_utc", "timestamp_local", "deck", "status"]
LOCAL_TZ = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "psu-deck-tracker (student data science project)"}

STATUS_TEXT = re.compile(r"Space availability:\s*([a-zA-Z]+)", re.IGNORECASE)
STATUS_ATTR = re.compile(r'state="(good|fair|poor)\1"', re.IGNORECASE)


def parse_status(html: str) -> str:
    """Return 'good', 'fair', 'poor', or 'unknown' from the deck page HTML."""
    match = STATUS_TEXT.search(html)
    if match:
        return match.group(1).lower()
    # Backup: the visible status icon is the div whose state repeats itself,
    # e.g. state="goodgood" or state="poorpoor".
    match = STATUS_ATTR.search(html)
    if match:
        return match.group(1).lower()
    return "unknown"


def fetch_status(code: str, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            response = requests.get(BASE_URL + code, headers=HEADERS, timeout=15)
            response.raise_for_status()
            return parse_status(response.text)
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(5)
    return "error"


def main() -> None:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    now_local = now_utc.astimezone(LOCAL_TZ)

    rows = []
    for deck, code in DECKS.items():
        status = fetch_status(code)
        rows.append({
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_local": now_local.isoformat(),
            "deck": deck,
            "status": status,
        })
        print(f"{now_local:%Y-%m-%d %H:%M}  {deck:<11} {status}")

    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    is_new_file = not os.path.exists(DATA_FILE)
    with open(DATA_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new_file:
            writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
