# prediction_bot

Download minute-by-minute Polymarket price history for sports games and view it in a web app.

## Setup
```bash
uv venv --python 3.13 .venv          # or: python3.13 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
```

## Download data
```bash
python download_polymarket.py --tag nba --days 7 --limit 20
```
Options: `--tag` (nba, nfl, mlb, nhl, epl, ...), `--days` (games ended in last N days),
`--limit` (max games), `--all-markets` (include spreads/totals, not just game winner),
`--out` (default `data/polymarket_sports_minutes.csv`).

CSV columns: `event, market, outcome, token_id, timestamp_utc, price, change, pct_change`
- `price` = implied probability (0–1), one row per minute (forward-filled when no trades)
- `change` / `pct_change` = move vs the previous minute

## View data
```bash
streamlit run app.py
```
Pick a game, set a time window, and see the price chart, per-minute change chart,
biggest 1-minute moves, and raw data (downloadable).
