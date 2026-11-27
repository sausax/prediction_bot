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
- [x] Show price as %, red/blue colors (added on request)
- [x] Add "Live" tab for games in progress (added on request)
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

**Live tab (added later)**
- `app.py` now has two tabs. The Live tab gets in-progress games from Gamma (`live=true` plus the games tag),
  shows a table of score, clock and odds, and a detail view per game using the last 6h of minute data
  from the CLOB API. It reuses `fetch_history`/`to_minutes` from the downloader and refreshes every 60s
  with `st.fragment(run_every=60)`.
- League names come from the event's `sport.name`. Soccer and cricket have three outcomes
  (team A / Draw / team B), and Draw is shown in gray.
- Polymarket sometimes leaves the `live` flag on games that haven't started yet (start time in the
  future), so the app skips those.

---

# Plan 2: Polymarket-style live page + paper trading

## Goal
1. **Live** tab looks like Polymarket's homepage: dark theme, grid of game cards. Each card shows
   the league, live score and clock, and a button per outcome with its price (e.g. `Cowboys 98¢`).
   The whole page refreshes every 60s.
2. Clicking an outcome opens a **bet slip** where you enter an amount of paper money and see
   shares, average price and potential payout, then confirm.
3. New **My Bets** tab: balance, open positions (current value and unrealized P&L), settled bets
   (won/lost, realized P&L), and totals.

## How paper trading works (same as Polymarket's mechanics)
- Starting balance: **$1,000** of paper money, with a "Reset" button.
- Buy at the current price: `shares = amount / price`. Each share pays **$1** if that outcome wins and $0 if not.
  Example: $10 on Cowboys at 40¢ buys 25 shares and pays $25 if they win (+$15 profit).
- Open positions are valued at the live price: `value = shares × current price`.
- **Cash out** button: sell an open position early at the current price.
- **Auto-settle**: when a game's market closes, look it up (verified: Gamma
  `markets?clob_token_ids=..&closed=true` returns final prices of 1/0) and pay out.
- Bets are stored in a **SQLite database** `data/paper_trading.db` (Python's built-in `sqlite3`, no new dependency).
  It keeps the full history of every bet (open, won, lost, cashed out). No real money, no wallet.
- **Catch-up on startup**: when the app starts (e.g. after the PC was off), all open bets are checked against
  Polymarket. Any game that finished meanwhile is settled automatically, with a toast like
  "2 bets settled while you were away: +$15.00".

## Design choices (keeping it simple)
- Stay in **Streamlit**, with custom CSS for the dark Polymarket-like card style, `st.dialog` for the bet
  slip and `st.fragment(run_every=60)` for refresh. No new framework.
- Price = Polymarket's displayed price (midpoint), not the order-book ask. That's simpler but slightly
  optimistic, since real buys cost a bit more.
- My own styling inspired by the layout. No Polymarket logo or branding.
- New file `paper.py` (small: load/save bets, place, cash out, settle) so `app.py` stays readable.

## Todo
- [x] `paper.py`: SQLite schema, `place_bet`, `cash_out`, `settle_open_bets`, cash balance
- [x] Dark theme + card CSS (`.streamlit/config.toml` + small CSS block)
- [x] Live tab: card grid with league filter pills, outcome price buttons, 60s refresh
- [x] Bet slip dialog (amount → shares, payout, profit; blocks bets above balance)
- [x] Per-game chart (📈 Chart on a card opens the price/change charts in a dialog)
- [x] My Bets tab: portfolio/cash/P&L metrics, open positions with Cash out, settled history, reset
- [x] Startup catch-up settlement + toast
- [x] Test with headless AppTest (place bet → appears in My Bets → cash out) + screenshot check
- [x] Update README + review section
- [x] Move bets to History as soon as the game ends (event `ended` / result proposed + decisive price), not only when the market formally closes
- [x] Stop-loss: auto-sell open bets whose value drops below 70% of stake (`paper.STOP_LOSS`), checked every 60s with the My Bets refresh
- [x] One bet per match: card buttons disabled + backend check in `paper.place_bet` (matched by the match's outcome token ids, so existing bets are covered with no DB change)
- [x] Sort live games by odds ratio (favorite price ÷ underdog price, high → low), ratio shown on each card

## Review (Plan 2)
**Changes**
- `paper.py` (new): SQLite `bets` table that keeps the full history (status open/won/lost/cashed_out, price,
  shares, payout). Cash is computed from the table (start − stakes + payouts), so there's no separate
  balance to get out of sync. `settle_open_bets` looks up the markets of open bets on Gamma and settles
  those that closed with a 1/0 result.
- `app.py`: three tabs (Live, My Bets, Historical). Live is a 3-column card grid that refreshes every 60s
  (`st.fragment(run_every=60)`). The bet slip and chart are `st.dialog`s kept in session state so the
  60s refresh doesn't close them. My Bets also refreshes every 60s and settles finished games
  while the app is open. On each new session, a catch-up pass settles bets that finished while the PC was off.
- `.streamlit/config.toml`: dark theme. Card and button styling is plain CSS in `app.py`; no Polymarket branding.

**Tested**
- Unit-tested `paper.py` against a temp DB: bet → cash 900, over-balance bet blocked, catch-up settled
  a bet on an already-finished game as lost, cash out paid shares × price, final cash correct.
- End-to-end AppTest: clicked a live price → slip showed shares/payout → placed a $25 bet → toast and header
  cash $975 → My Bets showed live P&L → Cash out → cash updated. The chart dialog renders.

**Notes / limitations**
- Fills use the displayed midpoint price, not the order book, so they're slightly optimistic.
- Bets settle on the *proposed* result once the game ends. If that result were disputed and changed later (rare), the paper bet would not be corrected.
- A market that closes without a clean 1/0 result (e.g. a cancelled game) stays "open" until it resolves.
- Reset deletes the bet history (it asks for confirmation first).
