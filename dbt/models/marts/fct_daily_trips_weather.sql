with trips as (

    select * from {{ ref('int_trips__daily') }}

),

weather as (

    select * from {{ ref('int_weather__daily') }}

)

select
    trips.trip_date,
    dayname(trips.trip_date)                                     as day_name,
    dayofweekiso(trips.trip_date) in (6, 7)                      as is_weekend,
    year(trips.trip_date)                                        as trip_year,
    monthname(trips.trip_date)                                   as month_name,
    month(trips.trip_date)                                       as month_num,
    case
        when month(trips.trip_date) in (12, 1, 2) then 'Winter'
        when month(trips.trip_date) in (3, 4, 5)  then 'Spring'
        when month(trips.trip_date) in (6, 7, 8)  then 'Summer'
        else 'Autumn'
    end                                                          as season,

    trips.trips,
    trips.member_trips,
    trips.casual_trips,
    trips.avg_trip_minutes,

    weather.avg_temp_c,
    weather.min_temp_c,
    weather.max_temp_c,
    weather.avg_wind_speed_ms,
    weather.avg_rain_mm_per_hour,
    weather.rainy_riding_hours,
    weather.snowy_riding_hours,
    weather.riding_hours_observed,
    weather.day_condition,
    weather.rain_hours_band

from trips
inner join weather
    on trips.trip_date = weather.weather_date
    -- inner join = only days with both trips and weather, i.e. the overlap window