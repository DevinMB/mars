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
- **Versions and updates:** show which release the console and the Flink image are
  running, and when each was deployed. When a newer release exists, say so, with an
  expandable **How to update** panel: what changed, the exact steps for the
  installation's deployment method, and whether the update needs a maintenance
  window (the console updates without stopping jobs; Flink needs every job saved
  and resumed). The console only reports; it never updates itself, because that
  would require control of the host's container runtime.
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
