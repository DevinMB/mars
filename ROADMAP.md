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
  by the topic or database it points at, and a pipeline map you can drag around and
  focus on one flow or cluster.
- A consumer group of its own for each job reading a Kafka table, unless one is set.
- Scheduled restore drills that check backups actually restore (opt-in).
- Savepoint retention: the newest few per job are kept and older ones removed through
  Flink, never the one a job would resume from.
- Job moves between clusters (optional): shared savepoint storage set up and verified
  from the Clusters page, and Move to cluster on a job, which keeps its state and
  rolls back if the destination cannot start it.
- Moves sized to the job's state: the expected pause shown first, from measured
  savepoint speed; waits that scale with state; optional native savepoints.
- Rolling cluster upgrades: a guide that empties, upgrades and refills one cluster
  at a time, with each moved job checked healthy before the next.
- Bulk actions on the Jobs page: select jobs and move, stop or resume them; the
  console runs the batch itself, so it survives a closed browser or a restart.

## Next

- **Release readiness:** refine deployment guidance and repeatable installation checks.
- **Safer changes:** make definition differences and their effects clearer before applying them.
- **Recovery:** simplify backup, restore, and migration between installations.
- **Operations:** improve job diagnostics and visibility into resource use.
- **Data flow, continued:** optionally merge catalog entries that describe the same
  topic; filter the pipeline map by tag or owner, or to only what is failing.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations.
- External identity providers for shared installations.
- Renaming a cluster. Jobs refer to a cluster by name, so a rename updates the cluster
  and every job that names it in one change; running jobs are unaffected.
