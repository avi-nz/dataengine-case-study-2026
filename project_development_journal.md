# Citibike × NYC Weather: Project Development Journal

This is the case study for my internship interview at DataEngine (the prize for winning the 2026 Datathon). 
The question is how weather affects Citibike usage in NYC, and the pipeline has to be built with Snowflake and dbt Cloud.

# Choosing the Data

### Attempt 1: The Citibike portal
The brief links to the Citibike System Data portal, which is a bucket of zip files: yearly files for 2013–2023, 
monthly ones from 2024, plus Jersey City files. I was going to pick a year and download it, but that means pulling 
GBs onto my laptop, unzipping them, then uploading them all again to Snowflake.

### Attempt 2: The S3 paths
The brief also gives two S3 paths:
```
s3://snowflake-workshop-lab/japan/citibike-trips/
s3://snowflake-workshop-lab/weather-nyc
```
S3 is Amazon's file storage, and this bucket is public. Snowflake can point an **external stage** at it and read 
The files are straight into a table, so nothing has to go through my laptop.

The weather only exists in this bucket, so the trip data has to come from here too; the dates won't 
line up. (The `japan/` in the path is left over from a Snowflake workshop in Japan. It's still NYC data.)

What's in there:

| | Trips | Weather |
| --- | --- | --- |
| Files | 376 `.csv.gz` (~2 GB) | 61 `.json.gz` |
| Dates | June 2013 → June 2018 | 5 July 2016 → 25 June 2019 |
| Format | CSV, no header row | one JSON object per line |

So the only period with both is **5 July 2016 → 30 June 2018**, about two years. I'm still loading all the trips 
and will filter to that window later in dbt.

### Problems with the weather data
Looking through the weather files, I found a few things that will matter later (still need to confirm these in 
Snowflake once it's loaded):
1. There are **two locations** mixed together. About half the readings are NYC (lat 40.71, lon −74.01) and the 
other half are a point in upstate New York near Utica (lat 43.0, lon −75.5), roughly 300 km away. If I don't 
filter to NYC, I'll be mixing in the wrong weather.
2. Temperatures are in **Kelvin**.
3. The time is a **Unix timestamp in UTC**, but the trip times are NYC local time, so I'll need to convert before 
joining or every day will be off by 4–5 hours.
4. There are ~24 readings per day, so the weather needs to be grouped by hour or by day before it can be joined 
to trips.
5. `rain` and `snow` only show up when it actually rained or snowed. I'm assuming missing = 0.

# Setting up Snowflake

You write SQL in a workspace, and everything is organised as 
**warehouse** (the compute that runs queries) and **database → schema → table** (where the data lives). The two 
are separate, which means a warehouse only costs credits while it's running, and I can make it bigger for a heavy 
job without touching the data.

I split my SQL into `setup/` (anything that builds something, and is safe to rerun) and `exploration/` (queries 
where I'm just looking at the data). The setup files are numbered so the run order is obvious: the stages live in 
the schema, which lives in the database, so `02` breaks if `01` hasn't been run.

### 01: Warehouse, database, schema
```sql
USE ROLE SYSADMIN;

CREATE WAREHOUSE IF NOT EXISTS CITIBIKE_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS CITIBIKE;
CREATE SCHEMA   IF NOT EXISTS CITIBIKE.RAW;
```
I use `SYSADMIN` instead of `ACCOUNTADMIN` because you shouldn't build things with the all-powerful role. The 
warehouse is the smallest size and switches itself off after 60 seconds idle. `IF NOT EXISTS` means I can run the 
script twice without it breaking. `RAW` is where the data lands exactly as it comes out of S3.

#### Bug:
```
SQL compilation error: Database 'CITIBIKE' does not exist or not authorized. Your primary role ACCOUNTADMIN ...
```
I thought this meant Snowflake couldn't reach the S3 bucket, but this step doesn't touch S3 at all. The error 
says my role was `ACCOUNTADMIN`, which means the first line never ran. Turns out Cmd+Enter only runs the line 
your cursor is on 😂 so `CREATE SCHEMA` ran before the database existed. Run All fixed it.

### 02: File formats and stages
A stage tells Snowflake *where* the files are, and a file format tells it *how to read* them.
```sql
USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

CREATE FILE FORMAT IF NOT EXISTS CSV_TRIPS
  TYPE = CSV
  COMPRESSION = GZIP
  SKIP_HEADER = 0
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  NULL_IF = ('', 'NULL')
  EMPTY_FIELD_AS_NULL = TRUE;

CREATE FILE FORMAT IF NOT EXISTS JSON_WEATHER
  TYPE = JSON
  COMPRESSION = GZIP;

CREATE STAGE IF NOT EXISTS TRIPS_STAGE
  URL = 's3://snowflake-workshop-lab/japan/citibike-trips/'
  FILE_FORMAT = CSV_TRIPS;

CREATE STAGE IF NOT EXISTS WEATHER_STAGE
  URL = 's3://snowflake-workshop-lab/weather-nyc/'
  FILE_FORMAT = JSON_WEATHER;
```
The CSV settings are determined by the file format: there's no header, so `SKIP_HEADER = 0`. Station names are in 
quotes (`"Broadway & W 24 St"`), so a comma inside a name doesn't split the column. Empty fields become proper 
`NULL`s.

There are no credentials because the bucket is public. For a private bucket I'd use a storage integration, like we 
did in the datathon.

#### Bug:
```
Cannot perform STAGE LS. This session does not have a current database.
```
My exploration file ran `LIST @TRIPS_STAGE` without any `USE` lines. Each file in Snowsight has its own session, 
so the `USE SCHEMA` from file `02` doesn't carry over. Adding the three `USE` lines at the top fixed it (writing 
`@CITIBIKE.RAW.TRIPS_STAGE` in full would also work).

`LIST @TRIPS_STAGE` showed 376 files, which matches the bucket. You can also query the files directly with 
`$1, $2...` before they're in a table, which is handy for checking what the columns are.

# Loading the Raw Data

### 03: Raw tables
```sql
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
```
Every trip column is `VARCHAR` on purpose. If `tripduration` was a `NUMBER` and one row out of millions had 
`"N/A"` in it, the whole load would fail. As text, the load always works, and I can convert the types in dbt with 
`TRY_CAST`, where bad values become `NULL` and I can count them.

The `_source_file`, `_source_row` and `_loaded_at` columns let me trace any row back to the exact file and line it 
came from. The weather goes into one `VARIANT` column (Snowflake's JSON type) and gets unpacked in dbt, the same 
way we read the referral JSON in the datathon.

### Test load
Before loading all 376 files, I tried one:
```sql
COPY INTO TRIPS
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @TRIPS_STAGE
)
FILES = ('trips_2013_0_0_0.csv.gz');
```
It loaded 105,305 rows.

Then I ran the exact same thing again, and it loaded **0 rows**. Snowflake remembers which files it has already 
loaded into a table and skips them, so rerunning a load can't create duplicates. This was a real problem in the 
datathon: our scripts used `INSERT` with a new `UUID_STRING()` each time, so every rerun duplicated every row with 
new IDs.


### 04_load_raw.sql
With the test file working, I loaded everything. Before the load I scaled the warehouse up to `MEDIUM`, then back 
down to `XSMALL` straight after:
```sql
ALTER WAREHOUSE CITIBIKE_WH SET WAREHOUSE_SIZE = 'MEDIUM';

COPY INTO TRIPS
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @TRIPS_STAGE
)
ON_ERROR = 'ABORT_STATEMENT';

COPY INTO WEATHER
FROM (
    SELECT $1, METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @WEATHER_STAGE
)
ON_ERROR = 'ABORT_STATEMENT';

ALTER WAREHOUSE CITIBIKE_WH SET WAREHOUSE_SIZE = 'XSMALL';
```

Each size up doubles the cost per hour and the number of workers. Since the data is split over
hundreds of files, the workers can load them at the same time, so a MEDIUM warehouse costs 4x as much per hour
but finishes about 4x faster. Snowflake bills per second, so the total cost is roughly the same, and I get the data
much sooner. This only works because the load can be split up. One giant file wouldn’t speed up.

Results:
| Category | Rows | Files |
| --- | --- | --- |
| Trips | 61,468,359 | 376 |
| Weather | 57,894 | 61 |

I then ran the whole file again, and both loads said Copy executed with 0 files processed. The test file from
earlier `(trips_2013_0_0_0)` was skipped during the full load too, so it wasn’t loaded twice.

### Weather data findings
Once the weather was loaded, I went back through the problems I'd found earlier and checked each one in SQL.

**1. Two locations.** Grouping by `raw:city.id` gives two cities:

| city_id | lat | lon | readings |
| --- | --- | --- | --- |
| 5128581 | 40.71 | −74.01 | 28,962 |
| 5128638 | 43.00 | −75.50 | 28,932 |

`5128581` is New York City. `5128638` is New York *State*, which is a point upstate about 300 km away. I'll filter 
on `city_id = 5128581` rather than the coordinates, because comparing decimals exactly is fragile and the ID is a 
stable identifier. Same lesson as matching on `TEAM_ID` instead of team names in my NBA project.

**2. Temperature is in Kelvin.** The range is 246–308. That can't be Celsius or Fahrenheit (both would be 
impossible weather), but in Kelvin it's −27 °C to 35 °C, which is a normal NYC year. To convert: °C = K − 273.15.

**3. Time is in UTC.** `raw:time` is a Unix timestamp. Converted, the NYC time is 4 hours behind UTC in summer and 
5 hours behind in winter due to daylight saving time. Instead of subtracting a fixed number of hours, I'll use 
`CONVERT_TIMEZONE('UTC', 'America/New_York', ...)`, which knows when the clocks change.

**4. ~24 readings per location per day.** The weather has to be grouped to an hour or a day before joining to trips.

**5. Rain and snow.** Each row is one reading, not one day, so a missing `rain` value means no rain was recorded 
for that reading. Comparing the weather label with the measured amount (NYC only):

| Label | Readings | Has rain amount |
| --- | --- | --- |
| Rain | 5,742 | 1,979 |
| Drizzle | 321 | 0 |
| Thunderstorm | 174 | 0 |
| Clouds | 9,034 | 65 |
| Clear | 9,122 | 48 |

Only about a third of `Rain` readings have an amount, and drizzle and thunderstorms never do. Some `Clear` and 
`Clouds` readings do have one, because the amount covers the period *before* the reading (it rained, then cleared). 
The amounts also come in two windows, `1h` and `3h`, so 2 mm could mean 2 mm in one hour or over three.

My definitions, all based on the weather label since it's on every reading (the amount is missing too often and 
mixes 1h and 3h windows):
* **Rainy hour:** the label is `Rain`, `Drizzle` or `Thunderstorm`
* **Snowy hour:** the label is `Snow`
* **Rainy / snowy day:** at least one rainy (or snowy) hour between 06:00 and 22:00, when people are actually 
riding. I also keep the number of rainy hours, so I can compare light and heavy rain days instead of just yes/no.

The rain amount is only used as a "how heavy" measure where it exists, converted to mm per hour so the `1h` and 
`3h` readings can be compared. The 06:00–22:00 window is an assumption for now, and I'll check it against when 
trips actually happen once the trip data is modelled.

