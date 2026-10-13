select
    date(started_at)                                             as trip_date,
    count(*)                                                     as trips,
    count_if(user_type = 'member')                               as member_trips,
    count_if(user_type = 'casual')                               as casual_trips,
    avg(case when not is_over_24h then trip_duration_seconds end) / 60
                                                                 as avg_trip_minutes
from {{ ref('stg_citibike__trips') }}
group by 1