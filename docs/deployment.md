# Deployment and recovery

The default Compose stack runs one Flink session cluster and a MARS console.
It is a single-host setup, not a high-availability deployment.

## Network access

Console port 8080 and Flink port 8081 bind to `127.0.0.1`. The local SQL Gateway
is available only inside the Compose network. To reach an installation over SSH:

```bash
ssh -L 8080:127.0.0.1:8080 -L 8081:127.0.0.1:8081 user@your-server
```

Open `http://localhost:8080`. For shared access, put an HTTPS reverse proxy in
front of the console and set `MARS_SESSION_COOKIE_SECURE=true` in `.env`. Configure
request limits and login rate limiting at the proxy. MARS has no built-in login throttle.
Trust forwarded headers only from that proxy.

If the proxy runs on another host or in a container, explicitly choose a reachable
`MARS_CONSOLE_BIND_ADDRESS` and restrict that interface to the proxy. Binding to an
interface does not restrict which clients can connect; enforce source restrictions
in your network or Docker-aware firewall rules. Avoid exposing HTTP login traffic.

Flink REST and SQL Gateway access is privileged and is not protected by MARS login.
Keep them private. Disabling Flink web submission does not secure every REST endpoint.
Set `MARS_FLINK_UI_URL` if the browser-facing Flink address differs from
`http://<console-host>:8081`.

Existing installations that used all-interface port bindings must explicitly set
bind addresses before adopting this Compose file. Changing `.env` requires
recreating the affected service; rebuilding an image alone does not apply it.

## Configuration

See [`.env.example`](../.env.example) for Compose-supported options. The backend also
accepts `MARS_` environment variables defined in
[`settings.py`](../backend/app/settings.py); add those to the console's Compose
`environment` block when needed. Merely placing an arbitrary backend variable in
`.env` does not pass it into a container.

The main stack uses fixed container names and a single TaskManager. Do not use
`--scale taskmanager` with it. Register a separate cluster under **Cluster** when
jobs need a different execution target; see [remote targets](../remote-target/README.md).

## Accounts and automation

Manage users and tokens in **Settings → Accounts**. Administrators manage the
installation; editors can define and execute jobs; viewers can read definitions
and job state. Editors must be trusted with the data and network access of the cluster.

Recover a lost administrator password locally:

```bash
docker compose exec console python -m app.admin reset-password admin
```

For API automation, issue a token in Accounts and send it in the
`Authorization: Bearer <token>` header. API username/password Basic Auth is not
supported. Never place tokens in URLs or commit them to scripts.

## Backups

**Settings → Backup** exports definitions as YAML and supports a dry-run import.
An export excludes the secret store, users, and run history. SQL, descriptions,
and endpoint URLs are copied as entered: review exports for inline credentials
and private data before sharing them.

A full recovery also needs the `console-data` volume and Flink state. The console
volume holds both `mars.db` and `secret.key`; anyone with both can decrypt stored
credentials. Protect backups as credentials. Losing the key makes those secrets
unrecoverable. Keep the key with its matching database when restoring.

For a consistent file backup, stop the console first, copy its volume using your
backup tooling, then restart it. This pauses MARS scheduling and monitoring; Flink
jobs continue. Capture Flink savepoints separately before cluster maintenance and
verify a restore in an isolated environment. Never use `docker compose down -v`
as an upgrade step: it deletes persistent volumes.

## Released images

Every merge to `main` builds the console and Flink images once, scans them with
Trivy, and pushes them to GHCR as `ghcr.io/devinmb/mars-console` and
`ghcr.io/devinmb/mars-flink`, tagged `sha-<commit>`. A release with fixable high or
critical vulnerabilities is not pushed. The Flink image contains the connector
JARs from the image pinned in `flink/connectors.image`.

To run a released image instead of a local build, pin it by digest in `.env`:

```bash
MARS_CONSOLE_IMAGE=ghcr.io/devinmb/mars-console@sha256:...
MARS_FLINK_IMAGE=ghcr.io/devinmb/mars-flink@sha256:...
```

A digest names exact image contents, so what runs is what was scanned, and a
rollback is the previous digest. Unset, both fall back to the locally built
`mars/console:0.1.0` and `mars/flink:0.1.0`. The console reads connector manifests
from `flink/jars/`, so keep that directory in step with the Flink image you pin.

## Recovery and failover

Flink saves a job's state in two ways:

| | Checkpoint | Savepoint |
|---|---|---|
| Taken | Automatically, every 30s in the bundled configuration | When you choose **Stop and save state** |
| Purpose | Recovering from failures | Planned stops: upgrades, config changes |
| Kept | Superseded ones are deleted | The newest 3 per job ([retention](#savepoint-retention)) |

**Resume** and the scheduler's supervisor mode restore from the newest of the two.
MARS records each running job's latest checkpoint location as it reconciles, so the
location survives even if Flink forgets the job. If a restore from a checkpoint
fails before the new run completes a checkpoint of its own, that checkpoint is
skipped and the next attempt uses the savepoint instead. **Start fresh** ignores
both.

What happens when something fails:

- **A TaskManager fails.** Flink restarts the job's tasks from the last checkpoint
  by itself. MARS shows the run as *restarting* while this happens.
- **A job exhausts its restart strategy.** It stays failed. With a supervisor
  schedule, MARS resubmits it from the newest restore point.
- **The JobManager restarts.** The default stack does not configure Flink high
  availability, so every running job is lost. MARS marks those runs failed;
  supervised jobs are resubmitted from their recorded checkpoints, others wait
  for you to resume them. For automatic JobManager failover, configure
  `high-availability.type` (ZooKeeper or Kubernetes) and
  `high-availability.storageDir`.

Resuming replays input after the restored checkpoint. The amount depends on its
age and how much input was processed afterward. Idempotent sinks or transactional
exactly-once sinks can prevent duplicate effects; other sinks may write duplicates.

The bundled `flink/conf/config.yaml` sets `state.checkpoints.num-retained: 2`.
Keeping two checkpoints reduces the chance that Flink deletes the location MARS
last recorded between reconciliation polls; it does not guarantee availability.

**Known limitation:** a slow stop or move can time out while Flink continues
writing its savepoint. Flink may then stop the job, and supervision can restart it
using stale recorded state. Overlapping savepoint requests are also not yet
reliably excluded. Check the actual job state and completed savepoint in Flink
before retrying. These are the first priorities in the
[roadmap](../ROADMAP.md#next-operational-reliability).

### Savepoint retention

Flink never deletes a savepoint, and MARS takes one at every planned stop, so
without cleanup they accumulate for good. MARS keeps the newest
`MARS_SAVEPOINTS_KEEP` per job (3 by default) and, once an hour, asks Flink to
remove older ones. Flink does the deleting, so this works the same for local
disk, a shared mount or object storage. Whatever the count, MARS never removes
the state a job would resume from or the savepoint its latest run started from.

A removed savepoint stays in the job's history, marked as removed, and is no
longer offered for resuming. Savepoints MARS did not record, such as one taken
by hand in Flink's own tools, are left alone. Set `MARS_SAVEPOINTS_KEEP=0` to
keep everything. Prometheus counts removals in `mars_savepoints_removed_total`
and failures, retried the next hour, in `mars_savepoint_removal_failures_total`.

Changing Flink configuration restarts the JobManager, so plan it as maintenance:

1. **Stop and save state** for each running job, and wait until each shows a new
   savepoint.
2. Edit the configuration file in place. It is bind-mounted as a single file, and
   editors that write a new file and rename it leave containers reading the old one.
3. Run `docker compose restart jobmanager taskmanager sql-gateway`. `up -d` does
   not pick up changed file contents.
4. **Resume** each job and confirm it restored from the savepoint taken in step 1.

## Job moves between clusters

Optional. With two or more clusters, a job can stop on one and resume on another
where it left off, which is also how a cluster can be upgraded without stopping
everything. It needs both clusters to keep savepoints in one shared place.
Checkpoints stay on each cluster's own disk: they are written every few seconds,
and a network share that stalls would fail checkpoints and, by default, the jobs
taking them.

Each cluster other than the default shows **Job moves** on its card:

- **Not set up**: the normal state. Jobs can still be placed on any cluster; one
  that changes cluster just starts without its state.
- **Ready**: a check passed, and both clusters still save to that place.
- **Not working**: it passed once, and since then a check failed or a cluster's
  savepoint location changed. A move would fail until it is fixed or turned off.

MARS cannot change a cluster's containers itself (the console has no access to
Docker), so **Set up** and **Turn off** are guided steps it then verifies. The
state is worked out from the check and what each cluster reports, never stored
as a switch, so it cannot claim something the clusters do not do.

The check proves sharing rather than trusting the configuration: a small batch
job on each cluster writes a random token into the savepoint folder and the other
reads it back, in both directions. Matching folder names prove nothing (every MARS
cluster defaults to `file:///flink-state/savepoints`, each on its own disk). It
needs one free task slot on each cluster for a few seconds, and leaves a few-byte
`mars-storage-check` folder behind.

### Moving a job

On a job's page, **More → Move to cluster…** lists the other clusters and, for
each, whether the job can go there now: job moves ready between the two, the
destination reachable with a free task slot, and a compatible Flink version
(the same version or a newer destination, never an older one). Nothing
is stopped until those pass. A running job is then stopped with a savepoint,
pointed at the destination and resumed there from that savepoint; if the
destination cannot start it, MARS points it back and resumes it where it was,
from the same savepoint. A stopped job only changes cluster, and only if the
state it would resume from is on the shared storage.

The job is stopped while its state is written and then read back, so the pause
grows with its state. The move panel shows the state size (from the latest
checkpoint) and the expected pause. Every savepoint MARS takes records its size
and how long it took, and the median speed of recent large ones becomes the
estimate; until there are some, 50 MB/s is assumed. How long MARS waits for a
savepoint scales the same way, up to 12 hours. This estimate does not yet account
for checkpoint delays caused by backpressure, so a savepoint can still outlast
the wait; see the [recovery limitation](#recovery-and-failover). For jobs with
large RocksDB state, the
**native savepoint format** (offered for state over 1 GB, and in bulk actions)
copies the state files instead of re-serializing every key: much faster, but
restorable only with the same state backend.

To move several, tick them on the Jobs page (the box in the header selects every
job shown, so search or filter first) and choose **Move to cluster…** in the bar
that appears. The same bar stops or resumes the selected jobs.

The console runs a bulk action itself, one job at a time, so it carries on if the
page that started it is closed. The Jobs page shows it, with each job's result,
to anyone who opens it; one runs at a time, and **Stop after this job** halts it
between jobs. A move stops at the first job that cannot move, which is left where
it was; stops and resumes carry on past a failure. If the console restarts
mid-way, as during a deploy, it picks the batch up again: each step checks the
job's state first, so a job already moved counts as done and one stopped
mid-move is resumed on the destination.

Changing **Runs on** in the editor is refused while a job is running: MARS would
then ask the new cluster about it, hear that it does not exist, and mark it
failed while it kept running on the old one.

### Upgrading one cluster at a time

With job moves ready, **Clusters → Upgrade one cluster at a time…** replaces the
maintenance window: empty one cluster, upgrade it, move every job onto it, then
upgrade the other. Each job pauses only for its own move. The guide starts with
whichever cluster has fewer jobs and works out the current step from where the
jobs are; the upgrades themselves are the usual image change on each machine,
which MARS shows but cannot run.

Moves in a batch are checked: the next job moves only once the last is running
and has completed a checkpoint on its new cluster (within three checkpoint
intervals, at least 90 seconds), and the batch stops at the first that has not.
A move onto a newer Flink version is allowed and noted; onto an older one it is
refused, because Flink does not restore a savepoint onto an older version.

### On an NFS share

1. Create a share every cluster's machine can reach, allowing each one's IP.
   Size hardly matters: [retention](#savepoint-retention) keeps a few per job.
2. On the Clusters page, choose **Set up** next to Job moves and enter the NAS
   address. MARS asks it which folders it shares (the NFS `EXPORT` call, the same
   as `showmount -e`), so you pick yours by name instead of typing its export
   path, which on UniFi is a long hidden one. For each cluster not yet on the
   share, the guide gives a `docker-compose.override.yml` to save next to that
   machine's `docker-compose.yml`. Compose reads it by itself.
3. Stop that cluster's jobs with their state saved, run the `docker compose up -d`
   line at the top of the file, resume the jobs, and press **Check**.

**Turning it off** for a cluster: move its jobs to the default cluster first
(their savepoints are on the share, which the cluster will no longer reach), then
delete its override file, restart it, and choose **Turn off**. MARS refuses while
a job there would still resume from the share.

The file mounts the share at `/flink-savepoints` on the JobManager and
TaskManager and sets `state.savepoints.dir` on the JobManager's command line
(`-D` and the setting as separate words). `FLINK_PROPERTIES` does not work here:
the image applies it by rewriting the configuration file, which MARS mounts
read-only. NFSv3 mounts use `nolock`; without it a host not running the lock
service has the mount refused, and Flink does not lock savepoint files. Older
savepoints stay where they were and still resume on their own cluster.

### On S3 or MinIO

Flink ships an S3 file system: set `ENABLE_BUILT_IN_PLUGINS=flink-s3-fs-presto-2.2.1.jar`
on the JobManager and TaskManager, pass `s3.endpoint`, `s3.path.style.access`
(for MinIO), `s3.access-key` and `s3.secret-key` with `-D`, and set
`state.savepoints.dir=s3://<bucket>/savepoints`. MARS has not been tested with
this yet; **Check** will say whether it works.

## Versions and updates

The console shows which release it runs (footer, and **Settings → Version &
updates**). Released console images carry their commit and build date. For Flink,
set `MARS_FLINK_REVISION` to the commit the image was built from; without it, the
pinned image is shown instead.

Checking for newer releases is off by default, because it asks GitHub once a day:

```bash
MARS_UPDATE_CHECK=true
MARS_UPDATE_CHANNEL=releases            # or main, to follow every merge
MARS_UPDATE_TOKEN_SECRET=github_read    # a MARS secret; only for a private repository
MARS_UPDATE_INSTRUCTIONS=               # e.g. ./deploy.sh {component} {commit}
```

When something newer exists, administrators see **Update available** with what
changed and how to update. The console never updates itself. Without
`MARS_UPDATE_INSTRUCTIONS`, the steps are generic Docker Compose ones; a Flink
update always says it needs a maintenance window, because every job on the cluster
stops while it is replaced. `{component}` is `console` or `flink`, `{commit}` the
full commit, `{short}` its first seven characters.

## Restore drill

A backup you have never restored is a guess. MARS can check its own on a schedule.
It is off unless enabled:

```bash
MARS_RESTORE_DRILL=true
MARS_RESTORE_DRILL_SCHEDULE=0 6 1 1,4,7,10 *      # default: quarterly, 06:00 UTC
MARS_RESTORE_DRILL_BACKUPS_DIR=/path/to/backups   # mounted read-only at /backups
```

Each run restores the newest `.tgz` or `.tar.gz` in the backups directory (each
holding `mars.db` and `secret.key`) into a scratch directory and checks that:

- the database opens and its schema is one this release can upgrade from;
- its jobs, catalog entries and users match the live console;
- every secret decrypts with the key in the backup;
- every running job's restore point exists in Flink's state volume. Only jobs on the
  local cluster are checked; jobs on other clusters keep their state on those
  machines and are reported as not checked.

With no archives in the directory, it tests a fresh snapshot of the live database
instead, which shows the data can be backed up but not that your backups restore.
The archives must be readable by the console's user (uid 10001).

Nothing is written outside the scratch directory and nothing touches the network.
Run it on demand with `docker compose exec console python -m app.admin restore-drill`.
The result is published as `mars_restore_drill_success` (1 or 0) and
`mars_restore_drill_last_run_timestamp_seconds`; both are absent while the drill is
off. To be told when a drill fails, alert on:

```yaml
- alert: MarsRestoreDrillFailed
  expr: mars_restore_drill_success == 0
```

## Monitoring

**Clusters → Resources** on each cluster shows what it has and what uses it, from
Flink's own metrics: per TaskManager, CPU load, slots used, heap (operators, and
state held by the hashmap backend) and managed memory (RocksDB and batch
sorting), plus the JobManager's heap; then each job on the cluster with the slots
it holds, its state size, its last checkpoint's duration and how busy its
busiest operator is, heaviest first. A job's own Diagnostics tab goes deeper:
backpressure, throughput and lag per operator.

`/healthz` checks the console process; `/readyz` checks default Flink reachability.
`/metrics` exposes Prometheus metrics including running and failed job counts.
These endpoints are unauthenticated, so keep them inside the same access boundary.
Flink's Prometheus reporter listens on port 9249 inside the container network.

Judge a job's health by checkpoint progress: the time since its last completed
checkpoint (`flink_jobmanager_job_lastCheckpointCompletedTimestamp`) should stay
under a few checkpoint intervals. Kafka consumer-group metrics do not work for Flink
jobs. Flink assigns partitions itself instead of joining a consumer group, so the
broker reports zero members and lag that may never move, however healthy the job
is. A source that produces in bursts also shows long stretches of zero input,
which is not a failure.
