# dbt project: dataengine_case_study_2026

The transform layer of the Citibike × NYC weather pipeline. See the [main README](../README.md)
for the full architecture, findings and decisions.

```
models/
├── staging/        one model per raw table: types, renames, unit fixes, dedupe
│   ├── citibike/   stg_citibike__trips
│   └── weather/    stg_weather__observations
├── intermediate/   daily grain: int_trips__daily, int_weather__daily
└── marts/          fct_daily_trips_weather (what the dashboard reads)
```

Build everything and run all tests:

```
dbt deps
dbt build
```
