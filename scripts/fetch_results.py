"""Fetch PH lotto results (6/42, 6/45, 6/49, 6/55, 6/58) and merge them into data/results.json.

Source: GMA News daily lotto result pages (/news/lotto/results-<month>-<dd>-<yyyy>/),
which their robots.txt allows. PCSO's own results page disallows automated access.

Usage:
  python scripts/fetch_results.py              # check the last 3 days
  python scripts/fetch_results.py --days 365   # backfill a year (run once)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "results.json"
MANUAL_FILE = ROOT / "data" / "manual.json"

PH_TZ = timezone(timedelta(hours=8))
URL = "https://www.gmanetwork.com/news/lotto/results-{month}-{day:02d}-{year}/"
HEADERS = {"User-Agent": "TambioloResultsBot/1.0 (+https://github.com/lextezy123)"}
DELAY_SECONDS = 2.0          # pause between page requests, to stay polite
STALE_AFTER_DAYS = 4         # fail the run (and email you) if nothing newer than this

GAMES = {42, 45, 49, 55, 58}
HEADING = re.compile(r"^(ultra\s*lotto|grand\s*lotto|super\s*lotto|mega\s*lotto|lotto)\s*6/(\d{2})\s*:?$", re.I)
NUMBERS = re.compile(r"^\d{1,2}(?:\s+\d{1,2}){5}$")
PRIZE = re.compile(r"^P\s?([\d,]+(?:\.\d+)?)$", re.I)


def parse_page(html: str, draw_date: date) -> list[dict]:
    """Pull the 6-number game results out of one daily results page."""
    lines = [ln.strip() for ln in BeautifulSoup(html, "html.parser").get_text("\n").split("\n")]
    lines = [ln for ln in lines if ln]
    found: dict[str, dict] = {}
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m or int(m.group(2)) not in GAMES:
            continue
        game = f"6/{m.group(2)}"
        nums, jackpot = None, None
        for nxt in lines[i + 1:i + 4]:
            if nums is None and NUMBERS.match(nxt):
                nums = [int(x) for x in nxt.split()]
            elif nums is not None and (p := PRIZE.match(nxt)):
                jackpot = float(p.group(1).replace(",", ""))
                break
        if nums and len(set(nums)) == 6 and all(1 <= n <= int(m.group(2)) for n in nums):
            found[game] = {"game": game, "date": draw_date.isoformat(), "numbers": nums, "jackpot": jackpot}
    return list(found.values())


def fetch_day(session: requests.Session, d: date) -> list[dict]:
    url = URL.format(month=d.strftime("%B").lower(), day=d.day, year=d.year)
    resp = session.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return parse_page(resp.text, d)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("draws", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="how many days back to check")
    args = ap.parse_args()

    by_key = {(d["game"], d["date"]): d for d in load(DATA_FILE)}
    today = datetime.now(PH_TZ).date()

    session = requests.Session()
    for back in range(args.days):
        d = today - timedelta(days=back)
        try:
            draws = fetch_day(session, d)
        except requests.RequestException as e:
            print(f"{d}: request failed: {e}", file=sys.stderr)
            continue
        for dr in draws:
            by_key[(dr["game"], dr["date"])] = dr
        print(f"{d}: {', '.join(x['game'] for x in draws) or 'no 6-number draws'}")
        time.sleep(DELAY_SECONDS)

    # manual.json lets you add or correct a draw by hand on GitHub; it always wins.
    for dr in load(MANUAL_FILE):
        by_key[(dr["game"], dr["date"])] = dr

    draws = sorted(by_key.values(), key=lambda x: (x["date"], x["game"]), reverse=True)
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "draws": draws}
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    old = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    if old.get("draws") != draws:
        DATA_FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved {len(draws)} draws.")
    else:
        print("No changes.")

    newest = max((date.fromisoformat(x["date"]) for x in draws), default=None)
    if newest is None or (today - newest).days > STALE_AFTER_DAYS:
        print(f"ERROR: newest draw is {newest}; the source page may have changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
