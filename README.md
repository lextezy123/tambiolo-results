# tambiolo-results

Nightly PH lotto results (6/42, 6/45, 6/49, 6/55, 6/58) for the Lotto Tambiolo app.

The app reads:
`https://raw.githubusercontent.com/lextezy123/tambiolo-results/main/data/results.json`

## Setup (once)
1. Create a **public** repo named `tambiolo-results` on GitHub and upload everything in this folder.
2. Go to **Actions** → enable workflows if asked.
3. Open **Fetch lotto results** → **Run workflow** → set days to `365` → Run. This fills a year of history.

After that it runs by itself every night at about 9:47 PM and 11:37 PM PH time.

## If something breaks
- If no new draw has been saved for 4+ days, the run fails and GitHub emails you. Usually that means the source page changed and `scripts/fetch_results.py` needs a small fix.
- To add or fix a draw by hand, edit `data/manual.json`:
  ```json
  { "draws": [ { "game": "6/55", "date": "2026-10-28", "numbers": [1, 2, 3, 4, 5, 6], "jackpot": 29700000 } ] }
  ```
  Manual entries always override scraped ones.

## Source
GMA News daily result pages (their robots.txt allows them). PCSO's own results page blocks automated access.
The script requests at most a few pages per run, 2 seconds apart.
