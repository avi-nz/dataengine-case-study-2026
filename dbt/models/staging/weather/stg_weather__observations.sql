with source as (

    select * from {{ source('weather', 'weather') }}

),

renamed as (

    select
        -- id: one reading per city per timestamp
        {{ dbt_utils.generate_surrogate_key(['raw:city.id', 'raw:time']) }} as observation_id,
        raw:city.id::int                                                  as city_id,

        -- time: epoch (UTC) -> timestamp -> New York local time
        to_timestamp_ntz(raw:time::int)                                   as observed_at_utc,
        convert_timezone('UTC', 'America/New_York',
                         to_timestamp_ntz(raw:time::int))                 as observed_at_nyc,

        -- temperature: Kelvin -> Celsius
        raw:main.temp::float - 273.15                                     as temp_c,
        raw:main.humidity::int                                            as humidity_pct,
        raw:wind.speed::float                                             as wind_speed_ms,
        raw:clouds.all::int                                               as cloud_cover_pct,

        -- condition label
        raw:weather[0].main::string                                       as weather_condition,
        raw:weather[0].description::string                                as weather_description,
        weather_condition in ('Rain', 'Drizzle', 'Thunderstorm')          as is_rain,
        weather_condition = 'Snow'                                        as is_snow,

        -- amounts: only sometimes present, in 1h or 3h windows -> mm per hour
        -- missing values are NULL,
        coalesce(raw:rain['1h']::float, raw:rain['3h']::float / 3)        as rain_mm_per_hour,
        coalesce(raw:snow['1h']::float, raw:snow['3h']::float / 3)        as snow_mm_per_hour,

        -- lineage
        _source_file,
        _loaded_at

    from source

)

select * from renamed
where city_id = 5128581   -- New York City only; 5128638 is New York State
qualify row_number() over (partition by observation_id order by _source_file) = 1
                          -- raw has exact duplicate readings. Keep one copy of each