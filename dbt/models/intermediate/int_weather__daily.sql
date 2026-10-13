with observations as (

    select * from {{ ref('stg_weather__observations') }}

),

daily as (

    select
        date(observed_at_nyc)                                    as weather_date,
        avg(temp_c)                                              as avg_temp_c,
        min(temp_c)                                              as min_temp_c,
        max(temp_c)                                              as max_temp_c,
        avg(wind_speed_ms)                                       as avg_wind_speed_ms,
        avg(rain_mm_per_hour)                                    as avg_rain_mm_per_hour,

        -- rainy / snowy hours during riding hours (06:00-22:00)
        count(distinct case when is_rain and hour(observed_at_nyc) between 6 and 21
                            then date_trunc('hour', observed_at_nyc) end)    as rainy_riding_hours,
        count(distinct case when is_snow and hour(observed_at_nyc) between 6 and 21
                            then date_trunc('hour', observed_at_nyc) end)    as snowy_riding_hours,
        count(distinct case when hour(observed_at_nyc) between 6 and 21
                            then date_trunc('hour', observed_at_nyc) end)    as riding_hours_observed

    from observations
    group by 1

)

select
    *,
    case
        when snowy_riding_hours > 0 then 'Snow'
        when rainy_riding_hours > 0 then 'Rain'
        else 'Dry'
    end                                                          as day_condition,
    case
        when rainy_riding_hours = 0             then '0 hours'
        when rainy_riding_hours between 1 and 2 then '1-2 hours'
        when rainy_riding_hours between 3 and 5 then '3-5 hours'
        else '6+ hours'
    end                                                          as rain_hours_band
from daily