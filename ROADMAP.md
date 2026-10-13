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

**Order agreed 2026-10-13:** the bugs that hurt a live move or upgrade come first, then World
of Buoys phase 3 (pairwise correlation, which is outside MARS). In order: (1) a move that times
out on its savepoint, (2) savepoints in progress visible, one at a time, (3) `deploy.sh`
reliability, (4) Version & updates per cluster, (5) the backpressure diagnostic, (6) moves in
parallel.

- **Correction: a move that times out on its savepoint.** On 2026-10-13, moving
  `buoys_hourly` (100 MB of RocksDB state, sink backpressured, checkpoints taking
  100–200 s) gave up waiting for its savepoint. Flink finished the savepoint 268 s
  later and stopped the job, but MARS did not record it, and the supervisor, still on,
  restarted the job on the old cluster. It tried the "latest" checkpoint, which Flink
  had already discarded, then fell back to a checkpoint from an earlier run, hours
  old and on a different state backend, which failed and kept restarting. Recovering
  it took a manual cancel, a Runs-on edit and a run from the savepoint's path.
  - Budget the savepoint from the job's recent checkpoint durations, not only its
    state size, and warn before starting when the job is backpressured.
  - Pause the job's supervisor for the whole move.
  - On giving up, keep watching the savepoint; when it lands, record it as the
    restore point and finish the move (or resume where it was, if the target is
    unhealthy), and say so instead of asking the user to.
  - "Latest" must never fall back to an earlier run's checkpoint. If the newest
    restore point is gone, stop and say so.
  - It happened again the same night (move to `default` ahead of a `mars-b` image
    upgrade, savepoint ~2 min late). The supervisor resubmitted on `mars-b` from
    `chk-126`, older than the savepoint that had just landed and already discarded,
    so the run failed. A slow, backpressured sink makes every move of that job hit
    this.
- **Version & updates, per cluster.** On 2026-10-13 the page did not get a Flink image
  onto `mars-b`. It shows one Flink version and one command
  (`deploy.sh flink <commit>`), and that command only replaces the console's own
  cluster, by a full maintenance window. That contradicts the page's own advice to
  upgrade one cluster at a time. Nothing told the user what to run on the other host.
  There, the image digest was pinned in `docker-compose.yml`, not in `.env`
  (`MARS_FLINK_IMAGE`) as the generated compose expects, and a placeholder `sed`
  corrupted it. Every attempt after that pulled `…@sha256:<old><NEW_DIGEST><NEW_DIGEST>`.
  - List every cluster with the Flink image it actually runs (from the cluster, not
    the console's config), and which ones are behind.
  - When there is more than one cluster, lead with the guided rolling upgrade and
    offer the single-cluster window only as the fallback.
  - For a remote cluster, give the exact, copy-ready commands with the real digest
    filled in: where the image is pinned, a replacement anchored on the whole image
    reference, then `docker compose pull && docker compose up -d`. Detect a compose
    file that pins the digest inline and say so.
  - Refuse to restart a cluster that still runs jobs. Say which jobs to move first,
    because without HA a restart drops them.
  - After the change, confirm from the cluster that the new image is running.
- **A savepoint in progress is visible, and only one at a time.** On 2026-10-13 the user
  stopped `buoys_hourly` with a savepoint, left the page, came back, and could not
  tell whether MARS was still saving its state. Meanwhile a second stop-with-savepoint
  arrived from the API. Flink rejected the overlap ("Checkpoint Coordinator is
  suspending", then "declined (tasks not ready)" while the job restarted), each failed
  stop restarted the job, and four savepoints failed in a row.
  - Show a stop or move in flight on the job and the Jobs page, from Flink's own
    checkpoint history rather than the browser session: savepoint started, elapsed
    against the expected time, subtasks acknowledged (e.g. 3 / 4, the sink last), and
    the outcome. It must survive a reload, another browser, and a console restart.
  - Refuse a second stop, move or savepoint while one is pending, and say who started
    the first and when.
  - When a savepoint fails, say whether the job is still running, and from which
    restore point it would resume.
  - The restore point must never silently become an older run's checkpoint. After
    these failures the job showed `a255cab…/chk-142`, more than three hours old and
    from an earlier run.
- **Moves in parallel, with all-or-nothing rollback.** A bulk move runs one job at a
  time and waits for each to complete a checkpoint before the next. On 2026-10-13,
  12 small jobs took 4 min 53 s each way (batches 8 and 9, about 24 s per job), mostly
  spent in health-check waits rather than downtime. The console already drives the
  batch server-side, so it can work on several jobs at once:
  - Stop-with-savepoint several jobs concurrently (bounded, e.g. 4 at a time, and by
    the destination's free slots). Submit each on the destination as soon as its
    savepoint lands, and watch all of them for RUNNING plus a completed checkpoint
    in parallel.
  - If any job fails its health check, back it out to the source from the same
    savepoint. Offer to roll back the rest of the wave, or the whole batch, so a
    cluster upgrade either completes or leaves everything where it started.
  - Keep jobs with large state or a slow savepoint (expected time from
    measured checkpoints, see the move-timeout correction) out of the parallel wave:
    run them alone, so one slow job doesn't hold up or time out the others.
  - Report per-job downtime and the batch total, as in the item above.
  - Check capacity before starting: a rolling upgrade empties one cluster into the
    other, so the destination needs a free slot for every job and enough managed memory
    for the RocksDB ones. Both clusters were sized alike on 2026-10-13 (16 slots, 2 cores,
    4 GB, 1.37 GB managed) for 14 jobs; say clearly when that stops fitting.
- **Backpressure diagnostic names the wrong operator.** On `buoys_hourly` the job page
  said "Backpressure at Source: buoy_observations_src → MiniBatchAssigner → (Calc,
  Calc, … Calc)" and "This operator is being held up by whatever it writes to.
  Throughput for the whole job is limited by it." The first half is right, the second
  is wrong: the source wasn't the bottleneck. The sink (`buoys_hourly_sink` Writer)
  was 100% busy and was the one limiting throughput.
  - Name the bottleneck: the most downstream busy operator that is not itself
    backpressured (high `busyTimeMsPerSecond`, low `backPressuredTimeMsPerSecond`).
    Say that it limits the job, and list the backpressured operators as its
    victims.
  - For a sink, say what it is waiting on (the external system), and point at the
    connector's own metrics where it has them (e.g. CouchDB conflicts and
    `couchdbRevCacheHits`).
  - Shorten operator chains: collapse repeats ("Calc ×10") instead of listing ten
    identical names.
- **`deploy.sh` must work every time, for anyone.** It failed for the user on
  2026-10-13 (symptom still to be recorded), and it ran cleanly for Claude minutes
  later on an empty cluster. Make it boring:
  - It only deploys the cluster on the host it runs on. Say so on the Version &
    updates page and in its usage text. It is not the way to upgrade `mars-b` (see
    the per-cluster updates item).
  - Pre-flight before anything stops: image pullable, `mars.env` writable, console
    ready, Flink healthy, no batch or savepoint in flight, enough free slots. Then
    print exactly what it will do (which jobs stop, for how long) and ask for
    confirmation unless `--yes`.
  - Fail with one clear line and a next step, never a bare `set -e` exit. Resume is
    automatic or one command.
  - Its deploy-history commits are never pushed: `dmb-flink-jobs` was 13 commits
    ahead of origin. Push them, or say why not.
  - Add a dry-run mode, and a CI smoke test against a throwaway compose project.
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
