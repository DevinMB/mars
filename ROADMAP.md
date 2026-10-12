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
- Cluster resources: memory, CPU and slots per TaskManager, and each job's slots,
  state, checkpoint time and busiest operator, heaviest first.
- Job tags: group jobs by what they do; filter the Jobs page and the pipeline map by
  tag, and tag many jobs at once from the selection. Tags never re-version a job.
- Bulk actions on the Jobs page: select jobs and move, stop or resume them; the
  console runs the batch itself, so it survives a closed browser or a restart.

## Next

- **Release readiness:** refine deployment guidance and repeatable installation checks.
- **Safer changes:** make definition differences and their effects clearer before applying them.
- **Recovery:** simplify backup, restore, and migration between installations.
- **Downtime of each move, measured:** record and show how long each job actually
  stopped processing when it moved: from the savepoint being triggered on the old
  cluster to its tasks running again, state restored, on the new one. Shown per job in
  bulk-move results and the job's history, with the batch total, and exported to
  Prometheus. Separate from the health check that follows, which waits for a
  checkpoint while the job is already processing. (First rolling upgrade, measured by
  hand: median 3.6 s, at most 6.4 s per job, inside a 3½-minute batch.)
- **State size on the Jobs page:** each job's current state size (from its latest
  checkpoint) as a column, so the heavy jobs stand out at a glance, sortable, and
  pointing at the move-time estimate for large ones.
- **Operations, continued:** trends over time (state growth, checkpoint duration, busy
  ratio), and warnings before a cluster runs short of memory or slots.
- **Data flow, continued:** optionally merge catalog entries that describe the same
  topic; filter the pipeline map by owner, or to only what is failing.
- **Design review follow-ups.** A product and design review was completed on
  2026-10-12 (12 ranked findings, quick wins, journeys, mock-ups; kept outside the repo
  on the MARS host in `/root/mars-design-review/`). It is provisional: it used
  synthetic data, and a pass on the live console with a viewer sign-in is still to
  do. Its five biggest changes:
  1. One attention view: a "Needs attention" filter and counts on Jobs (failed jobs,
     repeated restarts, stalled checkpoints, unreachable clusters), saying when the
     data was last received and telling unknown apart from healthy.
  2. Maintenance as a stable plan: the rolling upgrade with fixed cluster order,
     "You" and "MARS" steps, completion only once observed, and the measured pause
     per job (the downtime item above).
  3. Pipeline as the place to maintain the flow: an "Add outside system" action and
     an editable panel when an outside node is selected, with a list alternative.
  4. Capacity within reach: Resources becomes a full-width "Resources & jobs"
     control naming memory, CPU, slots and the JobManager.
  5. Building a pipeline with an explicit step from saved SQL to a running job.
  Quick wins: the Resources control; upgrade wording that does not claim success
  early; export wording that does not promise "safe to commit"; showing selected jobs
  hidden by a filter; a retry when validation cannot reach Flink; slot wording;
  "Remove from map" with a confirmation; "clusters" instead of "targets" everywhere.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations.
- A Telegram source connector (bot API long polling), so a bot's messages are a Flink
  table. First use: replace the Python `whisper-consumer` (Telegram to the
  `whispererer-log` topic), keeping its message shape and key (chat title). Needs the
  bot token as a MARS secret, and exactly one running copy, since Telegram allows one
  poller per bot.
- External identity providers for shared installations.
- Renaming a job, keeping its history, schedule and saved state. Its automatic Kafka
  consumer group (`mars-<job>`) changes with the name, which only matters for a fresh
  start; a resume uses the offsets in its savepoint.
- Renaming a cluster. Jobs refer to a cluster by name, so a rename updates the cluster
  and every job that names it in one change; running jobs are unaffected.
- External secret providers: resolve `${secret:...}` from CyberArk (first) or HashiCorp
  Vault at submission time, instead of only MARS's own encrypted store, so credentials
  stay in the system an organisation already manages and rotates.
