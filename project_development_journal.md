# Citibike × NYC Weather: Project Development Journal

# Background

This project is the technical case study for the final-stage internship interview at **DataEngine** (NZ data 
consultancy). The interview was the prize for winning the 2026 Datathon, where our team built an AI-assisted referral 
triage system for healthcare (Snowflake + AWS + an AI classification layer).

## The Brief
> *How does weather affect Citibike usage in New York City?*

The task is to:
* Design and build an **ELT pipeline** using **Snowflake** and **dbt Cloud**
* Ingest, transform and model two sources: **Citibike trip data** and **NYC weather data**
* Deliver insights showing any correlation between weather and trip volume
* Present the solution as you would to a client: assumptions, architecture decisions and the reasoning behind the insights

They evaluate five things:

| Criteria | What they're asking |
| --- | --- |
| Architecture | Is the pipeline logical, modular and scalable? |
| Data Modeling | Can raw data be turned into structured, useful business tables? |
| Data Integration | How well are the two datasets merged and related? |
| Assumptions & Communication | Are decisions well-reasoned and clearly explained? |
| Insight Delivery | Is the dashboard clear, actionable and story-driven? |

The brief says explicitly *"This is not about perfection — we're more interested in your approach."* That's a big 
part of why I'm keeping this journal: the reasoning behind each decision matters as much as the code.

## What I'm bringing over from the Datathon
Looking back at what won the datathon, a few things are worth repeating:
* **Problem first, tech second.** Our deck opened with the coordinators' bottleneck before showing any architecture.
* **Stating what we were NOT doing.** *"To streamline decision making, NOT to replace coordinators."* A clear scope 
statement makes the solution feel deliberate.
* **Simple flow diagrams** that a non-technical audience can follow.
* **A future work slide** that shows I know where the solution's limits are.

Some datathon technical patterns transfer directly: raw `VARIANT` tables with JSON path parsing, standardising two 
messy formats into one table, role-based access, and keeping warehouse costs down with auto-suspend.

There are also things I want to do *better* this time. In the datathon our transformations were hand-run `INSERT` 
scripts that generated a new `UUID_STRING()` on every run. Running a script twice duplicated every row. We also had no 
data tests, and some passwords sat in committed SQL files. dbt and the approach below are meant to fix all three.

---

# Phase 0: Understanding the Problem

## What is ELT? (and where my understanding was wrong)
My first mental model was: *"I write the ELT pipeline as a Python file, push the code onto Snowflake, and it runs 
there."* That turned out to be half right.

ELT stands for **Extract → Load → Transform**:
1. **Extract:** get the data from where it lives (S3 buckets)
2. **Load:** copy it into Snowflake *as-is*, still messy (the "raw" layer)
3. **Transform:** clean and reshape it *inside* Snowflake into useful tables

The older approach is ETL, where data is cleaned (e.g. in Python) *before* loading. ELT flips the order: load 
first, then use the warehouse's own processing power to transform. That's why this stack is SQL-heavy, not 
Python-heavy.

The correction: **the pipeline is not one Python file, and nothing gets "pushed onto" 
Snowflake.**
* **Extract + Load** are SQL commands run directly in Snowflake (stages + `COPY INTO`).
* **Transform** is a dbt project: a folder of SQL `SELECT` files in a Git repo. When dbt runs, it works out the 
order of the models, wraps each one in `CREATE TABLE ... AS`, and *sends* that SQL to Snowflake, which does the 
actual work.
* **Python** only appears at the very end, to display the finished tables.

This differs from the datathon, where `main.py` was in charge. It pulled data out of Snowflake, processed it in 
Python and wrote it back. That made sense there because the AI calls had to happen in Python. In this project dbt 
is in charge, and Python only presents results.

## Tool decision: Streamlit + Plotly instead of Power BI
DataEngine confirmed I could replace Power BI. I'm using **Streamlit + Plotly** instead because:
* Power BI Desktop is Windows-only and I develop on a Mac
* It lets me show Python skills alongside SQL/dbt
* The important rule still holds: **all transformation logic stays in dbt**. Streamlit only reads finished, 
analytics-ready tables and never processes raw data. Swapping the presentation layer doesn't weaken the core ELT 
requirements.

## The final architecture (planned)
```
S3 files ──(COPY INTO, SQL in Snowflake)──▶ RAW tables
                                              │
                          dbt Cloud sends SQL models to Snowflake
                                              ▼
                     STAGING (clean) ──▶ MARTS (business tables)
                                              │
                         Streamlit (Python) reads the marts
                                              ▼
                                      Interactive dashboard
```

---

# Phase 1: Choosing the Data

## Attempt 1: The Citibike portal
The brief links to the public Citibike System Data portal. It leads to a bucket full of zip files: yearly files from 
2013–2023, monthly files from 2024 onwards, plus separate Jersey City (`JC-`) files. Almost 20 GB in total.

My first thought was to pick a year and download it. But that would mean downloading ~GBs to my laptop, unzipping 
them and re-uploading everything to Snowflake. That's slow, and it skips the actual skill being tested.

## Attempt 2: The S3 paths in the brief
The brief also gives two direct paths:
```
s3://snowflake-workshop-lab/japan/citibike-trips/
s3://snowflake-workshop-lab/weather-nyc
```

#### What does "Direct S3 access via Snowflake external stage" mean?
* **S3** is Amazon's cloud file storage, like Google Drive for companies. `s3://...` is the address of a folder. 
This bucket is public, so anyone can read it.
* **An external stage** is a named pointer inside Snowflake to that folder. Snowflake reads the files 
*directly from S3 into a table*. Nothing passes through my laptop.

So the portal link is just there to credit where the data comes from. The S3 paths are what we actually use.

#### Why the S3 trip data and not the portal data?
The deciding factor is the **weather**. The weather data only exists in the S3 bucket, so whatever trip data I use 
must overlap with the weather dates. The newer portal data (2019–2026) also uses a completely different column 
layout and has no matching weather. That makes it a good *future work* item, not something to use now.

## What's actually in the buckets
Before setting anything up, I inspected the bucket contents:

| | Trips | Weather |
| --- | --- | --- |
| Path | `japan/citibike-trips/` | `weather-nyc/` |
| Files | 377 × `.csv.gz` (~2 GB compressed) | 61 × `.json.gz` (~2.7 MB) |
| Date range | June 2013 → June 2018 | 5 July 2016 → 25 June 2019 |
| Format | CSV, **no header row**, text in `"quotes"` | One JSON object per line (OpenWeather format) |

(The `japan/` in the path is left over from a Snowflake Japan workshop. The data is NYC.)

A sample trip row:
```
695,"2013-06-01 00:00:01.000","2013-06-01 00:11:36.000",444,"Broadway & W 24 St",40.7423543,-73.98915076,434,"9 Ave & W 18 St",40.74317449,-74.00366443,19678,"","Subscriber",1983,1
```

A sample weather record (with the very long `city` block removed):
```json
{"clouds": {"all": 92},
 "main": {"humidity": 99, "pressure": 982.46, "temp": 277.517, ...},
 "rain": {"3h": 2.37},
 "time": 1477174295,
 "weather": [{"description": "light rain", "main": "Rain"}],
 "wind": {"deg": 304, "speed": 4.76}}
```

### The analysis window
The analysis only works where **both** datasets exist:

**5 July 2016 → 30 June 2018** (about 2 years, i.e. two full summers and two winters)

Decision: I'll load **all** trip files into the raw layer anyway and filter to this window in dbt. That's the ELT 
approach: land everything raw and decide what to use during the transform. It also shows the pipeline can handle the 
full ~2 GB dataset.

## Data quality issues found during inspection
These came from exploring the weather files before building anything. I'll confirm each one in Snowflake once the 
data is loaded.

1. **The weather data contains two different locations.** Roughly half the readings are New York **City** 
(lat 40.71, lon −74.01). The other half are New York **State**, a point upstate near Utica (lat 43.0, lon −75.5), 
about 300 km away with very different weather. Joining without filtering would mix upstate weather into NYC's. 
**Must filter to the city coordinates.**
2. **Temperatures are in Kelvin** (246–308 K ≈ −27 °C to 35 °C). Convert to Celsius in staging.
3. **Weather time is a Unix epoch in UTC** (e.g. `1477174295`), while trip times are New York local time. Both 
must be in NY time before joining, or daily totals will be shifted by 4–5 hours.
4. **~24 readings per day per location.** Weather must be aggregated to an hourly or daily grain before joining 
to trips. Choosing that grain is the key modelling decision still to make.
5. **`rain` and `snow` fields only appear when it rained or snowed.** Assumption: a missing value means 0.

---

# Phase 2: Setting up Snowflake

## How Snowflake is organised
There is no "project" in Snowflake. In Snowsight (the web UI) you open a SQL file under **Projects → Workspaces** 
and the organisation lives inside Snowflake itself:
```
Account (my trial)
├── Warehouse   ← the ENGINE: compute that runs queries (costs credits only while running)
└── Database    ← the FILING CABINET: where data is stored
     └── Schema ← a DRAWER: groups related tables
          └── Table / Stage / View
```

The most important concept: **storage and compute are separate.** Data sits in a database whether or not a 
warehouse is running. A warehouse only costs money while it's executing queries, and it can be resized for a heavy 
job and shrunk again without touching the data.

## Project structure
I separated the SQL into two folders:
```
setup/          ← builds things. Part of the pipeline, rerunnable.
exploration/    ← only looks at things. Investigation, not pipeline.
```
**Rule:** pipeline files only contain steps that build something and are safe to rerun. Exploration queries go 
elsewhere. Then anyone reading the repo knows that running everything in `setup/` rebuilds the environment.

#### Why number the files (`01_`, `02_`...)?
1. **The number shows the run order.** Each file depends on the previous one: a stage lives in a schema, which 
lives in a database. So `02` fails if `01` hasn't run.
2. **The files sort in that order.** Files sort alphabetically, so the leading zero matters. Without it, 
`10_...` would sort before `2_...`.
3. **It's an industry convention.** Database migration tools like Flyway number their scripts (`V1__`, `V2__`) 
for exactly this reason.

## Step 1: Warehouse, Database, Schema
`setup/01_warehouse_database_schema.sql`
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

| Line | Why |
| --- | --- |
| `USE ROLE SYSADMIN` | `ACCOUNTADMIN` is the all-powerful role. Building objects with it is like working as `root`. `SYSADMIN` is the role meant for creating objects. |
| `XSMALL` | Start with the smallest, cheapest engine and only scale if needed. |
| `AUTO_SUSPEND = 60` | Turns off after 60 s idle so idle compute doesn't burn credits. |
| `AUTO_RESUME = TRUE` | Wakes automatically when a query arrives. |
| `IF NOT EXISTS` | Safe to run twice. The script is **idempotent**. |
| `CITIBIKE.RAW` | Where data lands exactly as it comes from S3. dbt will create its own schemas for the cleaned layers later. |

### Bug: `Database 'CITIBIKE' does not exist or not authorized`
```
SQL compilation error: Database 'CITIBIKE' does not exist or not authorized. Your primary role ACCOUNTADMIN ...
```
My first thought was that Snowflake couldn't access the S3 bucket. That was wrong on two counts:
* `CITIBIKE` isn't the S3 folder. It's the empty database I'm *creating* inside Snowflake. This step doesn't touch 
S3 at all.
* The clue was *"Your primary role **ACCOUNTADMIN**"*. If the whole script had run, the first line would have 
switched me to `SYSADMIN`.

**Cause:** In Snowsight, **Cmd+Enter only runs the statement the cursor is on.** I'd only run one line, so 
`CREATE SCHEMA` ran before `CREATE DATABASE` ever had. Clicking **Run All** fixed it: `Schema RAW successfully created`.

## Step 2: File Formats and Stages
Snowflake needs two pieces of information to read a file:
1. **Where is it?** → a **stage** (a saved bookmark to a folder)
2. **How do I read it?** → a **file format** (reading instructions)

Keeping them separate means a file format can be reused across stages, and both are stored as objects in Snowflake 
rather than hidden inside a script.

`setup/02_file_formats_and_stages.sql`
```sql
USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

-- How to read the trip CSVs
CREATE FILE FORMAT IF NOT EXISTS CSV_TRIPS
  TYPE = CSV
  COMPRESSION = GZIP
  SKIP_HEADER = 0
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  NULL_IF = ('', 'NULL')
  EMPTY_FIELD_AS_NULL = TRUE;

-- How to read the weather JSON
CREATE FILE FORMAT IF NOT EXISTS JSON_WEATHER
  TYPE = JSON
  COMPRESSION = GZIP;

-- Where the files live
CREATE STAGE IF NOT EXISTS TRIPS_STAGE
  URL = 's3://snowflake-workshop-lab/japan/citibike-trips/'
  FILE_FORMAT = CSV_TRIPS;

CREATE STAGE IF NOT EXISTS WEATHER_STAGE
  URL = 's3://snowflake-workshop-lab/weather-nyc/'
  FILE_FORMAT = JSON_WEATHER;
```

Every setting comes directly from what I found when inspecting the files. **Inspect first, then configure to match.**
* `SKIP_HEADER = 0`: the trip files have no header row, so line 1 is real data.
* `FIELD_OPTIONALLY_ENCLOSED_BY = '"'`: station names like `"Broadway & W 24 St"` are quoted. Without this, a 
comma inside a name would be read as a column break.
* `NULL_IF` / `EMPTY_FIELD_AS_NULL`: empty fields (`""`) become real `NULL`s instead of empty strings, which 
matters later for counts and tests.
* **No credentials on the stage**: the bucket is public. In a real client project I'd use a **storage 
integration**, a secure, password-free link to a private bucket. I built exactly that in the datathon 
(`REFERRAL_INTAKE_INTEGRATION` in Terraform).

### Bug: `This session does not have a current database`
```
Cannot perform STAGE LS. This session does not have a current database. Call 'USE DATABASE', or use a qualified name.
```
My exploration file ran `LIST @TRIPS_STAGE` without any `USE` lines. **Each Snowsight file runs in its own 
session**, so the context set in file `02` doesn't carry over. Snowflake didn't know which database 
`TRIPS_STAGE` was in.

Two possible fixes:
* **Set the context** at the top of the file with `USE ROLE / USE WAREHOUSE / USE SCHEMA` (what I did)
* **Use the fully qualified name**: `@CITIBIKE.RAW.TRIPS_STAGE`

**Lesson:** every file sets its own context, so it behaves the same no matter who runs it or what ran before. dbt 
always uses fully qualified names for the same reason.

### Exploration: looking before loading
`exploration/01_inspect_source_files.sql`
```sql
USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

-- 1. What files are there?
LIST @TRIPS_STAGE;
LIST @WEATHER_STAGE;

-- 2. Peek inside a trip file without loading anything
SELECT METADATA$FILENAME, $1, $2, $3, $5, $14
FROM @TRIPS_STAGE
LIMIT 10;

-- 3. Peek at a weather record
SELECT $1
FROM @WEATHER_STAGE
LIMIT 5;
```
`LIST @TRIPS_STAGE` returned **377 files**, matching the bucket inspection. Files in S3 can be queried directly 
with `$1, $2...` (column 1, column 2...) before they're in any table.

---

# Phase 3: Loading the Raw Data (the "L" in ELT)

## Design decisions for the raw layer

### Decision 1: Raw should match the source
Raw tables should match the source as closely as possible: no cleaning, no business logic. All of that happens in 
dbt, where it's tested and version controlled.

This led to loading every trip column as **`VARCHAR` (text)**, not as numbers or dates:
* If `tripduration` were declared a `NUMBER` and one row in tens of millions contained `"N/A"`, **the whole load 
would fail.**
* As text, **the load never breaks on bad data.** In dbt staging I'll convert types with `TRY_CAST`, which turns 
bad values into `NULL`, so they can be *counted and tested* instead of crashing the load.

### Decision 2: Track where each row came from
Every raw table gets three extra columns:
* `_source_file`: which S3 file the row came from
* `_source_row`: which line in that file
* `_loaded_at`: when it was loaded

If a strange value shows up later, I can trace it to the exact file and line. This is **lineage / auditability**. 
The `_` prefix marks columns I added rather than ones from the source.

### Decision 3: Weather goes into a single `VARIANT` column
The weather JSON is nested (and the `city` block contains a huge list of translations of "New York"). `VARIANT` is 
Snowflake's type for storing a whole JSON object as-is, which I'll unpack in dbt with path notation, the same 
technique as `raw:patient.demographics.age::INT` in the datathon.

## Step 3: Raw tables
The trip column names come from the Citibike data dictionary for this era of data. `$1` = trip duration (seconds), 
`$2` = start time, `$3` = stop time, `$5` = start station name, `$14` = user type (Subscriber / Customer).

`setup/03_raw_tables.sql`
```sql
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
```

## Test load: one file first
Before loading all 377 files, I tested with one.

`exploration/02_test_load.sql`
```sql
USE ROLE SYSADMIN;
USE WAREHOUSE CITIBIKE_WH;
USE SCHEMA CITIBIKE.RAW;

COPY INTO TRIPS
FROM (
    SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
           METADATA$FILENAME, METADATA$FILE_ROW_NUMBER, CURRENT_TIMESTAMP()
    FROM @TRIPS_STAGE
)
FILES = ('trips_2013_0_0_0.csv.gz');

SELECT COUNT(*) FROM TRIPS;
SELECT * FROM TRIPS LIMIT 20;
```
* `COPY INTO ... FROM (SELECT ...)` copies the file in and adds the three tracking columns at the same time.
* `FILES = (...)` restricts the load to a single file.

Result: the file loaded successfully (**TODO: add row count**).

### Running the same load twice
I then ran the exact same `COPY INTO` a second time. **It loaded 0 rows.**

Snowflake keeps **load metadata**: it remembers which files have already been loaded into each table and skips 
them. That makes rerunning a load **idempotent**: running it once or ten times gives the same result, with no 
duplicates.

This is exactly the problem we had in the datathon. Our standardisation scripts used `INSERT ... SELECT UUID_STRING()`, 
so every rerun added a full duplicate set of rows with brand-new IDs, and nothing could even detect the duplicates 
because the IDs were all different. Here, the tool handles it for me on the load side, and dbt will handle it on 
the transform side.

---

# Decision Log (quick reference)

| # | Decision | Why |
| --- | --- | --- |
| 1 | Snowflake + dbt Cloud + Streamlit/Plotly (not Power BI) | Approved swap; Mac development; transformation stays in dbt |
| 2 | Use the brief's S3 data, not the portal downloads | Weather only exists in S3; matching time range; no local downloads |
| 3 | Analysis window 2016-07-05 → 2018-06-30 | Only period where trips and weather overlap |
| 4 | Load all trips raw, filter in dbt | ELT principle: land everything, decide in the transform |
| 5 | Filter weather to NYC city coordinates | Dataset mixes NYC city and an upstate NY location |
| 6 | Separate `setup/` and `exploration/`, numbered files | Rerunnable pipeline vs investigation; clear run order |
| 7 | Build with `SYSADMIN`, not `ACCOUNTADMIN` | Least privilege |
| 8 | XSMALL warehouse, 60 s auto-suspend | Cost control; scale only when needed |
| 9 | Raw trip columns as `VARCHAR` | Loads never fail on bad values; typing happens in tested dbt models |
| 10 | `_source_file` / `_source_row` / `_loaded_at` on raw tables | Lineage: trace any row to its file and line |
| 11 | Weather as a single `VARIANT` column | Keep raw JSON intact; unpack in dbt |
| 12 | Test-load one file before the full load | Catch format issues cheaply |

# Open Questions
* What grain should trips and weather be joined at: **hourly or daily**?
* How should a day's weather be classified (e.g. "rainy day" = any rain? more than X mm?)
* How to handle confounders (season, weekday vs weekend) so comparisons are like-for-like

# Next Steps
* Load all 377 trip files, scaling the warehouse up for the load and back down afterwards
* Load the weather files
* Confirm the data quality issues (two locations, Kelvin, UTC) with SQL against the loaded data
