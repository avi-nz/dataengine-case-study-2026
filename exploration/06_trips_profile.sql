USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

--  checkign if all the timestamps parse (because Citibike changed formats over the years)
SELECT YEAR(TRY_TO_TIMESTAMP(starttime))              AS start_year,
       COUNT(*)                                       AS trip_rows,
       COUNT_IF(TRY_TO_TIMESTAMP(starttime) IS NULL)  AS unparseable_starttime
FROM TRIPS
GROUP BY 1
ORDER BY 1;

-- If any don't parse, what do they look like?
SELECT starttime, _source_file
FROM TRIPS
WHERE TRY_TO_TIMESTAMP(starttime) IS NULL
LIMIT 10;

-- checking the trip duration to see if there are any impossible or extreme durations
SELECT MIN(TRY_TO_NUMBER(tripduration))                        AS min_seconds,
       MEDIAN(TRY_TO_NUMBER(tripduration))                     AS median_seconds,
       MAX(TRY_TO_NUMBER(tripduration))                        AS max_seconds,
       COUNT_IF(TRY_TO_NUMBER(tripduration) < 60)              AS under_1_min,
       COUNT_IF(TRY_TO_NUMBER(tripduration) > 24 * 60 * 60)    AS over_1_day
FROM TRIPS;

-- checking what values do the category columns contain
SELECT usertype, COUNT(*) FROM TRIPS GROUP BY 1 ORDER BY 2 DESC;
SELECT gender,   COUNT(*) FROM TRIPS GROUP BY 1 ORDER BY 2 DESC;
SELECT MIN(TRY_TO_NUMBER(birth_year)), MAX(TRY_TO_NUMBER(birth_year)) FROM TRIPS;

-- checking if there duplicate trips
SELECT COUNT(*)                                                       AS trip_rows,
       COUNT(DISTINCT HASH(tripduration, starttime, stoptime,
                           start_station_id, end_station_id, bikeid)) AS distinct_trips
FROM TRIPS;

-- Could (bike + start time) identify a trip?
SELECT COUNT(*)                                  AS trip_rows,
       COUNT(DISTINCT HASH(bikeid, starttime))   AS distinct_bike_starts
FROM TRIPS;

-- Rows where one bike starts more than one trip at the same time
SELECT bikeid, starttime, stoptime, tripduration,
       start_station_name, end_station_name, usertype, _source_file
FROM TRIPS
QUALIFY COUNT(*) OVER (PARTITION BY bikeid, starttime) > 1
ORDER BY bikeid, starttime;