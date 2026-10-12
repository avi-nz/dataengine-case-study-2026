USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

-- How many rows and files landed?
SELECT COUNT(*) AS trip_rows, COUNT(DISTINCT _source_file) AS trip_files FROM TRIPS;
SELECT COUNT(*) AS weather_rows, COUNT(DISTINCT _source_file) AS weather_files FROM WEATHER;

-- Snowflake's own record of every file it loaded
SELECT file_name, row_count, error_count, status
FROM CITIBIKE.INFORMATION_SCHEMA.LOAD_HISTORY
ORDER BY last_load_time DESC;