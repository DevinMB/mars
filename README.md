# MARS

**Stream pipelines for Apache Flink®.**

MARS is a self-hosted console for building and running Flink SQL jobs. Define where
records come from, where they go, and the statement that connects them — then run it,
schedule it, and see what it's doing. No Java, no JAR builds, no cluster expertise.

```bash
git clone https://github.com/DevinMB/mars.git
cd mars
cp .env.example .env
docker compose up -d
```

Then open **http://localhost:8080**. The first administrator's password is printed once
to the log:

```bash
docker logs mars-console 2>&1 | grep -A3 administrator
```

**If you missed it — or the container has since been rebuilt, which starts a fresh
log — reset it.** This needs no compose file and works from any directory:

```bash
docker exec mars-console python -m app.admin reset-password admin
```

---

## What you get

Four containers and nothing else to install:

| | |
|---|---|
| `jobmanager` | Flink 2.2.1, pinned. Web UI on `:8081` |
| `taskmanager` | 12 slots, sized for many small jobs rather than a few large ones |
| `sql-gateway` | How MARS turns SQL into running jobs |
| `console` | The API and the UI, on `:8080` |

## How it fits together

A **catalog entry** is one `CREATE TABLE` — a source or a sink. A **job** is the statement
that connects them. MARS replays the table definitions a job declares immediately before
running it, so the definitions survive the SQL Gateway's ephemeral sessions without
anyone running a metastore.

```
Catalog                          Job
┌──────────────┐                 ┌─────────────────────────────────┐
│ whispers_raw │  ──────────────▶│ INSERT INTO whispers_sink       │
│   (kafka)    │                 │ SELECT doc, kafka_key           │
└──────────────┘                 │ FROM whispers_raw               │
┌──────────────┐                 └─────────────────────────────────┘
│whispers_sink │◀────────────────────────────┘
│  (couchdb)   │
└──────────────┘
```

## Connectors

A connector appears in the console by shipping a **manifest** — a description of its
options — inside its JAR. The console reads the manifest and builds the form: field
groups, help text, which options are required, which are conditional, which are secrets.

**Adding a connector requires no change to MARS.** Drop a JAR containing a
`mars-manifest.json` into `flink/jars/`, rebuild, and it has a form.

Included out of the box: **Kafka**, **CouchDB**, **filesystem**, **datagen**, **print**.

To build your own, see [`mars-connectors`](https://github.com/DevinMB/mars-connectors) —
the `connector-sdk` module declares a manifest in Java and generates the JSON at build
time, so the two cannot drift.

## Secrets

Connection passwords never belong in a job's SQL: that text is listed, diffed, shown in
an editor and kept in version history. Store a secret under **Secrets**, then reference it:

```sql
'password' = '${secret:couchdb_password}'
```

The value is substituted only as the statement is handed to Flink. It is encrypted at rest
with a key generated into `/data` on first start, it is never returned by the API — not
even to an administrator — and it is scrubbed back out of Flink error traces, which
readily echo a connection string at you.

> **Back up `/data/secret.key`.** Lose it and stored secrets cannot be decrypted; they
> must be re-entered. That is deliberate — a recoverable key is one an attacker with your
> database can also recover.

## Running jobs on specific machines

A **target** is a Flink cluster MARS can send jobs to. Jobs name one, or name none
and use the default.

This is the only way placement works in Flink. A cluster's scheduler puts tasks in
whatever slot is free, and there is no supported way to pin a job to a machine
inside one cluster — slot sharing groups control placement *within* a job, and
fine-grained resource management controls slot *sizing*. So choosing where a job
runs means choosing which cluster receives it.

- **More capacity, don't care where:** add workers to the cluster you have —
  `docker compose up -d --scale taskmanager=3`.
- **Choose where:** run a cluster on the other machine and register it as a target.
  See [`remote-target/`](remote-target/).

To try it on one host first:

```bash
docker compose --profile second-target up -d
```

then add a target pointing at `http://jobmanager-b:8081` and
`http://sql-gateway-b:8083`.

## Scheduling

- **Keep it running** (supervisor) — if a streaming job stops or fails, MARS starts it
  again. Flink restarts a job's *tasks*; nothing in Flink restarts a job that has given
  up. It will not start a job that has never been run by hand.
- **On a schedule** (cron) — for batch jobs that read a finite input and finish.

Neither will start a second copy of a job that is already running.

## Pre-flight checks

Before a job runs, MARS flags the ways a stream job damages something other than itself.
These are advisory — each has a legitimate exception — but none should be hit by accident:

- A Kafka source whose consumer group doesn't start with `mars-`. If something outside
  MARS already uses that group, Kafka gives the partition to one consumer and the other
  **silently stops receiving records**. That is an outage, not a duplicate.
- A CouchDB sink using automatic document ids, which makes replays duplicate rather than
  upsert.
- Two jobs writing the same Kafka topic. Kafka appends rather than upserts, so everything
  downstream sees each record twice.
- A job reading and writing the same topic, which grows without bound.

## Administration

The CLI works directly against the database, so it works even when nobody can sign in.

```bash
docker exec mars-console python -m app.admin list-users
docker exec mars-console python -m app.admin reset-password admin
docker exec mars-console python -m app.admin create-user devin --role admin
docker exec mars-console python -m app.admin issue-token ci --name deploy
docker exec mars-console python -m app.admin revoke-token --name deploy
```

`docker exec` is used rather than `docker compose exec` deliberately: it needs no
compose file and so works from any directory. `docker compose exec` only works from
the directory holding `docker-compose.yml`.

> The bootstrap password appears **once**, in the log of the container that created
> it. Rebuilding the console replaces that container and its log, so treat the
> reset command above as the normal way to recover access rather than a last
> resort.

Roles are `admin` (everything, including secrets), `editor` (jobs and catalog), and
`viewer` (read-only).

For automation, send an API token as `Authorization: Bearer <token>`.

## Configuration

Everything has a working default; `.env` is optional.

| Variable | Default | |
|---|---|---|
| `MARS_CONSOLE_PORT` | `8080` | Host port for the console |
| `MARS_FLINK_UI_PORT` | `8081` | Host port for Flink's own UI |
| `MARS_DATABASE_URL` | SQLite in `/data` | Set to a Postgres DSN for multi-operator installs |
| `MARS_SESSION_TTL_HOURS` | `12` | How long a sign-in lasts |
| `TZ` | `UTC` | Affects cron schedules |

Flink itself is configured in `flink/conf/config.yaml` — slots, memory, checkpoint
interval, and state backend.

## Monitoring

The console exposes Prometheus metrics at `/metrics` (`mars_jobs_running`,
`mars_jobs_failed`), and Flink exposes its own on `:9249`. `/readyz` returns 503 when
Flink is unreachable, so an orchestrator can act on it.

## Development

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080

# frontend, proxying the API to :8080
cd frontend && npm install && npm run dev

# tests
cd backend && python -m pytest tests --ignore=tests/integration
```

Integration tests need a running stack and a reachable CouchDB; see
`tests/integration/`.

## Licence

To be decided before the first public release.

---

MARS is not affiliated with or endorsed by the Apache Software Foundation. Apache Flink®
is a registered trademark of the ASF.
