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
- **🔴 Live** tab: a grid of cards for games in progress, with league, live score/clock and a price button per
  outcome (e.g. `Cowboys 74¢`) and the odds ratio (favorite ÷ underdog, e.g. 90¢/10¢ = 9.0 : 1). Sort by league or by odds ratio (high → low). Click a price to open a bet slip and place a **paper-money** bet; click
  📈 Chart for minute-by-minute charts. The page refreshes every 60 seconds.
- **💼 My Bets** tab: portfolio, cash, total/open/settled P&L, open positions at live prices with **Cash out**,
  and the full history of settled bets.
- **📊 Historical** tab: pick a downloaded game, set a time window, and see price/change charts, biggest
  1-minute moves and raw data.

## Paper trading
- Start with $1,000 of paper money (Reset in the My Bets tab). Same rules as Polymarket: buy shares at the
  current price, and each share pays $1 if that outcome wins and $0 if not.
- **Stop-loss**: an open bet is sold automatically at the current price if its value drops below 70% of the amount
  paid (i.e. the price falls below 70% of your buy price). Change `STOP_LOSS` in `paper.py` to adjust. Shows as
  `stop_loss` in History.
- One bet per match: after you bet on a match (either side), its price buttons are disabled, even after
  it's cashed out or settled.
- Bets are stored in SQLite at `data/paper_trading.db` (set `PAPER_DB` to use another file).
- Open bets move to History as soon as the game is over (the game is marked ended or a result has been proposed, and
  the price is ≥99¢ or ≤1¢), without waiting hours for Polymarket to formally close the market. This also catches up
  bets whose games finished while the app or PC was off; they settle the next time you open the app.
- Prices are Polymarket's displayed (midpoint) prices, so fills are slightly better than a real order would get.
