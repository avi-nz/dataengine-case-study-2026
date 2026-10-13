{{ config(materialized='table') }}
with source as (

    select * from {{ source('citibike', 'trips') }}

),

renamed as (

    select
        -- id: a bike can only start one trip at a time
        {{ dbt_utils.generate_surrogate_key(['bikeid', 'starttime']) }}  as trip_id,
        try_to_number(bikeid)                                           as bike_id,

        -- times (already New York local time)
        try_to_timestamp_ntz(starttime)                                 as started_at,
        try_to_timestamp_ntz(stoptime)                                  as ended_at,
        try_to_number(tripduration)                                     as trip_duration_seconds,
        trip_duration_seconds > 24 * 60 * 60                            as is_over_24h,

        -- stations
        try_to_number(start_station_id)                                 as start_station_id,
        start_station_name,
        try_to_double(start_station_latitude)                           as start_station_lat,
        try_to_double(start_station_longitude)                          as start_station_lon,
        try_to_number(end_station_id)                                   as end_station_id,
        end_station_name,
        try_to_double(end_station_latitude)                             as end_station_lat,
        try_to_double(end_station_longitude)                            as end_station_lon,

        -- rider type in plain language, eaiser to understand in report
        case usertype
            when 'Subscriber' then 'member'
            when 'Customer'   then 'casual'
            else 'unknown'
        end                                                             as user_type,

        -- lineage
        _source_file,
        _source_row,
        _loaded_at

        -- not brought through: gender, birth_year (not needed for the question,
        -- personal data), membership_type (not needed)

    from source

)

select * from renamed
qualify row_number() over (
    partition by trip_id
    order by _source_file, _source_row
) = 1   -- 19 bike+start clashes in raw (double-logged) so we keep the first recorded