USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

CREATE TABLE IF NOT EXISTS TRIPS (
    tripduration             VARCHAR,  -- $1  seconds
    starttime                VARCHAR,  -- $2
    stoptime                 VARCHAR,  -- $3
    start_station_id         VARCHAR,  -- $4
    start_station_name       VARCHAR,  -- $5
    start_station_latitude   VARCHAR,  -- $6
    start_station_longitude  VARCHAR,  -- $7
    end_station_id           VARCHAR,  -- $8
    end_station_name         VARCHAR,  -- $9
    end_station_latitude     VARCHAR,  -- $10
    end_station_longitude    VARCHAR,  -- $11
    bikeid                   VARCHAR,  -- $12
    membership_type          VARCHAR,  -- $13
    usertype                 VARCHAR,  -- $14 Subscriber / Customer
    birth_year               VARCHAR,  -- $15
    gender                   VARCHAR,  -- $16 0=unknown 1=male 2=female
    _source_file             VARCHAR,
    _source_row              NUMBER,
    _loaded_at               TIMESTAMP_NTZ
);

CREATE TABLE IF NOT EXISTS WEATHER (
    raw            VARIANT,
    _source_file   VARCHAR,
    _source_row    NUMBER,
    _loaded_at     TIMESTAMP_NTZ
);