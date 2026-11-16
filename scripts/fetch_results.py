"""Fetch PH lotto results and merge them into the data files the Lotto Tambiolo app reads.

  data/results.json   6-number games: 6/42, 6/45, 6/49, 6/55, 6/58 (full history)
  data/digits.json    digit games: 2D (EZ2), 3D (Swertres), 4D, 6D (last 120 days)

Source: GMA News daily lotto result pages (/news/lotto/results-<month>-<dd>-<yyyy>/),
which their robots.txt allows. PCSO's own results page disallows automated access.

Usage:
  python scripts/fetch_results.py               # check the last 3 days
  python scripts/fetch_results.py --days 1500   # backfill about 4 years (run once)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "results.json"
DIGITS_FILE = ROOT / "data" / "digits.json"
MANUAL_FILE = ROOT / "data" / "manual.json"

PH_TZ = timezone(timedelta(hours=8))
URL = "https://www.gmanetwork.com/news/lotto/results-{month}-{day:02d}-{year}/"
HEADERS = {"User-Agent": "TambioloResultsBot/1.0 (+https://github.com/lextezy123)"}
DELAY_SECONDS = 2.0          # pause between page requests, to stay polite
STALE_AFTER_DAYS = 4         # fail the run (and email you) if nothing newer than this
DIGITS_KEEP_DAYS = 120       # digit games draw up to 3 times a day; keep the file small
SCHEDULE_CHECK_DAYS = 30     # only recent draws are checked against the draw schedule

# ---- 6-number games ----
GAMES = {42, 45, 49, 55, 58}
# Draw days per game (Monday = 0). Every game draws three nights a week at 9 PM.
DRAW_DAYS = {
    58: {1, 4, 6},   # Tue Fri Sun
    55: {0, 2, 5},   # Mon Wed Sat
    49: {1, 3, 6},   # Tue Thu Sun
    45: {0, 2, 4},   # Mon Wed Fri
    42: {1, 3, 5},   # Tue Thu Sat
}
HEADING = re.compile(r"^(ultra\s*lotto|grand\s*lotto|super\s*lotto|mega\s*lotto|lotto)\s*6/(\d{2})\s*:?$", re.I)
NUMBERS = re.compile(r"^\d{1,2}(?:\s+\d{1,2}){5}$")
PRIZE = re.compile(r"^(?:P|PHP|₱)\s?([\d,]+(?:\.\d+)?)$", re.I)

# ---- digit games ----
# Headings look like "Swertres 9PM:", "2D 5PM:", "4D Lotto:", "6D Lotto:". Older pages may say "EZ2" or "4-Digit".
DIGIT_HEADING = re.compile(
    r"^(?:(?P<d2>2d|ez2)|(?P<d3>3d|swertres)|(?P<d4>4d|4[\s-]?digit)|(?P<d6>6d|6[\s-]?digit))"
    r"(?:\s*lotto)?"
    r"(?:\s*(?P<hour>\d{1,2})(?::\d{2})?\s*(?P<ampm>[ap])\.?m\.?)?"
    r"\s*:?$",
    re.I,
)
# game code -> (how many numbers, highest value of each)
DIGIT_SHAPE = {"2D": (2, 31), "3D": (3, 9), "4D": (4, 9), "6D": (6, 9)}
DIGIT_ORDER = {"2D": 0, "3D": 1, "4D": 2, "6D": 3}


def page_lines(html: str) -> list[str]:
    from bs4 import BeautifulSoup

    lines = [ln.strip() for ln in BeautifulSoup(html, "html.parser").get_text("\n").split("\n")]
    return [ln for ln in lines if ln]


def _prize_after(lines: list[str], start: int) -> float | None:
    for nxt in lines[start:start + 2]:
        p = PRIZE.match(nxt)
        if p:
            return float(p.group(1).replace(",", ""))
    return None


def parse_lotto(lines: list[str], draw_date: date) -> list[dict]:
    """Pull the 6-number game results out of one daily results page."""
    found: dict[str, dict] = {}
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m or int(m.group(2)) not in GAMES:
            continue
        top = int(m.group(2))
        game = f"6/{top}"
        # The numbers are on the line right after the heading (or the one after that).
        for j in (i + 1, i + 2):
            if j < len(lines) and NUMBERS.match(lines[j]):
                nums = [int(x) for x in lines[j].split()]
                if len(set(nums)) == 6 and all(1 <= n <= top for n in nums):
                    found[game] = {
                        "game": game,
                        "date": draw_date.isoformat(),
                        "numbers": nums,
                        "jackpot": _prize_after(lines, j + 1),
                    }
                break
    return list(found.values())


def parse_digits(lines: list[str], draw_date: date) -> list[dict]:
    """Pull the digit game results (2D, 3D, 4D, 6D) out of one daily results page."""
    found: dict[tuple[str, str], dict] = {}
    for i, line in enumerate(lines):
        m = DIGIT_HEADING.match(line)
        if not m:
            continue
        game = "2D" if m.group("d2") else "3D" if m.group("d3") else "4D" if m.group("d4") else "6D"
        if m.group("hour"):
            draw_time = f"{int(m.group('hour'))}{m.group('ampm').upper()}M"
        elif game in ("4D", "6D"):
            draw_time = "9PM"        # one draw a night
        else:
            continue                 # a 2D/3D heading with no draw time can't be placed
        count, top = DIGIT_SHAPE[game]
        for j in (i + 1, i + 2):
            if j >= len(lines):
                break
            parts = lines[j].replace("-", " ").split()
            if len(parts) == count and all(p.isdigit() and len(p) <= 2 for p in parts):
                nums = [int(p) for p in parts]
                low = 1 if game == "2D" else 0
                if all(low <= n <= top for n in nums):
                    found[(game, draw_time)] = {
                        "game": game,
                        "date": draw_date.isoformat(),
                        "time": draw_time,
                        "numbers": nums,
                        "prize": _prize_after(lines, j + 1),
                    }
                break
    return list(found.values())


def off_schedule(draw: dict, today: date) -> bool:
    """True for a recent 6-number result dated on a night that game doesn't draw."""
    d = date.fromisoformat(draw["date"])
    if (today - d).days > SCHEDULE_CHECK_DAYS:
        return False                 # schedules were different in past years; don't judge old pages
    top = int(draw["game"].split("/")[1])
    return d.weekday() not in DRAW_DAYS[top]


def fetch_day(session, d: date) -> tuple[list[dict], list[dict]]:
    url = URL.format(month=d.strftime("%B").lower(), day=d.day, year=d.year)
    resp = session.get(url, headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        return [], []
    resp.raise_for_status()
    lines = page_lines(resp.text)
    return parse_lotto(lines, d), parse_digits(lines, d)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("draws", [])


def hour_of(draw_time: str) -> int:
    m = re.match(r"(\d{1,2})\s*([AP])M", draw_time, re.I)
    if not m:
        return 0
    h = int(m.group(1)) % 12
    return h + 12 if m.group(2).upper() == "P" else h


def dump(draws: list[dict]) -> str:
    """One draw per line: small to download, and easy to read or fix by hand on GitHub."""
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = ",\n".join("  " + json.dumps(d, ensure_ascii=False, separators=(", ", ": ")) for d in draws)
    return '{\n "updated": "%s",\n "draws": [\n%s\n ]\n}\n' % (updated, rows)


def save_if_changed(path: Path, draws: list[dict]) -> bool:
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if old.get("draws") == draws:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(draws), encoding="utf-8")
    return True


def main() -> int:
    import requests

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="how many days back to check")
    args = ap.parse_args()

    lotto = {(d["game"], d["date"]): d for d in load(DATA_FILE)}
    digits = {(d["game"], d["date"], d.get("time", "9PM")): d for d in load(DIGITS_FILE)}
    today = datetime.now(PH_TZ).date()
    skipped = 0

    session = requests.Session()
    for back in range(args.days):
        d = today - timedelta(days=back)
        try:
            day_lotto, day_digits = fetch_day(session, d)
        except requests.RequestException as e:
            print(f"{d}: request failed: {e}", file=sys.stderr)
            continue
        kept = []
        for dr in day_lotto:
            if off_schedule(dr, today):
                skipped += 1
                print(f"WARNING {d}: {dr['game']} does not draw on this day; result skipped", file=sys.stderr)
                continue
            lotto[(dr["game"], dr["date"])] = dr
            kept.append(dr["game"])
        for dr in day_digits:
            digits[(dr["game"], dr["date"], dr["time"])] = dr
        print(f"{d}: {', '.join(kept) or 'no 6-number draws'}; {len(day_digits)} digit draws")
        time.sleep(DELAY_SECONDS)

    # manual.json lets you add or correct a draw by hand on GitHub; it always wins.
    # Entries with a "time" (or a 2D/3D/4D/6D game) are digit draws.
    for dr in load(MANUAL_FILE):
        if dr["game"] in DIGIT_SHAPE:
            digits[(dr["game"], dr["date"], dr.get("time", "9PM"))] = {"time": "9PM", **dr}
        else:
            lotto[(dr["game"], dr["date"])] = dr

    lotto_draws = sorted(lotto.values(), key=lambda x: (x["date"], x["game"]), reverse=True)
    if save_if_changed(DATA_FILE, lotto_draws):
        print(f"Saved {len(lotto_draws)} lotto draws.")
    else:
        print("No lotto changes.")

    cutoff = (today - timedelta(days=DIGITS_KEEP_DAYS)).isoformat()
    digit_draws = [d for d in digits.values() if d["date"] >= cutoff]
    # Newest day first; within a day, 9 PM before 2 PM; then 2D, 3D, 4D, 6D.
    digit_draws.sort(key=lambda x: (x["date"], hour_of(x["time"]), -DIGIT_ORDER[x["game"]]), reverse=True)
    if save_if_changed(DIGITS_FILE, digit_draws):
        print(f"Saved {len(digit_draws)} digit draws.")
    else:
        print("No digit changes.")

    newest = max((date.fromisoformat(x["date"]) for x in lotto_draws), default=None)
    if newest is None or (today - newest).days > STALE_AFTER_DAYS:
        print(f"ERROR: newest draw is {newest}; the source page may have changed.", file=sys.stderr)
        return 1
    if skipped >= 3:
        print("ERROR: several results fell on non-draw days; the draw schedule may have changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
