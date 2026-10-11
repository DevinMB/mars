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
| Kept | Superseded ones are deleted | Until you remove it |

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

Resuming from a checkpoint replays up to one checkpoint interval of input. Sinks
with deterministic keys absorb that; append-only sinks such as Kafka without
exactly-once delivery write those records twice.

Flink keeps only the newest checkpoint by default. Setting
`state.checkpoints.num-retained: 2` in `flink/conf/config.yaml` ensures the
checkpoint MARS last recorded still exists, because MARS checks every 20s.

Changing Flink configuration restarts the JobManager, so plan it as maintenance:

1. **Stop and save state** for each running job, and wait until each shows a new
   savepoint.
2. Edit the configuration file in place. It is bind-mounted as a single file, and
   editors that write a new file and rename it leave containers reading the old one.
3. Run `docker compose restart jobmanager taskmanager sql-gateway`. `up -d` does
   not pick up changed file contents.
4. **Resume** each job and confirm it restored from the savepoint taken in step 1.

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
