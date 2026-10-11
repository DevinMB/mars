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
- **Guided cluster setup:** one name throughout ("cluster"), and an **Add cluster**
  flow that starts with where it will run. On the same machine: one command, with
  the form filled in. On another machine: a ready-to-copy compose file built from
  the exact images the existing cluster runs. Then a connection test that explains
  failures, a warning when clusters run different Flink versions, and a pointer to
  moving a job onto the new cluster.
- **Rolling cluster upgrades:** upgrade Flink or connectors without pausing every
  job at once. A temporary second cluster starts on the new image, jobs move over
  one at a time (savepoint, resume on the new cluster), and the old cluster stops.
  Needs savepoint storage shared by both clusters and a move-job action. Each job
  pauses for seconds instead of the whole pipeline for a maintenance window.
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
