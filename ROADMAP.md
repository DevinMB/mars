# MARS roadmap

Ordered roughly by when each becomes necessary rather than by appeal.

## Near term

- ~~Alembic migrations run on startup~~ **DONE**, and needed sooner than expected:
  adding a column to `jobs` brought the console up and then failed at the first query
  mentioning it, because `create_all` adds missing tables but never missing columns.
- **Savepoint-aware restarts.** Cancel-with-savepoint and resume-from-savepoint through
  the console. Supervisor mode currently resubmits from scratch, which is wrong for any
  job with meaningful state.
- **GitOps export/import.** Round-trip every catalog entry, job and schedule as YAML so a
  deployment can be reviewed and version-controlled outside MARS.
- **Connector health checks.** Manifests already declare `supportsHealthCheck`. Probing a
  connector's target *before* submitting turns "job restarts forever" into "this database
  does not exist" at the moment a user presses Save.

## Execution targets — running jobs on specific workers — **DONE**

Shipped. A target is a Flink cluster; jobs name one or get the default. Verified by
standing up a second cluster and confirming a pinned job ran there and nowhere else.

The notes below are kept because the reasoning still governs what comes next.

Worth being precise about what Flink actually offers, because "assign a job to a node" is
not a single switch:

| Mechanism | What it really controls | Fit |
|---|---|---|
| Slot sharing groups | Which *tasks within one job* share a slot | Not node placement |
| Fine-grained resource management | Slot CPU/memory profiles | Sizing, not placement |
| Separate session clusters | Everything: a job runs where it is submitted | **The practical answer** |
| Application mode | One JobManager + TaskManagers per job | Best isolation, heaviest |
| Kubernetes operator | Real `nodeSelector` / affinity / taints | Where true node-pinning lives |

In a single Flink session cluster, the scheduler places tasks in any free slot and there
is no supported way to say "this job belongs on that machine". So pinning is achieved by
choosing *which cluster* receives the job.

**Proposed design: an execution target is a first-class object.**

```
Target
  name            "default" | "heavy" | "gpu-box"
  flink_rest_url  http://jobmanager-a:8081
  gateway_url     http://sql-gateway-a:8083
  labels          {"zone": "rack-1", "profile": "memory"}
  default         bool
```

A job gains an optional `target` (falling back to the default), and submission routes to
that target's gateway. Everything already built stays put: the submitter takes a gateway
and a cluster client, so this is a lookup rather than a rewrite — the single hard-coded
pair in `deps.py` becomes a per-target pair.

That yields, in increasing order of effort:

1. **Several session clusters on one host** — a small one for light jobs, a larger one for
   heavy state. Immediately useful, no new infrastructure.
2. **Session clusters on separate machines** — each a target. This is the point at which
   "run this job on that node" becomes literally true.
3. **Kubernetes** — each target maps to a deployment with node affinity, and MARS gains
   real scheduling rather than routing.

Worth doing **before** there are many jobs: retrofitting a target onto existing jobs means
a migration plus a decision per job, whereas adding it while everything is `default` is a
nullable column and a dropdown.

Not blocking on the current single-cluster work, and nothing being built now forecloses it.

## Later

- **Multi-user in earnest.** Roles exist; per-job ownership and audit do not.
- **Alerting.** MARS knows when a job is restarting; it cannot yet tell anyone.
- **Metric history.** Checkpoint age and lag are read live and forgotten. A short rolling
  window would make "when did this start degrading" answerable.
- **Connector marketplace.** The manifest contract already allows third-party connectors;
  a signed, listed set is what makes that a platform rather than a convention.
