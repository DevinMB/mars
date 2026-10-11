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
- Bulk actions on the Jobs page: select jobs and move, stop or resume them; the
  console runs the batch itself, so it survives a closed browser or a restart.

## Next

- **Release readiness:** refine deployment guidance and repeatable installation checks.
- **Safer changes:** make definition differences and their effects clearer before applying them.
- **Recovery:** simplify backup, restore, and migration between installations.
- **Operations:** improve job diagnostics and visibility into resource use.
- **Moves for large state:** wait for a savepoint as long as the job's state needs
  instead of a fixed three minutes (today a large savepoint is reported failed while
  Flink is still writing it, then stops the job anyway), and show the expected pause
  before a move, from the job's state size and the speed of past savepoints.
  Optionally, native-format savepoints for RocksDB jobs, which copy state files
  instead of re-serializing every key.
- **Rolling cluster upgrades:** upgrade Flink or connectors without pausing every
  job at once. Shared savepoint storage and moving jobs are in place; what remains is
  the guided flow: start the second cluster on the new image, move jobs over one at
  a time with a health check after each, upgrade the first, move them back. Needs a
  deliberate exception to the same-Flink-version check, since savepoints restore
  forward across versions but not back.
- **Data flow, continued:** optionally merge catalog entries that describe the same
  topic; filter the pipeline map by tag or owner, or to only what is failing.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations.
- External identity providers for shared installations.
- Renaming a cluster. Jobs refer to a cluster by name, so a rename updates the cluster
  and every job that names it in one change; running jobs are unaffected.
