# tambiolo-results

PH lotto results for the Lotto Tambiolo app, refreshed automatically several times a day.

| File | What | History |
|---|---|---|
| `data/results.json` | 6/42, 6/45, 6/49, 6/55, 6/58 | everything fetched so far |
| `data/digits.json` | 2D (EZ2), 3D (Swertres), 4D, 6D | last 120 days |

The app reads them from
`https://raw.githubusercontent.com/lextezy123/tambiolo-results/main/data/`.

## How it runs
`.github/workflows/fetch.yml` runs the script 7 times a day (after each draw time, plus
late-night and morning runs, because results are often posted hours after the draw).
Each run checks the last 3 days, so a missed run is caught by the next one.

To load older history (for the app's "All" stats): **Actions → Fetch lotto results →
Run workflow**, set days to `1500`, and run. It takes about an hour.

## If something breaks
GitHub emails you when a run fails. A run fails when:
- the parser check fails (`tests/test_parse.py`),
- no new 6-number draw has been saved for 4+ days (the source page probably changed), or
- several results land on nights a game doesn't draw (the draw schedule probably changed;
  update `DRAW_DAYS` in `scripts/fetch_results.py` and in the app).

To add or fix a draw by hand, edit `data/manual.json`. Manual entries always win:
```json
{ "draws": [
  { "game": "6/55", "date": "2026-10-28", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 29700000 },
  { "game": "3D", "date": "2026-10-28", "time": "9PM", "numbers": [4, 1, 5] }
] }
```

## Source
GMA News daily result pages (their robots.txt allows them). PCSO's own results page blocks
automated access. The script requests a few pages per run, 2 seconds apart.
