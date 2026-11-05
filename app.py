"""
Penn State deck parking app.
Live availability, today's price, and the time each deck is usually full,
using the history saved by collector.py.

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

# Penn State colors
NAVY = "#001E44"     # Nittany Navy
BEAVER = "#1E407C"   # Beaver Blue
PUGH = "#96BEE6"     # Pugh Blue
STATUS_STYLE = {
    "good": ("#2E7D32", "Spaces available"),
    "fair": ("#C98A00", "Filling up"),
    "poor": ("#C62828", "Full for visitors"),
    "unknown": ("#8A97A8", "No reading"),
    "error": ("#8A97A8", "Couldn't reach deck"),
}
FULLNESS = {"good": 0, "fair": 1, "poor": 2}

# Spaces per level, from Penn State Transportation Services (Nov 2026).
# Decks are mixed use: permit holders and visitors share these spaces.
DECK_LEVELS = {
    "East": {"Level 1": 96, "Level 2": 187, "Level 3": 187, "Level 4": 182,
             "Level 5": 189, "Level 6": 187, "Level 7": 201},
    "West": {"Level 1": 134, "Level 2": 287, "Level 3": 294, "Level 4": 295,
             "Level 5": 294, "Level 6": 310},
    "Eisenhower": {"Level 1": 55, "Level 2": 175, "Level 3": 176, "Level 4": 173,
                   "Level 5": 173, "Level 6": 187},
    "HUB": {"Lower level": 98, "Upper level": 253},
    "Nittany": {"Level 1": 118, "Level 2": 244, "Level 3": 245, "Level 4": 245,
                "Level 5": 241, "Level 6": 249},
}
DECK_SPACES = {deck: sum(levels.values()) for deck, levels in DECK_LEVELS.items()}
# Transportation Services: fair = 80-90% full, poor = 90% full or more.
STATUS_RANGE = {"good": (0.0, 0.80), "fair": (0.80, 0.90), "poor": (0.90, 1.0)}
MIN_DAYS = 2          # matching past days needed before showing a usual time
MIN_SAME_WEEKDAY = 3  # below this, compare with all weekdays (or weekends) instead
WEEKDAY_NAMES = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]

st.set_page_config(page_title="PSU Deck Parking", page_icon="🅿️", layout="wide")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@500;700&family=Roboto:wght@400;500;700&display=swap');
html, body, p, label, li {{ font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif; }}
h1, h2, h3 {{ font-family: 'Roboto Slab', Georgia, serif !important; color: {NAVY} !important; }}
.block-container {{ padding-top: 1.2rem; max-width: 1200px; }}
.band {{ background: {NAVY}; padding: 1.7rem 1.9rem 1.5rem; border-radius: 6px;
         border-bottom: 6px solid {BEAVER}; margin-bottom: 1.4rem; }}
.band .kicker {{ color: {PUGH}; font-size: .8rem; font-weight: 700; letter-spacing: .14em;
                 text-transform: uppercase; margin: 0 0 .35rem; }}
.band h1 {{ color: #fff !important; margin: 0; font-size: 2.15rem; line-height: 1.2; padding: 0; }}
.band .sub {{ color: {PUGH}; margin: .45rem 0 0; font-size: 1rem; }}
.deck {{ background: #fff; border: 1px solid #D5DEEA; border-top: 6px solid var(--s);
         border-radius: 4px; padding: 1rem 1rem .9rem; min-height: 270px; }}
.deck .name {{ font-family: 'Roboto Slab', Georgia, serif; font-weight: 700; font-size: 1.25rem; color: {NAVY}; }}
.deck .status {{ color: var(--s); font-weight: 700; font-size: 1.05rem; margin: .3rem 0 .75rem; }}
.deck .dot {{ display: inline-block; width: .7rem; height: .7rem; border-radius: 50%;
              background: var(--s); margin-right: .45rem; }}
.deck .spaces {{ font-size: .86rem; color: #5B6B80; margin: -.2rem 0 .55rem; }}
.deck .count {{ font-size: 1rem; color: {NAVY}; margin-bottom: .55rem; line-height: 1.3; }}
.deck .count b {{ font-size: 1.15rem; }}
.deck .count small {{ display: block; color: #5B6B80; font-size: .8rem; }}
.deck .usual {{ background: #EEF3F9; border-left: 4px solid {BEAVER}; padding: .45rem .6rem;
                font-size: .92rem; color: {NAVY}; margin-bottom: .55rem; line-height: 1.35; }}
.deck .usual small {{ color: #5B6B80; display: block; font-size: .78rem; margin-top: .15rem; }}
.deck .price {{ font-size: .88rem; color: #33475F; line-height: 1.35; }}
.deck .price b {{ color: {NAVY}; }}
.note {{ font-size: .84rem; color: #5B6B80; margin-top: .9rem; }}
</style>
""", unsafe_allow_html=True)


# ---------- data ----------
@st.cache_data(ttl=120)
def live_statuses() -> dict:
    return {deck: fetch_status(code) for deck, code in DECKS.items()}


@st.cache_data(ttl=600)
def load_history() -> pd.DataFrame:
    try:
        df = pd.read_csv(REPO_RAW + "data/deck_status.csv")
    except Exception:
        return pd.DataFrame(columns=["time", "deck", "status", "fullness", "date"])
    df["time"] = pd.to_datetime(df["timestamp_utc"], utc=True).dt.tz_convert(TZ)
    df["fullness"] = df["status"].map(FULLNESS)
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    return df.dropna(subset=["fullness"])


@st.cache_data(ttl=600)
def load_events() -> pd.DataFrame:
    try:
        ev = pd.read_csv(REPO_RAW + "events.csv", dtype={"date": str, "start": str, "end": str})
    except Exception:
        return pd.DataFrame()
    if ev.empty:
        return ev
    ev["rate"] = pd.to_numeric(ev["rate"], errors="coerce")
    ev["start_dt"] = pd.to_datetime(ev["date"] + " " + ev["start"]).dt.tz_localize(TZ)
    ev["end_dt"] = pd.to_datetime(ev["date"] + " " + ev["end"]).dt.tz_localize(TZ)
    return ev


# ---------- pricing ----------
def active_event(events: pd.DataFrame, deck: str, when: datetime):
    if events.empty:
        return None
    hits = events[events["deck"].isin([deck, "All"])
                  & (events["start_dt"] <= when) & (events["end_dt"] >= when)]
    return None if hits.empty else hits.sort_values("rate", ascending=False).iloc[0]


def price_text(event) -> str:
    if event is None:
        return "<b>$2</b> first hour, $1 after, $16 max"
    if pd.isna(event["rate"]):
        return f"<b>Event pricing</b> ({event['event']}), rate not posted yet"
    return f"<b>${event['rate']:.0f} event rate</b> ({event['event']})"


def occupancy_text(deck: str, status: str) -> str:
    """Turn good/fair/poor into an estimated number of parked cars."""
    total = DECK_SPACES[deck]
    if status not in STATUS_RANGE:
        return ""
    low, high = STATUS_RANGE[status]
    cars_low, cars_high = math.ceil(total * low), math.floor(total * high)
    open_low, open_high = total - cars_high, total - cars_low
    if status == "good":
        return (f"Fewer than <b>{cars_high:,}</b> cars parked"
                f"<small>More than {open_low:,} spaces open (under 80% full)</small>")
    if status == "fair":
        return (f"About <b>{cars_low:,}–{cars_high:,}</b> cars parked"
                f"<small>About {open_low:,}–{open_high:,} spaces open (80–90% full)</small>")
    return (f"<b>{cars_low:,}+</b> cars parked"
            f"<small>{open_high:,} or fewer spaces open (90%+ full)</small>")


def hourly_cost(hours: float) -> int:
    """Normal deck rate: $2 first hour, $1 each extra hour, $16 max."""
    return 0 if hours <= 0 else min(2 + (math.ceil(hours) - 1), 16)


# ---------- "usually full at" ----------
def comparable_days(history: pd.DataFrame, events: pd.DataFrame, now: datetime):
    """Past days that behave like today, and a label for them."""
    event_dates = set(events["date"]) if not events.empty else set()
    today = now.strftime("%Y-%m-%d")
    days = history[history["date"] != today][["date", "time"]].drop_duplicates("date")
    days["weekday"] = days["time"].dt.weekday

    if today in event_dates:
        return set(days[days["date"].isin(event_dates)]["date"]), "game days"

    normal = days[~days["date"].isin(event_dates)]
    same = set(normal[normal["weekday"] == now.weekday()]["date"])
    if len(same) >= MIN_SAME_WEEKDAY:
        return same, WEEKDAY_NAMES[now.weekday()]
    if now.weekday() < 5:
        return set(normal[normal["weekday"] < 5]["date"]), "weekdays"
    return set(normal[normal["weekday"] >= 5]["date"]), "weekends"


def usual_full_time(history: pd.DataFrame, events: pd.DataFrame, deck: str, now: datetime) -> dict:
    """
    For each comparable past day, find the first time the deck was marked full.
    If it was full on at least half of those days, the typical (median) first-full
    time, rounded to 15 minutes, is when it is "usually full".
    """
    dates, basis = comparable_days(history, events, now)
    h = history[(history["deck"] == deck) & (history["date"].isin(dates))]
    n_days = h["date"].nunique()
    if n_days < MIN_DAYS:
        return {"ready": False, "n_days": n_days, "basis": basis}

    full = h[h["status"] == "poor"]
    first_full = full.groupby("date")["time"].min()
    n_full = len(first_full)
    if n_full == 0 or n_full / n_days < 0.5:
        return {"ready": True, "n_days": n_days, "n_full": n_full, "basis": basis, "time": None}

    minutes = (first_full.dt.hour * 60 + first_full.dt.minute).median()
    minutes = int(round(minutes / 15) * 15)
    usual = now.replace(hour=minutes // 60 % 24, minute=minutes % 60, second=0, microsecond=0)
    return {"ready": True, "n_days": n_days, "n_full": n_full, "basis": basis, "time": usual}


def usual_text(u: dict) -> str:
    if not u["ready"]:
        return (f"Not enough history yet<small>Needs {MIN_DAYS} past {u['basis']} "
                f"(has {u['n_days']})</small>")
    if u["time"] is None:
        return (f"Usually doesn't fill on {u['basis']}"
                f"<small>Full on {u['n_full']} of {u['n_days']} past {u['basis']}</small>")
    return (f"Usually full by <b>{u['time']:%-I:%M %p}</b> on {u['basis']}"
            f"<small>Full on {u['n_full']} of {u['n_days']} past {u['basis']}</small>")


# ---------- page ----------
now = datetime.now(TZ)
statuses = live_statuses()
events = load_events()
history = load_history()

st.markdown(f"""
<div class="band">
  <p class="kicker">Penn State · University Park</p>
  <h1>Where to park on campus</h1>
  <p class="sub">Live visitor space at the five gated decks, checked {now:%-I:%M %p} on {now:%A, %B %-d}</p>
</div>
""", unsafe_allow_html=True)

cols = st.columns(len(DECKS))
for col, deck in zip(cols, DECKS):
    status = statuses[deck]
    color, label = STATUS_STYLE.get(status, STATUS_STYLE["unknown"])
    usual = usual_text(usual_full_time(history, events, deck, now))
    price = price_text(active_event(events, deck, now))
    col.markdown(f"""
    <div class="deck" style="--s:{color}">
      <div class="name">{deck} Deck</div>
      <div class="spaces">{DECK_SPACES[deck]:,} spaces</div>
      <div class="status"><span class="dot"></span>{label}</div>
      <div class="count">{occupancy_text(deck, status)}</div>
      <div class="usual">{usual}</div>
      <div class="price">{price}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown(
    '<p class="note">Penn State publishes each deck as available, filling up, or full, not an exact '
    'car count. Car numbers are estimated from that status using Transportation Services\' definitions: '
    'fair is 80–90% full and full is 90% or more. "Usually full by" is the typical time each deck first '
    'showed as full on similar past days.</p>',
    unsafe_allow_html=True)

with st.expander("Spaces on each level"):
    lc = st.columns(len(DECK_LEVELS))
    for c, (deck, levels) in zip(lc, DECK_LEVELS.items()):
        c.markdown(f"**{deck} Deck** · {DECK_SPACES[deck]:,}")
        c.markdown("\n".join(f"- {lvl}: {n:,}" for lvl, n in levels.items()))
    st.caption("Decks are shared by permit holders and visitors. On busy weekdays Penn State closes a "
               "deck to visitors before it's completely full, so permit holders still have space.")

st.header("What will it cost?")
c1, c2 = st.columns(2)
deck_choice = c1.selectbox("Deck", list(DECKS))
hours = c2.slider("Hours parked", 0.5, 12.0, 2.0, 0.5)
event = active_event(events, deck_choice, now)
if event is not None and not pd.isna(event["rate"]):
    st.info(f"An event rate applies at {deck_choice} Deck right now: "
            f"**${event['rate']:.0f} flat** for {event['event']}.")
elif event is not None:
    st.info(f"Event pricing applies at {deck_choice} Deck today ({event['event']}); "
            "the rate hasn't been posted yet.")
else:
    st.success(f"Parking {hours:g} hours at {deck_choice} Deck costs **${hourly_cost(hours)}**.")

if not events.empty:
    upcoming = events[events["end_dt"] >= now].sort_values("start_dt")
    if not upcoming.empty:
        st.header("Upcoming events")
        table = upcoming[["date", "event", "deck", "rate"]].copy()
        table["rate"] = table["rate"].map(lambda r: "Not posted yet" if pd.isna(r) else f"${r:.0f}")
        table["deck"] = table["deck"].replace({"All": "All decks"})
        st.dataframe(table.rename(columns=str.capitalize), hide_index=True, width="stretch")

st.header("How busy has it been?")
if history.empty:
    st.write("History appears here once the collector has saved some readings.")
else:
    h1, h2 = st.columns(2)
    hist_deck = h1.selectbox("Deck ", list(DECKS), key="hist_deck")
    days = h2.radio("Period", [1, 7, 30], index=1, horizontal=True,
                    format_func=lambda d: f"Last {d} day{'s' if d > 1 else ''}")
    recent = history[(history["deck"] == hist_deck)
                     & (history["time"] >= pd.Timestamp(now) - pd.Timedelta(days=days))]
    if recent.empty:
        st.write(f"No readings for {hist_deck} Deck in this period yet.")
    else:
        timeline = alt.Chart(recent).mark_line(
            interpolate="step-after", color=BEAVER, strokeWidth=2.5, point=True).encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("fullness:Q", title=None, scale=alt.Scale(domain=[0, 2]),
                    axis=alt.Axis(values=[0, 1, 2],
                                  labelExpr="['Under 80%','80–90% full','90%+ full'][datum.value]")),
        ).properties(height=220)
        st.altair_chart(timeline, width="stretch")

        by_hour = (recent.assign(hour=recent["time"].dt.hour)
                   .groupby("hour")["status"].apply(lambda s: (s == "poor").mean() * 100)
                   .reset_index(name="pct_full"))
        st.subheader("How often it's full, by hour of day")
        bars = alt.Chart(by_hour).mark_bar(color=NAVY).encode(
            x=alt.X("hour:O", title="Hour of day"),
            y=alt.Y("pct_full:Q", title="% of readings full", scale=alt.Scale(domain=[0, 100])),
        ).properties(height=220)
        st.altair_chart(bars, width="stretch")

st.markdown(
    '<p class="note">Independent student project, not affiliated with Penn State. Availability comes '
    'from Transportation Services\' public deck displays; event rates are entered from official '
    'announcements. Deck permit holders aren\'t affected by visitor status.</p>',
    unsafe_allow_html=True)
