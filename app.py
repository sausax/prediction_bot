"""Web app for viewing downloaded Polymarket minute data.

Run:  streamlit run app.py
"""
import pandas as pd
import plotly.express as px
import streamlit as st

DATA = "data/polymarket_sports_minutes.csv"

st.set_page_config(page_title="Polymarket Sports Odds", layout="wide")
st.title("Polymarket sports odds — minute by minute")


@st.cache_data
def load(path):
    df = pd.read_csv(path, parse_dates=["timestamp_utc"], dtype={"token_id": str})
    df["price"] *= 100   # show price as a percentage (0.635 -> 63.5%)
    df["change"] *= 100  # change in percentage points
    return df


try:
    df = load(DATA)
except FileNotFoundError:
    st.error(f"No data at `{DATA}`. Run `python download_polymarket.py` first.")
    st.stop()

# --- Pick a game and market ---
c1, c2 = st.columns(2)
event = c1.selectbox("Game", sorted(df["event"].unique()))
ev = df[df["event"] == event]
market = c2.selectbox("Market", sorted(ev["market"].unique()))
mk = ev[ev["market"] == market]

# --- Time window (default: last 12 hours of the market, where most in-game movement is) ---
tmin, tmax = mk["timestamp_utc"].min().to_pydatetime(), mk["timestamp_utc"].max().to_pydatetime()
default_start = max(tmin, tmax - pd.Timedelta(hours=12))
start, end = st.slider("Time window (UTC)", min_value=tmin, max_value=tmax,
                       value=(default_start, tmax), format="MM-DD HH:mm")
view = mk[(mk["timestamp_utc"] >= start) & (mk["timestamp_utc"] <= end)]
colors = dict(zip(sorted(mk["outcome"].unique()), ["#1f5fd1", "#d62728"]))  # blue, red
pct = st.column_config.NumberColumn(format="%.1f%%")

# --- Summary stats per outcome ---
cols = st.columns(view["outcome"].nunique())
for col, (outcome, g) in zip(cols, view.groupby("outcome")):
    first, last = g["price"].iloc[0], g["price"].iloc[-1]
    col.metric(outcome, f"{last:.1f}%", f"{last - first:+.1f} pts in window")
    col.caption(f"Minutes with a move: {(g['change'] != 0).sum():,} · "
                f"Biggest 1-min move: {g['change'].abs().max():.1f} pts")

# --- Charts ---
st.subheader("Win probability (%)")
fig = px.line(view, x="timestamp_utc", y="price", color="outcome", color_discrete_map=colors)
fig.update_layout(yaxis_range=[0, 100], yaxis_ticksuffix="%", yaxis_title="Price", hovermode="x unified", xaxis_title=None)
fig.update_traces(hovertemplate="%{y:.1f}%")
st.plotly_chart(fig, width="stretch")

st.subheader("Change vs previous minute (percentage points)")
fig2 = px.bar(view, x="timestamp_utc", y="change", color="outcome", barmode="group", color_discrete_map=colors)
fig2.update_layout(hovermode="x unified", xaxis_title=None, yaxis_title="Change (pts)")
fig2.update_traces(hovertemplate="%{y:+.1f} pts")
st.plotly_chart(fig2, width="stretch")

# --- Biggest moves + raw data ---
st.subheader("Biggest 1-minute moves")
top = view.reindex(view["change"].abs().sort_values(ascending=False).index).head(15)
st.dataframe(top[["timestamp_utc", "outcome", "price", "change", "pct_change"]], hide_index=True,
             column_config={"price": pct, "change": st.column_config.NumberColumn("change (pts)", format="%+.1f"),
                            "pct_change": st.column_config.NumberColumn(format="%+.1f%%")})

with st.expander("Raw data"):
    st.dataframe(view, hide_index=True, column_config={"price": pct})
    st.download_button("Download this view as CSV", view.to_csv(index=False),
                       file_name="polymarket_view.csv", mime="text/csv")
