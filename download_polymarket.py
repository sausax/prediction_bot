"""Download minute-by-minute Polymarket price history for closed sports games.

Usage:
    python download_polymarket.py --tag nba --days 7 --limit 20

Output CSV columns:
    event, market, outcome, token_id, timestamp_utc, price, change, pct_change
"""
import argparse
import json
import os
import time

import pandas as pd
import requests

GAMMA = "https://gamma-api.polymarket.com/events"
CLOB = "https://clob.polymarket.com/prices-history"
GAMES_TAG_ID = 100639  # Polymarket tag for individual games (not season futures)
PAGE_SIZE = 50  # Gamma rejects larger pages (HTTP 406)
DAY = 86400

session = requests.Session()
session.headers["User-Agent"] = "polymarket-history-downloader"


def get_json(url, params, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            print(f"  retrying after error: {e}")
            time.sleep(2 * (attempt + 1))


def fetch_events(tag, days, limit, all_markets=False):
    """Closed game events for a league tag that ended within the last `days` days."""
    since = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events, offset = [], 0
    while len(events) < limit:
        page = get_json(GAMMA, {
            "tag_slug": tag, "tag_id": GAMES_TAG_ID, "closed": "true",
            "end_date_min": since, "order": "endDate", "ascending": "false",
            "limit": PAGE_SIZE, "offset": offset,
        })
        if not page:
            break
        if not all_markets:  # keep only events that have a game-winner market
            page_ok = [e for e in page if any(m.get("sportsMarketType") == "moneyline" for m in e.get("markets", []))]
        events.extend(page if all_markets else page_ok)
        offset += len(page)
    return events[:limit]


def fetch_history(token_id, start_ts, end_ts):
    """Raw price points as a Series indexed by time, fetched in 1-day chunks (needed for minute fidelity)."""
    points = []
    for s in range(start_ts, end_ts, DAY):
        data = get_json(CLOB, {"market": token_id, "startTs": s,
                               "endTs": min(s + DAY, end_ts), "fidelity": 1})
        points.extend(data.get("history", []))
        time.sleep(0.1)  # be polite
    if not points:
        return pd.Series(dtype=float)
    df = pd.DataFrame(points).drop_duplicates("t").sort_values("t")
    return pd.Series(df["p"].values, index=pd.to_datetime(df["t"], unit="s", utc=True))


def to_minutes(prices):
    """Exact 1-minute grid (last price in each minute, forward-filled) plus per-minute change."""
    df = prices.resample("1min").last().ffill().to_frame("price")
    df["change"] = df["price"].diff().round(6)
    df["pct_change"] = (df["price"].pct_change() * 100).round(4)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default="nba", help="league tag slug, e.g. nba, nfl, mlb, nhl, epl")
    ap.add_argument("--days", type=int, default=7, help="games that ended in the last N days")
    ap.add_argument("--limit", type=int, default=20, help="max number of events")
    ap.add_argument("--all-markets", action="store_true",
                    help="include spreads/totals/props, not just the moneyline (game winner)")
    ap.add_argument("--out", default="data/polymarket_sports_minutes.csv")
    args = ap.parse_args()

    events = fetch_events(args.tag, args.days, args.limit, args.all_markets)
    print(f"Found {len(events)} closed {args.tag} game events")

    frames = []
    for ev in events:
        for mk in ev.get("markets", []):
            if not args.all_markets and mk.get("sportsMarketType") != "moneyline":
                continue
            if not mk.get("clobTokenIds") or not mk.get("startDate"):
                continue
            tokens = json.loads(mk["clobTokenIds"])
            outcomes = json.loads(mk.get("outcomes") or "[]")
            start = int(pd.Timestamp(mk["startDate"]).timestamp())
            end_s = mk.get("closedTime") or mk.get("endDate")
            end = int(pd.Timestamp(end_s).timestamp()) + 3600 if end_s else int(time.time())
            print(f"- {mk['question']}")
            for token, outcome in zip(tokens, outcomes):
                prices = fetch_history(token, start, end)
                if prices.empty:
                    print(f"    {outcome}: no data")
                    continue
                df = to_minutes(prices)
                df.insert(0, "event", ev["title"])
                df.insert(1, "market", mk["question"])
                df.insert(2, "outcome", outcome)
                df.insert(3, "token_id", token)
                frames.append(df)
                print(f"    {outcome}: {len(df)} minutes")

    if not frames:
        print("No data found.")
        return
    out = pd.concat(frames).rename_axis("timestamp_utc").reset_index()
    out["timestamp_utc"] = out["timestamp_utc"].dt.strftime("%Y-%m-%d %H:%M")
    out = out[["event", "market", "outcome", "token_id", "timestamp_utc", "price", "change", "pct_change"]]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} rows to {args.out}")


if __name__ == "__main__":
    main()
