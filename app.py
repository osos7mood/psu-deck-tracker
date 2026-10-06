"""
Penn State deck parking app.
Shows live availability and today's price for the five gated decks,
plus history collected by collector.py.

Run locally:  streamlit run app.py
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from collector import DECKS, fetch_status

REPO_RAW = "https://raw.githubusercontent.com/osos7mood/psu-deck-tracker/main/"
TZ = ZoneInfo("America/New_York")

STATUS_INFO = {
    "good": ("🟢", "Spaces available"),
    "fair": ("🟡", "Filling up"),
    "poor": ("🔴", "Full for visitors"),
    "unknown": ("⚪", "No reading"),
    "error": ("⚪", "Couldn't reach deck"),
}
FULLNESS = {"good": 0, "fair": 1, "poor": 2}

st.set_page_config(page_title="PSU Deck Parking", page_icon="🅿️", layout="wide")


# ---------- data loading ----------
@st.cache_data(ttl=120)
def live_statuses() -> dict:
    return {deck: fetch_status(code) for deck, code in DECKS.items()}


@st.cache_data(ttl=600)
def load_history() -> pd.DataFrame:
    try:
        df = pd.read_csv(REPO_RAW + "data/deck_status.csv")
    except Exception:
        return pd.DataFrame(columns=["timestamp_local", "deck", "status"])
    df["time"] = pd.to_datetime(df["timestamp_utc"], utc=True).dt.tz_convert(TZ)
    df["fullness"] = df["status"].map(FULLNESS)
    return df.dropna(subset=["fullness"])


@st.cache_data(ttl=600)
def load_events() -> pd.DataFrame:
    try:
        ev = pd.read_csv(REPO_RAW + "events.csv")
    except Exception:
        return pd.DataFrame()
    if ev.empty:
        return ev
    ev["start_dt"] = pd.to_datetime(ev["date"] + " " + ev["start"]).dt.tz_localize(TZ)
    ev["end_dt"] = pd.to_datetime(ev["date"] + " " + ev["end"]).dt.tz_localize(TZ)
    return ev


# ---------- pricing ----------
def active_event(events: pd.DataFrame, deck: str, when: datetime):
    """Return the event row that sets this deck's price right now, or None."""
    if events.empty:
        return None
    hits = events[
        events["deck"].isin([deck, "All"])
        & (events["start_dt"] <= when)
        & (events["end_dt"] >= when)
    ]
    if hits.empty:
        return None
    return hits.sort_values("rate", ascending=False).iloc[0]  # higher rate wins


def hourly_cost(hours: float) -> int:
    """Normal deck rate: $2 first hour, $1 each extra hour, $16 max."""
    if hours <= 0:
        return 0
    return min(2 + (math.ceil(hours) - 1), 16)


# ---------- page ----------
now = datetime.now(TZ)
statuses = live_statuses()
events = load_events()

st.title("Penn State deck parking")
st.caption(
    f"Live visitor availability at the five gated decks, checked {now:%-I:%M %p} "
    f"on {now:%A, %b %-d}."
)

cols = st.columns(len(DECKS))
for col, deck in zip(cols, DECKS):
    emoji, label = STATUS_INFO.get(statuses[deck], STATUS_INFO["unknown"])
    event = active_event(events, deck, now)
    price = (
        f"Event rate: ${event['rate']:.0f} ({event['event']})"
        if event is not None
        else "Hourly: $2 first hour, $1 after, $16 max"
    )
    with col:
        st.subheader(f"{deck}")
        st.markdown(f"## {emoji}")
        st.markdown(f"**{label}**")
        st.caption(price)

st.divider()

# Cost calculator
st.header("What will it cost?")
c1, c2 = st.columns(2)
deck_choice = c1.selectbox("Deck", list(DECKS))
hours = c2.slider("Hours parked", 0.5, 12.0, 2.0, 0.5)
event = active_event(events, deck_choice, now)
if event is not None:
    st.info(
        f"An event rate applies at {deck_choice} Deck right now: "
        f"**${event['rate']:.0f} flat** for {event['event']}."
    )
else:
    st.success(f"Parking {hours:g} hours at {deck_choice} Deck costs **${hourly_cost(hours)}**.")

# Upcoming events
if not events.empty:
    upcoming = events[events["end_dt"] >= now].sort_values("start_dt")
    if not upcoming.empty:
        st.header("Upcoming event pricing")
        st.dataframe(
            upcoming[["date", "start", "end", "deck", "event", "rate"]].rename(
                columns=str.capitalize
            ),
            hide_index=True,
            width="stretch",
        )

st.divider()

# History
st.header("How busy has it been?")
history = load_history()
if history.empty:
    st.write("History will appear here once the collector has saved some readings.")
else:
    h1, h2 = st.columns(2)
    hist_deck = h1.selectbox("Deck ", list(DECKS), key="hist_deck")
    days = h2.radio("Period", [1, 7, 30], format_func=lambda d: f"Last {d} day{'s' if d > 1 else ''}",
                    horizontal=True)
    recent = history[(history["deck"] == hist_deck) &
                     (history["time"] >= pd.Timestamp(now) - pd.Timedelta(days=days))]

    if recent.empty:
        st.write(f"No readings for {hist_deck} Deck in this period yet.")
    else:
        timeline = alt.Chart(recent).mark_line(interpolate="step-after").encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("fullness:Q", title=None, scale=alt.Scale(domain=[0, 2]),
                    axis=alt.Axis(values=[0, 1, 2],
                                  labelExpr="['Available','Filling up','Full'][datum.value]")),
        ).properties(height=220)
        st.altair_chart(timeline, width="stretch")

        by_hour = (recent.assign(hour=recent["time"].dt.hour)
                   .groupby("hour")["status"].apply(lambda s: (s == "poor").mean() * 100)
                   .reset_index(name="pct_full"))
        st.subheader("Share of readings marked full, by hour of day")
        bars = alt.Chart(by_hour).mark_bar().encode(
            x=alt.X("hour:O", title="Hour of day"),
            y=alt.Y("pct_full:Q", title="% of readings full", scale=alt.Scale(domain=[0, 100])),
        ).properties(height=220)
        st.altair_chart(bars, width="stretch")

st.caption(
    "Availability comes from Penn State Transportation Services' public deck displays. "
    "Event rates are entered from official announcements. Permit holders aren't affected by visitor status."
)
