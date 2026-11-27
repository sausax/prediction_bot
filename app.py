"""Web app for viewing Polymarket sports odds minute by minute (historical + live).

Run:  streamlit run app.py
"""
import json
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

import paper
from download_polymarket import GAMES_TAG_ID, GAMMA, PAGE_SIZE, fetch_history, get_json, to_minutes

DATA = "data/polymarket_sports_minutes.csv"
COLORS = ["#1f5fd1", "#d62728", "#7f7f7f"]  # blue, red, gray (gray = draw in 3-way markets)
PCT = st.column_config.NumberColumn(format="%.1f%%")

st.set_page_config(page_title="Sports Odds Live", page_icon="🔴", layout="wide")
st.html("""<style>
  .block-container {padding-top: 2rem; max-width: 1400px}
  [class*="st-key-card_"] {background:#18222d; border:1px solid #263241 !important; border-radius:12px;
                           transition:border-color .15s, transform .15s}
  [class*="st-key-card_"]:hover {border-color:#3d5266 !important; transform:translateY(-1px)}
  .pm-head {display:flex; justify-content:space-between; font-size:11px; color:#8b98a5;
            text-transform:uppercase; letter-spacing:.05em}
  .pm-live {color:#ef4444; font-weight:700}
  .pm-live::before {content:"●"; margin-right:4px; animation:pm-blink 1.4s infinite}
  @keyframes pm-blink {50% {opacity:.25}}
  .pm-title {font-weight:600; font-size:15px; line-height:1.3; margin:8px 0 2px; min-height:2.6em}
  .pm-score {font-size:24px; font-weight:700; font-variant-numeric:tabular-nums}
  [class*="st-key-blue_"] button {background:rgba(59,130,246,.15); color:#7fb0ff; border:none; font-weight:600}
  [class*="st-key-blue_"] button:hover {background:#3b82f6; color:#fff}
  [class*="st-key-red_"] button {background:rgba(239,68,68,.15); color:#ff8a8a; border:none; font-weight:600}
  [class*="st-key-red_"] button:hover {background:#ef4444; color:#fff}
  [class*="st-key-gray_"] button {background:rgba(148,163,184,.15); color:#cbd5e1; border:none; font-weight:600}
  [class*="st-key-gray_"] button:hover {background:#64748b; color:#fff}
</style>""")


def color_map(outcomes):
    """Draw is gray; teams alternate blue/red."""
    teams = iter(COLORS[:2] * 2)
    return {o: COLORS[2] if o == "Draw" else next(teams) for o in outcomes}


def charts(view, colors):
    """Win-probability line chart + per-minute change bar chart (prices already in %)."""
    st.subheader("Win probability (%)")
    fig = px.line(view, x="timestamp_utc", y="price", color="outcome", color_discrete_map=colors)
    fig.update_layout(yaxis_range=[0, 100], yaxis_ticksuffix="%", yaxis_title="Price",
                      hovermode="x unified", xaxis_title=None)
    fig.update_traces(hovertemplate="%{y:.1f}%")
    st.plotly_chart(fig, width="stretch")

    st.subheader("Change vs previous minute (percentage points)")
    fig2 = px.bar(view, x="timestamp_utc", y="change", color="outcome", barmode="group",
                  color_discrete_map=colors)
    fig2.update_layout(hovermode="x unified", xaxis_title=None, yaxis_title="Change (pts)")
    fig2.update_traces(hovertemplate="%{y:+.1f} pts")
    st.plotly_chart(fig2, width="stretch")


# ---------------------------------------------------------------- Historical tab
@st.cache_data
def load(path):
    df = pd.read_csv(path, parse_dates=["timestamp_utc"], dtype={"token_id": str})
    df["price"] *= 100   # show price as a percentage (0.635 -> 63.5%)
    df["change"] *= 100  # change in percentage points
    return df


def historical_tab():
    try:
        df = load(DATA)
    except FileNotFoundError:
        st.info(f"No data at `{DATA}`. Run `python download_polymarket.py` first.")
        return

    c1, c2 = st.columns(2)
    event = c1.selectbox("Game", sorted(df["event"].unique()))
    ev = df[df["event"] == event]
    market = c2.selectbox("Market", sorted(ev["market"].unique()))
    mk = ev[ev["market"] == market]

    # Time window (default: last 12 hours of the market, where most in-game movement is)
    tmin, tmax = mk["timestamp_utc"].min().to_pydatetime(), mk["timestamp_utc"].max().to_pydatetime()
    default_start = max(tmin, tmax - pd.Timedelta(hours=12))
    start, end = st.slider("Time window (UTC)", min_value=tmin, max_value=tmax,
                           value=(default_start, tmax), format="MM-DD HH:mm")
    view = mk[(mk["timestamp_utc"] >= start) & (mk["timestamp_utc"] <= end)]
    colors = color_map(sorted(mk["outcome"].unique()))

    cols = st.columns(view["outcome"].nunique())
    for col, (outcome, g) in zip(cols, view.groupby("outcome")):
        first, last = g["price"].iloc[0], g["price"].iloc[-1]
        col.metric(outcome, f"{last:.1f}%", f"{last - first:+.1f} pts in window")
        col.caption(f"Minutes with a move: {(g['change'] != 0).sum():,} · "
                    f"Biggest 1-min move: {g['change'].abs().max():.1f} pts")

    charts(view, colors)

    st.subheader("Biggest 1-minute moves")
    top = view.reindex(view["change"].abs().sort_values(ascending=False).index).head(15)
    st.dataframe(top[["timestamp_utc", "outcome", "price", "change", "pct_change"]], hide_index=True,
                 column_config={"price": PCT,
                                "change": st.column_config.NumberColumn("change (pts)", format="%+.1f"),
                                "pct_change": st.column_config.NumberColumn(format="%+.1f%%")})

    with st.expander("Raw data"):
        st.dataframe(view, hide_index=True, column_config={"price": PCT})
        st.download_button("Download this view as CSV", view.to_csv(index=False),
                           file_name="polymarket_view.csv", mime="text/csv")


# ---------------------------------------------------------------- Live tab
def outcome_lines(event):
    """[(label, token_id, price)] for the game-winner market(s) of an event.
    2-way sports have one market with two outcomes; soccer has one Yes/No market per result."""
    lines = []
    for m in event.get("markets", []):
        if m.get("sportsMarketType") != "moneyline" or not m.get("clobTokenIds"):
            continue
        outcomes = json.loads(m.get("outcomes") or "[]")
        tokens = json.loads(m["clobTokenIds"])
        prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
        if outcomes == ["Yes", "No"]:
            label = m.get("groupItemTitle") or m["question"]
            label = "Draw" if label.startswith("Draw") else label
            lines.append((label, tokens[0], prices[0] if prices else None))
        else:
            lines.extend(zip(outcomes, tokens, prices or [None] * len(tokens)))
    return lines


@st.cache_data(ttl=55)
def fetch_live_games():
    events, offset = [], 0
    while True:
        page = get_json(GAMMA, {"tag_id": GAMES_TAG_ID, "closed": "false", "live": "true",
                                "limit": PAGE_SIZE, "offset": offset})
        events.extend(page)
        offset += len(page)
        if len(page) < PAGE_SIZE:
            break
    now, games = pd.Timestamp.now(tz="UTC"), []
    for e in events:
        lines = outcome_lines(e)
        if not lines or (e.get("startTime") and pd.Timestamp(e["startTime"]) > now):
            continue  # no game-winner market, or a stale "live" flag on a game that hasn't started
        games.append({"id": e["id"], "title": e["title"],
                      "league": (e.get("sport") or {}).get("name", "Other"),
                      "score": e.get("score") or "",
                      "clock": " ".join(x for x in [e.get("period"), e.get("elapsed")] if x),
                      "lines": lines})
    return games


@st.cache_data(ttl=55)
def live_history(token_id, hours=6):
    """Minute data for the last `hours` hours."""
    end = int(pd.Timestamp.now(tz="UTC").timestamp())
    prices = fetch_history(token_id, end - hours * 3600, end)
    return None if prices.empty else to_minutes(prices)


# ---------------------------------------------------------------- Live tab (Polymarket-style cards)
CSS_STYLE = dict(zip(COLORS, ["blue", "red", "gray"]))  # chart color -> button CSS class


def game_frames(game):
    """Minute data (in %) for each outcome of a live game."""
    frames = []
    for name, token, _ in game["lines"]:
        df = live_history(token)
        if df is None:
            continue
        df = df.rename_axis("timestamp_utc").reset_index().assign(outcome=name)
        df["price"] *= 100
        df["change"] *= 100
        frames.append(df)
    return frames


@st.dialog("Price chart", width="large", on_dismiss=lambda: st.session_state.pop("chart", None))
def chart_dialog(game):
    st.markdown(f"**{game['title']}** · {game['score']} {game['clock']}")
    frames = game_frames(game)
    if frames:
        charts(pd.concat(frames), color_map([n for n, _, _ in game["lines"]]))
    else:
        st.info("No price history yet for this game.")


@st.dialog("Bet slip", on_dismiss=lambda: st.session_state.pop("slip", None))
def bet_slip(slip):
    price = slip["price"]
    st.markdown(f"**{slip['title']}**  \n{slip['league']}")
    st.markdown(f"Buy **{slip['outcome']}** at **{price * 100:.1f}¢**")
    balance = paper.cash()
    amount = st.number_input("Amount ($)", min_value=1.0, max_value=max(balance, 1.0),
                             value=min(10.0, max(balance, 1.0)), step=5.0)
    shares = amount / price
    c1, c2, c3 = st.columns(3)
    c1.metric("Shares", f"{shares:,.2f}")
    c2.metric("Payout if win", f"${shares:,.2f}")
    c3.metric("Profit if win", f"${shares - amount:,.2f}")
    st.caption(f"Cash available: ${balance:,.2f} · Each share pays $1 if {slip['outcome']} wins, $0 if not.")
    if st.button("Place bet", type="primary", width="stretch", disabled=amount > balance):
        try:
            paper.place_bet(slip["title"], slip["league"], slip["outcome"], slip["token"], price, amount,
                            match_tokens=slip["match_tokens"])
        except ValueError as e:
            st.error(str(e))
            return
        del st.session_state["slip"]
        st.session_state.toasts = [f"Bet placed: ${amount:,.2f} on {slip['outcome']} at {price * 100:.1f}¢"]
        st.rerun()


def odds_ratio(g):
    """Favorite's price / underdog's price, e.g. 90¢ vs 10¢ -> 9.0 (a 60-40 game -> 1.5)."""
    prices = [p for _, _, p in g["lines"] if p is not None]
    return max(prices) / max(min(prices), 0.001) if len(prices) > 1 else 0.0


def game_card(g, already_bet):
    with st.container(key=f"card_{g['id']}", border=True):
        st.html(f"""
          <div class="pm-head"><span>{escape(g['league'])} · {odds_ratio(g):.1f} : 1</span>
            <span class="pm-live">LIVE {escape(g['clock'])}</span></div>
          <div class="pm-title">{escape(g['title'])}</div>
          <div class="pm-score">{escape(g['score']) or '&nbsp;'}</div>""")
        styles = color_map([n for n, _, _ in g["lines"]])
        match_tokens = [t for _, t, _ in g["lines"]]
        cols = st.columns(len(g["lines"]))
        for i, (col, (name, token, price)) in enumerate(zip(cols, g["lines"])):
            tradable = price is not None and 0.001 < price < 0.999 and not already_bet
            label = f"{name}  {price * 100:.0f}¢" if price is not None else name
            with col.container(key=f"{CSS_STYLE[styles[name]]}_{g['id']}_{i}"):
                if st.button(label, key=f"buy_{g['id']}_{i}", width="stretch", disabled=not tradable):
                    st.session_state.slip = {"title": g["title"], "league": g["league"], "outcome": name,
                                             "token": token, "price": price, "match_tokens": match_tokens}
                    st.rerun(scope="app")
        if already_bet:
            st.caption("✓ You already have a bet on this match — see My Bets")
        if st.button("📈 Chart", key=f"chart_{g['id']}", type="tertiary"):
            st.session_state.chart = g
            st.rerun(scope="app")


@st.fragment(run_every=60)
def live_tab():
    games = fetch_live_games()
    if not games:
        st.info("No live games right now. This page checks again every minute.")
        return
    leagues = sorted({g["league"] for g in games})
    c1, c2 = st.columns([4, 1])
    league = c1.pills("League", ["All"] + leagues, default="All", key="league_filter",
                      label_visibility="collapsed") or "All"
    sort = c2.selectbox("Sort by", ["League", "Odds ratio (high → low)"], key="live_sort",
                        label_visibility="collapsed")
    shown = [g for g in games if league == "All" or g["league"] == league]
    if sort == "League":
        shown.sort(key=lambda g: (g["league"], g["title"]))
    else:
        shown.sort(key=odds_ratio, reverse=True)
    st.caption(f"{len(shown)} live games · auto-refreshes every 60s · "
               f"updated {pd.Timestamp.now(tz='UTC'):%H:%M:%S} UTC")
    mine = paper.bet_tokens()
    cols = st.columns(3)
    for i, g in enumerate(shown):
        with cols[i % 3]:
            game_card(g, already_bet=any(t in mine for _, t, _ in g["lines"]))


# ---------------------------------------------------------------- My Bets tab
@st.cache_data(ttl=55)
def cached_prices(token_ids):
    return paper.market_prices(token_ids)


def money(x, sign=False):
    return f"{'+' if sign and x >= 0 else '-' if x < 0 else ''}${abs(x):,.2f}"


@st.fragment(run_every=60)
def bets_tab():
    open_bets = paper.bets("open")
    prices = cached_prices(tuple(sorted(open_bets["token_id"]))) if not open_bets.empty else {}
    settled = paper.settle_open_bets(prices)
    stopped = paper.apply_stop_loss(prices)
    if settled or stopped:  # update everything (including the cash in the header)
        st.session_state.toasts = [settle_msg(s) for s in settled] + [
            f"🛑 Stop-loss sold {s['outcome']} ({s['event']}): {money(s['profit'], sign=True)}" for s in stopped]
        st.rerun(scope="app")

    all_bets = paper.bets()
    open_bets = all_bets[all_bets["status"] == "open"].copy()
    closed = all_bets[all_bets["status"] != "open"].copy()
    open_bets["now"] = [prices.get(t, (None, False))[0] for t in open_bets["token_id"]]
    open_bets["value"] = open_bets["shares"] * open_bets["now"].fillna(open_bets["price"])
    open_bets["pnl"] = open_bets["value"] - open_bets["amount"]
    closed["pnl"] = closed["payout"] - closed["amount"]

    cash, positions = paper.cash(), open_bets["value"].sum()
    c = st.columns(5)
    c[0].metric("Portfolio", money(cash + positions))
    c[1].metric("Cash", money(cash))
    c[2].metric("Total P&L", money(cash + positions - paper.START_BALANCE, sign=True))
    c[3].metric("Open P&L", money(open_bets["pnl"].sum(), sign=True))
    c[4].metric("Settled P&L", money(closed["pnl"].sum(), sign=True))
    st.caption(f"Started with {money(paper.START_BALANCE)} paper money · prices refresh every 60s · "
               f"stop-loss sells a bet automatically if its value drops below "
               f"{paper.STOP_LOSS:.0%} of the amount paid")

    st.subheader(f"Open positions ({len(open_bets)})")
    if open_bets.empty:
        st.info("No open bets. Place one from the Live tab.")
    for b in open_bets.itertuples():
        with st.container(border=True):
            c = st.columns([4, 2, 2, 2, 1.5])
            c[0].markdown(f"**{b.outcome}**  \n{b.event_title} · {b.league}")
            c[1].markdown(f"Bought **{b.price * 100:.1f}¢**  \n{money(b.amount)} · {b.shares:,.1f} sh  \n"
                          f":gray[Stop-loss below {b.price * paper.STOP_LOSS * 100:.1f}¢]")
            now_txt = f"{b.now * 100:.1f}¢" if pd.notna(b.now) else "–"
            c[2].markdown(f"Now **{now_txt}**  \nValue {money(b.value)}")
            color = "green" if b.pnl >= 0 else "red"
            c[3].markdown(f"P&L  \n:{color}[**{money(b.pnl, sign=True)}** "
                          f"({b.pnl / b.amount * 100:+.1f}%)]")
            if c[4].button("Cash out", key=f"cashout_{b.id}", disabled=pd.isna(b.now),
                           help=f"Sell now for {money(b.value)}"):
                paper.cash_out(b.id, b.now)
                st.session_state.toasts = [f"Cashed out {b.outcome}: {money(b.pnl, sign=True)}"]
                st.rerun(scope="app")

    st.subheader(f"History ({len(closed)})")
    if closed.empty:
        st.caption("Settled and cashed-out bets will appear here.")
    else:
        st.dataframe(closed[["closed_at", "event_title", "outcome", "status", "price", "amount", "payout", "pnl"]],
                     hide_index=True, column_config={
                         "closed_at": "Closed (UTC)", "event_title": "Game", "status": "Result",
                         "price": st.column_config.NumberColumn("Bought at", format="%.3f"),
                         "amount": st.column_config.NumberColumn("Stake", format="$%.2f"),
                         "payout": st.column_config.NumberColumn("Payout", format="$%.2f"),
                         "pnl": st.column_config.NumberColumn("P&L", format="$%+.2f")})

    with st.expander("Reset paper account"):
        st.write(f"Deletes all bets and restores the {money(paper.START_BALANCE)} starting balance.")
        if st.checkbox("I understand this deletes my bet history") and st.button("Reset", type="primary"):
            paper.reset()
            st.rerun(scope="app")


def settle_msg(s):
    return f"{'✅ Won' if s['won'] else '❌ Lost'}: {s['outcome']} ({s['event']}) {money(s['profit'], sign=True)}"


# ---------------------------------------------------------------- Page
# Catch-up: settle bets whose games ended while the app (or PC) was off. Once per browser session.
if "caught_up" not in st.session_state:
    st.session_state.caught_up = True
    away = paper.settle_open_bets()
    if away:
        total = sum(s["profit"] for s in away)
        st.session_state.toasts = [f"{len(away)} bet(s) settled while you were away: {money(total, sign=True)}"] \
            + [settle_msg(s) for s in away]

for msg in st.session_state.pop("toasts", []):
    st.toast(msg)

head, bal = st.columns([4, 1])
head.title("Sports odds — live")
bal.metric("Cash (paper)", money(paper.cash()))

tab_live, tab_bets, tab_hist = st.tabs(["🔴 Live", "💼 My Bets", "📊 Historical"])
with tab_live:
    live_tab()
with tab_bets:
    bets_tab()
with tab_hist:
    historical_tab()

if "slip" in st.session_state:
    bet_slip(st.session_state.slip)  # stays open until placed or dismissed
elif "chart" in st.session_state:
    chart_dialog(st.session_state.chart)
