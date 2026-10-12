USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

-- checking how big the problem is (in NYC only)
SELECT COUNT(*)                         AS readings,
       COUNT(DISTINCT raw:time::int)    AS distinct_times
FROM WEATHER
WHERE raw:city.id::int = 5128581;

-- checking are the duplicates exact copies or are they different
SELECT COUNT(*)                           AS duplicated_times,
       COUNT_IF(distinct_versions > 1)    AS times_where_copies_differ
FROM (
    SELECT raw:time::int               AS t,
           COUNT(*)                    AS copies,
           COUNT(DISTINCT HASH(raw))   AS distinct_versions
    FROM WEATHER
    WHERE raw:city.id::int = 5128581
    GROUP BY 1
    HAVING COUNT(*) > 1
);

-- Looking at one duplicated reading side by side
SELECT raw:time::int AS t, raw:main.temp, raw:weather[0].main, _source_file
FROM WEATHER
WHERE raw:city.id::int = 5128581
QUALIFY COUNT(*) OVER (PARTITION BY raw:time::int) > 1
ORDER BY t
LIMIT 10;