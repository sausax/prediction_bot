"""Paper trading (fake money) on Polymarket prices, stored in SQLite.

Mechanics match Polymarket: buy shares at the current price; each share pays $1 if
that outcome wins and $0 if it loses.
"""
import json
import os
import sqlite3

import pandas as pd

from download_polymarket import get_json

DB = os.environ.get("PAPER_DB", "data/paper_trading.db")  # override for testing
START_BALANCE = 1000.0
STOP_LOSS = 0.70  # auto-sell an open bet when its value drops below 70% of the amount paid
MARKETS = "https://gamma-api.polymarket.com/markets"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    placed_at   TEXT NOT NULL,
    event_title TEXT NOT NULL,
    league      TEXT,
    outcome     TEXT NOT NULL,
    token_id    TEXT NOT NULL,
    price       REAL NOT NULL,   -- price paid per share (0-1)
    amount      REAL NOT NULL,   -- dollars spent
    shares      REAL NOT NULL,   -- amount / price
    status      TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | cashed_out | stop_loss
    exit_price  REAL,            -- final price (1/0) or cash-out price
    payout      REAL,            -- dollars received when closed
    closed_at   TEXT
);
"""


def now():
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def bets(status=None):
    with connect() as con:
        q = "SELECT * FROM bets" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC"
        return pd.read_sql_query(q, con, params=(status,) if status else ())


def cash():
    """Starting balance - money spent on bets + money received from closed bets."""
    with connect() as con:
        spent, received = con.execute(
            "SELECT COALESCE(SUM(amount), 0), COALESCE(SUM(payout), 0) FROM bets").fetchone()
    return START_BALANCE - spent + received


def bet_tokens():
    """Token ids of every bet ever placed (open or closed)."""
    with connect() as con:
        return {r[0] for r in con.execute("SELECT DISTINCT token_id FROM bets")}


def place_bet(event_title, league, outcome, token_id, price, amount, match_tokens=()):
    """match_tokens: all outcome token ids of this match; only one bet per match is allowed."""
    if bet_tokens() & {str(t) for t in (*match_tokens, token_id)}:
        raise ValueError("You already have a bet on this match")
    if not 0 < price < 1:
        raise ValueError("Price must be between 0 and 1")
    if amount <= 0 or amount > cash() + 1e-9:
        raise ValueError("Amount must be positive and no more than your cash balance")
    with connect() as con:
        con.execute("INSERT INTO bets (placed_at, event_title, league, outcome, token_id, price, amount, shares)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (now(), event_title, league, outcome, str(token_id), price, amount, amount / price))


def cash_out(bet_id, price, status="cashed_out"):
    """Sell an open position at the current price."""
    with connect() as con:
        con.execute("UPDATE bets SET status=?, exit_price=?, payout=shares*?, closed_at=?"
                    " WHERE id=? AND status='open'", (status, price, price, now(), bet_id))


def apply_stop_loss(prices):
    """Sell open bets whose value (shares x current price) is below STOP_LOSS x amount paid.
    Same as: current price < STOP_LOSS x buy price. Returns the bets that were sold."""
    sold = []
    for b in bets("open").itertuples():
        price, over = prices.get(b.token_id, (None, False))
        if price is None or over or price >= STOP_LOSS * b.price:
            continue  # no price, game already over (settlement handles it), or above the stop
        cash_out(b.id, price, status="stop_loss")
        sold.append({"event": b.event_title, "outcome": b.outcome, "profit": b.shares * price - b.amount})
    return sold


def reset():
    with connect() as con:
        con.execute("DELETE FROM bets")


def market_prices(token_ids):
    """{token_id: (price, game_over)} for each token, from Gamma (open and closed markets need separate calls).
    game_over is True as soon as the game has ended (event `ended`, or a result has been proposed),
    not only once Polymarket formally closes the market, which can take hours."""
    out = {}
    ids = list({str(t) for t in token_ids})
    for i in range(0, len(ids), 20):  # keep URLs a reasonable length
        chunk = ids[i:i + 20]
        for closed in ("false", "true"):
            for m in get_json(MARKETS, {"clob_token_ids": chunk, "closed": closed}):
                tokens = json.loads(m.get("clobTokenIds") or "[]")
                prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
                over = (bool(m.get("closed"))
                        or any(e.get("ended") for e in m.get("events", []))
                        or m.get("umaResolutionStatus") in ("proposed", "resolved"))
                for t, p in zip(tokens, prices):
                    out[t] = (p, over)
    return out


def settle_open_bets(prices=None):
    """Settle open bets whose game is over with a decisive price (≥99¢ won / ≤1¢ lost). Returns the settled bets.
    Runs on every app start, so bets that finished while the app/PC was off get settled too."""
    open_bets = bets("open")
    if open_bets.empty:
        return []
    prices = prices or market_prices(open_bets["token_id"])
    settled = []
    with connect() as con:
        for b in open_bets.itertuples():
            price, over = prices.get(b.token_id, (None, False))
            if not over or price is None or 0.01 < price < 0.99:
                continue  # still playing, or over but no clear winner yet (e.g. cancelled)
            won = price >= 0.99
            payout = b.shares if won else 0.0
            con.execute("UPDATE bets SET status=?, exit_price=?, payout=?, closed_at=? WHERE id=?",
                        ("won" if won else "lost", 1.0 if won else 0.0, payout, now(), b.id))
            settled.append({"event": b.event_title, "outcome": b.outcome, "won": won,
                            "profit": payout - b.amount})
    return settled
