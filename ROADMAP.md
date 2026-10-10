# Roadmap

MARS focuses on making Flink SQL pipelines easier to build and operate.
This is a direction of travel, not a release schedule.

## Available

- SQL editing, validation, previews, and reusable catalog definitions.
- Streaming and scheduled jobs, restart supervision, and recovery from the newest savepoint or checkpoint.
- Multiple execution targets, activity history, and definition versioning.
- Role-based accounts, API tokens, encrypted secrets, and YAML import/export.
- Optional AI-assisted SQL drafting and schema registry integration.

## Next

- **Release readiness:** refine deployment guidance and repeatable installation checks.
- **Safer changes:** make definition differences and their effects clearer before applying them.
- **Recovery:** simplify backup, restore, and migration between installations.
- **Operations:** improve job diagnostics and visibility into resource use.
- **Data flow:** treat catalog entries as tables rather than fixed sources or sinks.
  A Kafka topic is usually written by one job and read by others, so its role
  belongs to each job's use of it, not to the definition. MARS would derive who
  reads and writes each table from job SQL, show the jobs connected through
  shared topics as a pipeline, including producers and consumers outside Flink,
  and apply per-job settings such as consumer groups automatically. Existing
  entries keep working.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations.
- External identity providers for shared installations.
