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


def fmt_ratio(v):
    """Rounded to the nearest half: 'about 2.5 times'."""
    if v is None or pd.isna(v):
        return "n/a"
    return f"about {round(v * 2) / 2:g} times"


def label_room(values):
    """x-axis range with extra space on the left so bar labels don't hit the axis."""
    return alt.Scale(domain=[min(values.min() * 1.5, -5), max(values.max(), 0)])


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

season_means = f.groupby("season")["trips"].mean()
season_ratio = (season_means["Summer"] / season_means["Winter"]
                if {"Summer", "Winter"} <= set(season_means.index) else None)

# ---------------- headline ----------------
st.title("How weather affects Citibike usage in NYC")
st.caption(f"{len(f)} days, {f.trip_date.min():%d %b %Y} to {f.trip_date.max():%d %b %Y} "
           "· source: dbt mart fct_daily_trips_weather (production)")
season_text = (f"**The season matters most:** an average summer day has {fmt_ratio(season_ratio)} "
               f"as many trips as a winter day. " if season_ratio else "")
st.info(
    season_text
    + f"**Weather matters on top of that:** compared with dry days in the same season and day type, "
      f"rain days have **{fmt_approx(rain_l4l)}** trips and snow days **{fmt_approx(snow_l4l)}**, "
      f"and the drop is biggest when it rains most of the day ({fmt_approx(heavy_rain)} with 6+ rainy hours)."
)

t1, t2, t3, t4 = st.tabs(["1. The seasons", "2. Weather on top",
                          "3. Who is affected", "4. What to do"])

# ---------------- 1. the seasons ----------------
with t1:
    st.subheader("The season sets the level of demand")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total trips", f"{f.trips.sum() / 1e6:.1f}M")
    c2.metric("Avg trips per day", f"{f.trips.mean():,.0f}")
    c3.metric("Summer day vs winter day", fmt_ratio(season_ratio))
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
    st.caption(f"Light line: each day. Dark line: 30-day average. A summer day has "
               f"{fmt_ratio(season_ratio)} as many trips as a winter day, so weather has to be "
               "compared within the same season.")

    st.markdown("**Season vs weather: which gap is bigger?**")
    sc = (f.groupby(["season", "day_condition"])
            .agg(avg_trips=("trips", "mean"), days=("trips", "size")).reset_index())
    st.altair_chart(
        alt.Chart(sc).mark_bar().encode(
            x=alt.X("day_condition:N", sort=["Dry", "Rain", "Snow"], title=None,
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("avg_trips:Q", title="Avg trips per day"),
            color=alt.Color("day_condition:N", scale=COLOURS, legend=None),
            tooltip=["season", "day_condition",
                     alt.Tooltip("avg_trips:Q", format=",.0f"), "days"],
        ).properties(width=140, height=260)
         .facet(column=alt.Column("season:N", sort=SEASONS, title=None))
    )
    st.caption("The difference between summer and winter is far bigger than the difference "
               "between a dry day and a rainy day in the same season.")

    dow = f.groupby("day_name")["trips"].mean().reindex(DAYS).dropna().reset_index()
    st.altair_chart(
        alt.Chart(dow).mark_bar(color="#3D7EE8").encode(
            x=alt.X("day_name:N", sort=DAYS, title=None),
            y=alt.Y("trips:Q", title="Avg trips per day"),
            tooltip=["day_name", alt.Tooltip("trips:Q", format=",.0f")],
        ),
        width="stretch",
    )
    st.caption("Weekdays are busiest, so most riders are commuting. "
               "So we compare weekdays and weekends separately.")

# ---------------- 2. weather on top ----------------
with t2:
    st.subheader("Within a season, how much do rain and snow reduce trips?")
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

    st.markdown("**Correlation with daily trips**")
    measures = {"avg_temp_c": "Average temperature",
                "rainy_riding_hours": "Rainy riding hours",
                "snowy_riding_hours": "Snowy riding hours",
                "avg_wind_speed_ms": "Wind speed"}
    corr = (f[list(measures) + ["trips"]].corr()["trips"]
              .drop("trips").rename(index=measures).round(2))
    st.dataframe(corr.rename("Correlation (r)").rename_axis("Weather measure").reset_index(),
                 hide_index=True)
    st.caption("r runs from -1 to 1 (0 = no relationship). Temperature has by far the strongest link, potentially due to summer being hotter"
               "with trips, which is the seasons again. Rain still matters on top of seasons "
               "Wind looks stronger than rain mostly because winter is windier.")

    st.markdown("**More rain, fewer trips?**")
    band_rows = []
    for b in BANDS[1:]:
        v = like_for_like(no_snow, b, "0 hours", by="rain_hours_band")
        if v is not None:
            band_rows.append({"band": b, "change": v, "label": fmt_approx(v)})
    if band_rows:
        rb = pd.DataFrame(band_rows)
        base = alt.Chart(rb).encode(
            y=alt.Y("band:N", sort=BANDS[1:], title=None),
            x=alt.X("change:Q", scale=label_room(rb["change"]),
                    title="% change in trips vs days with no rain (like-for-like)"),
        )
        st.altair_chart(
            (base.mark_bar(color="#3D7EE8", size=28)
             + base.mark_text(align="right", dx=-6).encode(text="label:N"))
            .properties(height=160),
            width="stretch",
        )
    st.caption("Rows: rainy hours between 06:00 and 22:00. Each band is compared with no-rain days "
               "in the same season and day type. The clear drop comes when it rains for most of the day.")

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
            x=alt.X("change_vs_dry:Q", scale=label_room(who["change_vs_dry"]),
                    title="% change in trips vs dry days (like-for-like)"),
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
    st.caption("Members potentially ride to work, so they have less choice. Casual riders ride "
               "for leisure and can simply not go.")

# ---------------- 4. what to do ----------------
with t4:
    st.subheader("What this means for Citibike operations")
    st.markdown(f"""
**1. Plan by season, adjust by weather.**

*What the data shows:* an average summer day has {fmt_ratio(season_ratio)} as many trips as a winter
day. Within a season, rain days have {fmt_approx(rain_l4l)} trips and snow days {fmt_approx(snow_l4l)}.

*What we'd do:* set fleet size, staff rosters and major maintenance windows by season (winter is
maintenance season). Then use tomorrow's forecast to fine-tune daily rebalancing targets.

**2. Scale the response to how long it rains.**

*What the data shows:* 1-2 rainy hours means {fmt_approx(light_rain)} trips; 6+ rainy hours means {fmt_approx(heavy_rain)}.

*What we'd do:* a short shower trims demand a little; a forecast of rain for most of the day cuts it
much more. Reserve the full "wet day" plan (fewer rebalancing trucks, bike maintenance and station
repairs moved to that day) for those days.

**3. Snow hits casual riders hardest.**

*What the data shows:* snow days have {fmt_approx(snow_l4l)} trips, the largest weather effect in the
data, and casual riders drop off far more than members.

*What we'd do:* schedule winter fleet maintenance around snow forecasts, keep commuter stations
clear because members still ride, and don't plan on casual demand on snow days.

**Assumptions and limits**
- This shows correlation, not cause. Holidays and special events aren't controlled for.
- "Season" bundles temperature, daylight and tourism together; this data can't separate them.
- Based on July 2016 to June 2018; demand and the fleet have grown since.
- "Rainy hour" = weather label of Rain, Drizzle or Thunderstorm between 06:00 and 22:00
  (amounts are missing for two-thirds of rain readings).
- "Dry" means no rain or snow, not necessarily sunny: it includes cloudy days.
""")