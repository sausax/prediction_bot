# Project Plan: Polymarket Minute-by-Minute Sports Odds Downloader

## Goal
Download historical minute-level price (odds/implied probability) data for Polymarket
sports markets, plus the minute-to-minute change in odds, saved as CSV.

## What I verified (APIs are public, no key needed)
- **Gamma API** `https://gamma-api.polymarket.com/events` — lists events/markets.
  Filter sports with `tag_slug` (e.g. `nba`, `nfl`) or `tag_id` (`100639` = game-level
  sports markets, as opposed to futures like "Who wins the 2027 title?"). Each market
  gives `clobTokenIds` (one token per outcome) and `outcomes`.
- **CLOB API** `https://clob.polymarket.com/prices-history?market=<token_id>&startTs=..&endTs=..&fidelity=1`
  — returns `[{t, p}]` at roughly 1 point per minute. Tested: works for closed markets
  when queried in date chunks (`interval=max` gives coarser data, so use chunks).

## Approach (single simple script)
`download_polymarket.py` (requests + pandas) and `app.py` web viewer (streamlit + plotly), in a `.venv`.

1. Get closed sports events from Gamma (filter by tag, date range, `--limit`).
2. For each market, for each outcome token: fetch price history in 1-day chunks with `fidelity=1`.
3. Resample to an exact 1-minute grid (forward-fill minutes with no trades).
4. Add columns: `price` (implied prob), `change` (vs previous minute), `pct_change`.
5. Write one CSV: `data/polymarket_sports_minutes.csv` with columns:
   `event, market, outcome, token_id, timestamp_utc, price, change, pct_change`

Example usage:
```
python download_polymarket.py --tag nba --days 30 --limit 50
```

## Todo
- [x] Create `requirements.txt` + `.venv` (Python 3.13 via uv) + `.gitignore`
- [x] Write `download_polymarket.py` (fetch events → fetch history → resample → CSV)
- [x] Polite rate limiting + simple retry
- [x] Test run on a small sample (4 recent NBA games) and check the output
- [x] Add Streamlit web app `app.py` for viewing the data (added on request)
- [x] Add usage notes to README.md
- [x] Add review section to this file

## Review
**Changes**
- `download_polymarket.py`: gets closed game events from the Gamma API (filtered by league tag plus
  the "games" tag, moneyline markets only by default), downloads each outcome's price history from
  the CLOB `prices-history` endpoint one day at a time at `fidelity=1`, puts it on a 1-minute grid
  with pandas (carrying the last price forward), adds `change`/`pct_change`, and writes one CSV.
- `app.py`: Streamlit app to pick a game and market, a time-window slider (defaults to the last 12h),
  summary metrics, a price line chart, a per-minute change bar chart, biggest-moves table, raw data download.
- `requirements.txt`, `.gitignore` (ignores `.venv/` and `data/`), README usage notes.

**Things found along the way**
- The Gamma API returns HTTP 406 for `limit` > 50, so the script fetches 50 events per page.
- Many "events" are side markets (e.g. "Exact Margin"), so `--limit` counts only events with a moneyline market.
- Token IDs are 77-digit numbers, so the app reads them as strings.
- Python 3.15 is too new for package wheels, so the venv uses 3.13.
- Markets open about 2 weeks before the game, so each outcome has about 21k minute rows and most early
  minutes are flat. Test run: 4 games took about 20 seconds and produced 171k rows.
