USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

-- 1. How many locations are in the data?
SELECT raw:city.id::INT          AS city_id,
       raw:city.coord.lat::FLOAT AS lat,
       raw:city.coord.lon::FLOAT AS lon,
       COUNT(*)                  AS readings
FROM WEATHER
GROUP BY 1, 2, 3;

-- 2. What units is temperature in?
SELECT MIN(raw:main.temp::FLOAT) AS min_temp,
       MAX(raw:main.temp::FLOAT) AS max_temp
FROM WEATHER;

-- 3. What does the time look like, and what range does it cover?
SELECT raw:time::INT                                         AS epoch,
       TO_TIMESTAMP(raw:time::INT)                           AS utc_time,
       CONVERT_TIMEZONE('UTC', 'America/New_York',
                        TO_TIMESTAMP(raw:time::INT))         AS nyc_time
FROM WEATHER
LIMIT 5;

-- 4. How often is rain / snow actually recorded?
SELECT COUNT(*)                         AS readings,
       COUNT_IF(raw:rain IS NOT NULL)   AS has_rain,
       COUNT_IF(raw:snow IS NOT NULL)   AS has_snow
FROM WEATHER;


-- How do the label and the measured amount line up?
SELECT raw:weather[0].main::STRING   AS label,
       COUNT(*)                      AS readings,
       COUNT_IF(raw:rain IS NOT NULL) AS has_rain_amount
FROM WEATHER
WHERE raw:city.id::INT = 5128581
GROUP BY 1
ORDER BY 2 DESC;

-- What keys are inside the rain object?
SELECT DISTINCT OBJECT_KEYS(raw:rain) AS rain_keys
FROM WEATHER
WHERE raw:rain IS NOT NULL;