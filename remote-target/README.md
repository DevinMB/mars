# Running a target on another machine

A target is a Flink cluster MARS can send jobs to. Putting one on its own machine is
how "run this job over there" becomes literally true.

## Why a whole cluster, and not just a worker

The obvious idea is to start a TaskManager on the new machine and point it at the
existing JobManager. That works, and it does something different from what you
probably want:

| | Effect |
|---|---|
| Add a TaskManager to the existing cluster | **More slots.** The scheduler still places tasks in whatever slot is free, so you cannot say which machine a job runs on |
| Run a cluster on the new machine and register it as a target | **Placement.** A job names the target and runs there |

Flink has no supported way to pin a job to a machine inside one cluster. Slot
sharing groups control placement *within* a job; fine-grained resource management
controls slot *sizing*. Neither pins a job to a host.

So: if you only want more capacity and do not care where things land, add
TaskManagers to the cluster you have — `docker compose up -d --scale taskmanager=3`.
If you want to choose, run a cluster here.

The cost is honest: each cluster carries its own JobManager, roughly a gigabyte
before it runs anything. That is what placement costs.

## Deploying

```bash
# 1. Get the image onto this machine. Either push to a registry both can reach, or:
docker save mars/flink:0.1.0 | ssh newhost docker load

# 2. Copy this directory over and configure it.
scp -r remote-target newhost:~/mars-target
ssh newhost
cd mars-target && cp .env.example .env

# 3. Start it.
docker compose up -d
```

Confirm it is alive from the machine running MARS, not just locally:

```bash
curl -s http://newhost:8081/overview
curl -s http://newhost:8083/v1/info
```

## Registering it

In the console under **Cluster**, add a target:

| Field | Value |
|---|---|
| Name | something short and stable, e.g. `rack-2` — jobs reference it by name and it cannot be renamed |
| Flink REST url | `http://newhost:8081` |
| Gateway url | `http://newhost:8083` |
| Labels | optional, e.g. `zone=rack-2`, `profile=memory` |

Then pick it in a job's **Runs on** field. Jobs that name nothing keep running on the
default target.

## What has to be reachable

Only two ports, and only from the machine running the MARS console:

- **8081** — the Flink REST API, for job status and cancellation
- **8083** — the SQL Gateway, for submission

The cluster's internal RPC stays inside this machine's Docker network, so nothing
else needs opening. Note the ports carry **no authentication**: anyone who can reach
8081 can cancel jobs. Keep them on a trusted network, or put them behind something
that authenticates.

Whatever a job on this target reads or writes — Kafka, CouchDB, an API — must also be
reachable *from this machine*. A target is where the work happens, so connectivity is
judged from here, not from the console.

## Sizing

`conf/config.yaml` is a copy of the main cluster's, with 8 slots instead of 12.

- **Slots** bound how many jobs run at once. MARS jobs are typically many small
  pipelines rather than a few large ones, so err high.
- **TaskManager memory** bounds how much state a job here can hold. A sessionisation
  or windowed join needs more than a pass-through sink.
- Add workers within this machine with `--scale taskmanager=N`; add *machines* by
  deploying another copy of this directory and registering another target.
