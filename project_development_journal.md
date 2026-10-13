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

#### Bug (sort of):
Running `04_load_raw.sql` with Run All just printed `Statement executed successfully`. Snowsight only shows the 
result of the last statement, which was the `ALTER WAREHOUSE`. The `COPY` results were there, just hidden. Same 
with my check file: I only saw the last query. Running each statement on its own (Cmd+Enter, the thing that caused 
my very first bug 😂) showed everything.

That's also how I found out the file count was off. `LIST` showed 377 entries, but 
`COUNT(DISTINCT _source_file)` on the loaded table gave 376. The extra entry was the S3 folder itself, stored as an 
empty file. Lesson: count what actually landed instead of trusting the number I expected.

# Connecting Snowflake to GitHub

My SQL only existed inside Snowflake, which is a problem. The trial ends in 30 days and everything goes with it, the 
people reviewing this will look at GitHub, not my Snowflake account, and I can't rebuild the setup from scratch if 
the files aren't saved anywhere. Snowsight workspaces can sync with a Git repo, so I set that up instead of copying 
files across by hand.

Snowflake can't reach GitHub until an **API integration** allows it:
```sql
USE ROLE ACCOUNTADMIN;

CREATE API INTEGRATION IF NOT EXISTS GITHUB_INTEGRATION
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com/avi-nz')
  API_USER_AUTHENTICATION = (TYPE = SNOWFLAKE_GITHUB_APP)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION GITHUB_INTEGRATION TO ROLE SYSADMIN;
```
This is the one place I used `ACCOUNTADMIN`. Integrations are account-wide security objects and only admin roles 
can create them. `SYSADMIN` gets permission to use it, not change it. It only allows my own GitHub account, and it 
signs in with OAuth so there's no token to store.

#### Bug:
The first dialog I found was **Clone Git Repository**, which kept asking for a database and schema. That creates a 
read-only copy of the repo inside a database, which Snowflake can run files from but not push to. What I actually 
wanted was a **Git workspace** (Workspaces → Create → Git workspace), which is an editor that can commit and push.

#### Bug:
```
Failed to push to Git: ... Operation push is not permitted by server for origin 'https://github.com/avi-nz/dataengine-case-study-2026'.
```
In GitHub settings, `snowflakedb` was under **Authorized GitHub Apps** but not **Installed GitHub Apps**. 
Authorising lets the app act as me. Installing gives it access to specific repos. Reading had worked only because 
the repo is public. Installing the app on just this repo fixed the push.

# Setting up dbt

### A role and user for dbt
dbt Cloud connects to Snowflake like any other user, so I gave it its own identity with only what it needs:
```sql
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS TRANSFORMER;
GRANT ROLE TRANSFORMER TO ROLE SYSADMIN;

GRANT USAGE  ON WAREHOUSE CITIBIKE_WH TO ROLE TRANSFORMER;
GRANT USAGE  ON DATABASE  CITIBIKE    TO ROLE TRANSFORMER;
GRANT CREATE SCHEMA ON DATABASE CITIBIKE TO ROLE TRANSFORMER;

GRANT USAGE  ON SCHEMA CITIBIKE.RAW TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES    IN SCHEMA CITIBIKE.RAW TO ROLE TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA CITIBIKE.RAW TO ROLE TRANSFORMER;

CREATE USER IF NOT EXISTS DBT_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = TRANSFORMER
  DEFAULT_WAREHOUSE = CITIBIKE_WH;

GRANT ROLE TRANSFORMER TO USER DBT_SVC;
```
`SECURITYADMIN` this time because creating users and handing out permissions is security work, while `SYSADMIN` 
creates objects. dbt can read `RAW` but never change it, and it can create its own schemas for the models it 
builds. Granting `TRANSFORMER` to `SYSADMIN` means I can still see everything dbt creates. Without that, dbt's 
schemas would be invisible to my own role.

### Key pair authentication
A `SERVICE` user can't log in with a password, so dbt uses a key pair. I generated it on my Mac with `openssl`, set 
the public key on `DBT_SVC`, and pasted the private key into dbt Cloud. `DESC USER DBT_SVC` confirmed it:

| Property | Value |
| --- | --- |
| HAS_KEYPAIR | true |
| PASSWORD | null |
| RSA_PUBLIC_KEY_FP | SHA256:BhIv0/... |

The `ALTER USER ... SET RSA_PUBLIC_KEY` command isn't saved in the repo, only a comment saying the step exists. 
The datathon had a password sitting in a committed SQL file, and I didn't want to repeat that.

I then found an AI overview saying generating keys locally *isn't* best practice. Reading it properly, the real 
issue was the unencrypted private key left on my laptop afterwards, not where it was generated (Snowflake's own 
docs generate it locally). So I deleted the local `.p8`. The private key now only exists in dbt Cloud, and if I 
ever need another one, Snowflake gives each user a second key slot (`RSA_PUBLIC_KEY_2`) for rotating keys without 
downtime.

### The dbt Cloud project
* The dbt project lives in a `dbt/` folder, so the repo reads as `setup/` (load), `exploration/`, `dbt/` (transform).
* A **Development** environment builds into my own sandbox schema, `DBT_AVISHAI`. Later I'll add **Staging** 
(CI checks on pull requests) and **Production** (the real tables the dashboard reads) deployment environments.
* dbt Cloud locks `main`, so every change goes on a branch and gets merged through a pull request. This will make 
CI/CD easier to add later.
* `dbt debug` passed, so the connection, project and key all work.

I deleted the example models dbt creates and renamed the project from `my_new_project` to 
`dataengine_case_study_2026`. That name appears twice in `dbt_project.yml` and both must match, otherwise the model 
settings silently apply to nothing.

### Project structure and sources
The models are split into three layers:

| Layer | Job | Built as |
| --- | --- | --- |
| staging | Clean each raw table as-is: rename, cast types, fix units. No joins, no aggregating | view |
| intermediate | Reshape and combine, e.g. weather by hour | view |
| marts | Business-ready tables the dashboard reads | table |

Views store only the query, so they're free to build but rerun every time they're read. Tables store the result, 
so they're slower to build but quick to read. Staging is only read while dbt builds the next layer, while marts 
get hit by every dashboard click, so they should be tables. One worry: the trips staging view will sit on 61 
million rows, so it might need to be a table too. I'll measure that rather than guess.

The raw tables are declared as two **sources**, `citibike` and `weather`, because they come from two different 
systems even though they sit in the same schema. Models then use `{{ source('citibike', 'trips') }}` instead of 
`CITIBIKE.RAW.TRIPS`. The location is written once, and dbt's lineage graph starts at the raw tables. 
`dbt ls --resource-type source` listed both.

I also added the `dbt_utils` package (pinned to any 1.x version) for `generate_surrogate_key` and extra tests.

# Staging the weather: `stg_weather__observations`

Each weather finding became a line of SQL:

| Finding | In the model |
| --- | --- |
| Two locations | `where city_id = 5128581` |
| Kelvin | `raw:main.temp::float - 273.15` |
| UTC epoch time | `convert_timezone('UTC', 'America/New_York', to_timestamp_ntz(raw:time::int))` |
| Label is the reliable rain signal | `weather_condition in ('Rain', 'Drizzle', 'Thunderstorm') as is_rain` |
| Amounts in `1h` or `3h` windows | `coalesce(raw:rain['1h']::float, raw:rain['3h']::float / 3) as rain_mm_per_hour` |
| No ID column | `dbt_utils.generate_surrogate_key(['raw:city.id', 'raw:time'])` |

One assumption changed here. Earlier I wrote that a missing rain amount means 0. But two-thirds of `Rain` readings 
have no amount, so 0 would mean "it rained 0 mm", which is wrong. Missing means *unknown*, so it stays `NULL`. SQL 
averages skip `NULL`s, so the "how heavy" measure only uses readings that actually measured something.

The surrogate key is a hash of city + time, so the same reading gets the same ID on every run. That's the 
proper fix for the datathon's `UUID_STRING()` problem.

I added tests in `_weather__models.yml`: `unique` and `not_null` on the ID, `accepted_values` on `city_id` (only 
NYC should be left), `not_null` on the time and temperature, and `accepted_range` of −40 to 50 °C on temperature 
(if the Kelvin conversion were missing or done twice, this would catch it).

#### Bug:
`dbt build --select stg_weather__observations` failed on one test:

| Test | First run |
| --- | --- |
| `unique` observation_id | ❌ fail |
| `not_null` observation_id | ✅ |
| `accepted_values` city_id | ✅ |
| `not_null` observed_at_nyc | ✅ |
| `not_null` temp_c | ✅ |
| `accepted_range` temp_c | ✅ |

Some readings appear more than once. Before fixing it I wanted to know what kind of duplicates they were, because 
identical copies and copies that disagree need different fixes (`exploration/05_weather_duplicates.sql`, NYC only):

| Check | Result |
| --- | --- |
| Readings | 28,962 |
| Distinct times | 21,173 |
| Times with more than one copy | 7,747 |
| Times where the copies differ | 0 |

So 7,789 rows (about 27%) were extra copies, every copy is identical, and a few readings appear three or more 
times. Some copies come from the same file and some from different files. Since Snowflake never loaded a file 
twice, the duplicates are in the source data, not something my load caused.

The fix keeps one copy of each reading:
```sql
select * from renamed
where city_id = 5128581   -- New York City only; 5128638 is New York State
qualify row_number() over (partition by observation_id order by _source_file) = 1
```
I used `row_number()` instead of `select distinct` because copies from different files have different 
`_source_file` values, so `distinct` would keep both. Ordering by `_source_file` means the same copy wins every 
run. After this, all 7 (the model plus 6 tests) passed.

This also corrects the earlier "~24 readings per day". After removing duplicates it's 21,173 readings over about 
1,085 days, roughly 19.5 a day, so some hours have no reading at all. I'll need to decide what that means when I 
build the hourly weather.

Lesson: this is the third time checking the data changed an assumption (377 files, missing = 0, and now this). The 
failing test did its job. Without it, every duplicated reading would have been counted twice.

