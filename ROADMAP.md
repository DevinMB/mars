# Roadmap

MARS focuses on making Flink SQL pipelines easier to build and operate.
This is a direction of travel, not a release schedule.

## Available

- SQL editing, validation, previews, and reusable catalog definitions.
- Streaming and scheduled jobs, restart supervision, and recovery from the newest savepoint or checkpoint.
- Multiple execution targets, activity history, and definition versioning.
- Role-based accounts, API tokens, encrypted secrets, and YAML import/export.
- Optional AI-assisted SQL drafting and schema registry integration.
- Versions and updates: what the console and Flink run, and, when update checks are
  on, what changed since and how to update.
- Guided cluster setup, on this machine or another, from the exact images in use.
- A catalog of tables: which jobs read and write each one, from Flink's plan, grouped
  by the topic or database it points at, and a pipeline view of the whole flow.
- Scheduled restore drills that check backups actually restore (opt-in).

## Next

- **Release readiness:** refine deployment guidance and repeatable installation checks.
- **Safer changes:** make definition differences and their effects clearer before applying them.
- **Recovery:** simplify backup, restore, and migration between installations.
- **Operations:** improve job diagnostics and visibility into resource use.
- **Rolling cluster upgrades:** upgrade Flink or connectors without pausing every
  job at once. A temporary second cluster starts on the new image, jobs move over
  one at a time (savepoint, resume on the new cluster), and the old cluster stops.
  Needs savepoint storage shared by both clusters and a move-job action. Each job
  pauses for seconds instead of the whole pipeline for a maintenance window.
- **Data flow, continued:** set each job's consumer group automatically, warn when two
  jobs share one, and optionally merge catalog entries that describe the same topic.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations.
- External identity providers for shared installations.
- Renaming a cluster. Jobs refer to a cluster by name, so a rename updates the cluster
  and every job that names it in one change; running jobs are unaffected.
