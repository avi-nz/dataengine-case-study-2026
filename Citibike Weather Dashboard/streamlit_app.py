import pandas as pd
import altair as alt
import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

COLOURS = alt.Scale(domain=["Dry", "Rain", "Snow"], range=["#E8A33D", "#3D7EE8", "#9AA5B1"])
SEASONS = ["Spring", "Summer", "Autumn", "Winter"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BANDS = ["0 hours", "1-2 hours", "3-5 hours", "6+ hours"]


@st.cache_data
def load_daily():
    df = session.sql(
        "select * from CITIBIKE.ANALYTICS_MARTS.FCT_DAILY_TRIPS_WEATHER"
    ).to_pandas()
    df.columns = [c.lower() for c in df.columns]
    df["trip_date"] = pd.to_datetime(df["trip_date"])
    return df


def pct_change(new, base):
    if new is None or base is None or pd.isna(new) or pd.isna(base) or base == 0:
        return None
    return (new / base - 1) * 100


def round5(v):
    return None if v is None or pd.isna(v) else int(5 * round(v / 5))


def fmt_approx(v):
    """Rounded to the nearest 5%, in words: '~25% fewer'."""
    r = round5(v)
    if r is None:
        return "n/a"
    if r == 0:
        return "little change"
    return f"~{abs(r)}% {'fewer' if r < 0 else 'more'}"


def like_for_like(data, target, baseline="Dry", by="day_condition", col="trips"):
    """% change of `target` days vs `baseline` days, compared within the same
    season and day type, weighted by how many `target` days each group has."""
    means = data.groupby(["season", "is_weekend", by])[col].mean().unstack(by)
    if baseline not in means.columns or target not in means.columns:
        return None
    counts = (data[data[by] == target]
                .groupby(["season", "is_weekend"]).size().rename("n"))
    g = means[[baseline, target]].dropna().join(counts, how="inner")
    if g.empty:
        return None
    return ((g[target] / g[baseline] - 1) * g["n"]).sum() / g["n"].sum() * 100


df = load_daily()

# ---------------- filters ----------------
with st.sidebar:
    st.header("Compare like with like")
    seasons = st.multiselect("Season", SEASONS, default=SEASONS)
    day_type = st.radio("Day type", ["All days", "Weekdays", "Weekends"])

f = df[df.season.isin(seasons)]
if day_type == "Weekdays":
    f = f[~f.is_weekend]
elif day_type == "Weekends":
    f = f[f.is_weekend]
if f.empty:
    st.warning("No days match these filters.")
    st.stop()

no_snow = f[f.day_condition != "Snow"]
rain_l4l = like_for_like(f, "Rain")
snow_l4l = like_for_like(f, "Snow")
light_rain = like_for_like(no_snow, "1-2 hours", "0 hours", by="rain_hours_band")
heavy_rain = like_for_like(no_snow, "6+ hours", "0 hours", by="rain_hours_band")

# ---------------- headline ----------------
st.title("How weather affects Citibike usage in NYC")
st.caption(f"{len(f)} days, {f.trip_date.min():%d %b %Y} to {f.trip_date.max():%d %b %Y} "
           "· source: dbt mart fct_daily_trips_weather (production)")
st.info(
    f"**In short:** compared with dry days in the same season and day type, rain days have "
    f"**{fmt_approx(rain_l4l)}** trips and snow days **{fmt_approx(snow_l4l)}**. "
    f"A little rain barely matters ({fmt_approx(light_rain)} trips with 1-2 rainy hours), "
    f"but a wet day does ({fmt_approx(heavy_rain)} with 6+ rainy hours)."
)

t1, t2, t3, t4 = st.tabs(["1. Baseline", "2. Weather impact",
                          "3. Who is affected", "4. What to do"])

# ---------------- 1. baseline ----------------
with t1:
    st.subheader("What normal demand looks like")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Days analysed", f"{len(f):,}")
    c2.metric("Total trips", f"{f.trips.sum() / 1e6:.1f}M")
    c3.metric("Avg trips per day", f"{f.trips.mean():,.0f}")
    c4.metric("Weekend vs weekday",
              fmt_approx(pct_change(f.loc[f.is_weekend, "trips"].mean(),
                                    f.loc[~f.is_weekend, "trips"].mean())))

    ts = f.sort_values("trip_date").copy()
    ts["rolling_30d"] = ts["trips"].rolling(30, min_periods=7).mean()
    base = alt.Chart(ts).encode(x=alt.X("trip_date:T", title=None))
    st.altair_chart(
        base.mark_line(opacity=0.25, color="#3D7EE8").encode(
            y=alt.Y("trips:Q", title="Trips per day"))
        + base.mark_line(color="#1F3F7A", strokeWidth=2).encode(y="rolling_30d:Q"),
        width="stretch",
    )
    st.caption("Light line: each day. Dark line: 30-day average. Demand roughly triples "
               "from winter to summer, so weather has to be compared within the same season.")

    dow = f.groupby("day_name")["trips"].mean().reindex(DAYS).dropna().reset_index()
    st.altair_chart(
        alt.Chart(dow).mark_bar(color="#3D7EE8").encode(
            x=alt.X("day_name:N", sort=DAYS, title=None),
            y=alt.Y("trips:Q", title="Avg trips per day"),
            tooltip=["day_name", alt.Tooltip("trips:Q", format=",.0f")],
        ),
        width="stretch",
    )

# ---------------- 2. weather impact ----------------
with t2:
    st.subheader("How much do rain and snow reduce trips?")
    cols = st.columns(3)
    for col, cond, l4l in zip(cols, ["Dry", "Rain", "Snow"], [None, rain_l4l, snow_l4l]):
        days = f[f.day_condition == cond]
        if days.empty:
            col.metric(f"{cond} days", "no days")
            continue
        r = round5(l4l)
        col.metric(f"Avg trips, {cond.lower()} day ({len(days)} days)",
                   f"{days.trips.mean():,.0f}",
                   None if r is None else f"{r:+d}% like-for-like (approx.)")
    st.caption("Like-for-like: each rain or snow day is compared with dry days in the same "
               "season and day type, so 'winter is quiet' isn't mistaken for 'rain is bad'.")

    piv = f.pivot_table(index=["season", "is_weekend"], columns="day_condition",
                        values="trips", aggfunc="mean")
    tbl = pd.DataFrame(index=piv.index)
    for c in ["Dry", "Rain", "Snow"]:
        if c in piv.columns:
            tbl[f"{c} (avg trips)"] = piv[c].round(0).astype("Int64")
    if "Dry" in piv.columns:
        for c in ["Rain", "Snow"]:
            if c in piv.columns:
                tbl[f"{c} vs dry"] = ((piv[c] / piv["Dry"] - 1) * 100).map(fmt_approx)
    tbl = tbl.reset_index()
    tbl["is_weekend"] = tbl["is_weekend"].map({True: "Weekend", False: "Weekday"})
    tbl["season"] = pd.Categorical(tbl["season"], SEASONS, ordered=True)
    tbl = (tbl.sort_values(["season", "is_weekend"])
              .rename(columns={"season": "Season", "is_weekend": "Day type"}))
    st.dataframe(tbl, hide_index=True, width="stretch")

    st.markdown("**More rain, fewer trips?**")
    rb = (no_snow.groupby("rain_hours_band")
            .agg(avg_trips=("trips", "mean"), days=("trips", "size")).reset_index())
    st.altair_chart(
        alt.Chart(rb).mark_bar(color="#3D7EE8").encode(
            x=alt.X("rain_hours_band:N", sort=BANDS, title="Rainy hours between 06:00 and 22:00"),
            y=alt.Y("avg_trips:Q", title="Avg trips per day"),
            tooltip=["rain_hours_band", alt.Tooltip("avg_trips:Q", format=",.0f"), "days"],
        ),
        width="stretch",
    )
    st.caption(f"Like-for-like vs no rain: 1-2 rainy hours, {fmt_approx(light_rain)} trips; "
               f"6+ rainy hours, {fmt_approx(heavy_rain)}. It's sustained rain that matters.")

    st.markdown("**Temperature**")
    st.altair_chart(
        alt.Chart(f).mark_circle(opacity=0.6).encode(
            x=alt.X("avg_temp_c:Q", title="Average temperature (°C)"),
            y=alt.Y("trips:Q", title="Trips that day"),
            color=alt.Color("day_condition:N", scale=COLOURS, title="Day"),
            tooltip=[alt.Tooltip("trip_date:T", format="%a %d %b %Y"), "trips",
                     alt.Tooltip("avg_temp_c:Q", format=".1f"), "day_condition"],
        ),
        width="stretch",
    )
    st.caption("Trips rise with temperature until about 20 °C, then level off. "
               "At the same temperature, rain days (blue) sit below dry days.")

# ---------------- 3. who is affected ----------------
with t3:
    st.subheader("Members or casual riders: who stops riding?")
    rows = []
    for label, column in [("Member", "member_trips"), ("Casual", "casual_trips")]:
        for cond in ["Rain", "Snow"]:
            v = like_for_like(f, cond, col=column)
            if v is not None:
                rows.append({"rider": label, "condition": cond,
                             "change_vs_dry": v, "label": fmt_approx(v)})
    if rows:
        who = pd.DataFrame(rows)
        base = alt.Chart().encode(
            y=alt.Y("rider:N", title=None, sort=["Member", "Casual"]),
            x=alt.X("change_vs_dry:Q", title="% change in trips vs dry days (like-for-like)"),
        )
        bars = base.mark_bar().encode(
            color=alt.Color("rider:N", legend=None,
                            scale=alt.Scale(domain=["Member", "Casual"],
                                            range=["#1F3F7A", "#E8A33D"])))
        labels = base.mark_text(align="right", dx=-6).encode(text="label:N")
        st.altair_chart(
            alt.layer(bars, labels, data=who)
               .properties(width=550, height=90)
               .facet(row=alt.Row("condition:N", title=None,
                                  header=alt.Header(labelAngle=0, labelAlign="left")))
        )
    st.caption("Members mostly ride to work, so they have less choice. Casual riders ride "
               "for leisure and can simply not go.")

# ---------------- 4. what to do ----------------
with t4:
    st.subheader("What this means for Citibike operations")
    st.markdown(f"""
**1. Only plan for sustained rain, not any rain.**
*Observed:* 1-2 rainy hours means {fmt_approx(light_rain)} trips; 6+ rainy hours means {fmt_approx(heavy_rain)}.
*Recommendation:* trigger a "wet day" plan only when the forecast shows rain for most of the day.
Run fewer rebalancing trucks and move bike maintenance and station repairs to those days.

**2. Snow is the big one.**
*Observed:* snow days have {fmt_approx(snow_l4l)} trips, the largest effect in the data.
*Recommendation:* schedule winter fleet maintenance around snow forecasts, and prioritise clearing
docks at commuter stations, because members still ride.

**3. Use the weather forecast in demand planning.**
*Observed:* temperature and rain together explain much of the day-to-day swing in trips.
*Recommendation:* feed tomorrow's forecast (temperature + expected rainy hours) into daily
rebalancing targets instead of using last week's demand.

**Assumptions and limits**
- This shows correlation, not cause. Holidays and special events aren't controlled for.
- Based on July 2016 to June 2018; demand and the fleet have grown since.
- "Rainy hour" = weather label of Rain, Drizzle or Thunderstorm between 06:00 and 22:00
  (amounts are missing for two-thirds of rain readings).
""")