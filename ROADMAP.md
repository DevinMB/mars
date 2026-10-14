# Roadmap

MARS focuses on making Flink SQL pipelines easier to build and operate.
This roadmap separates shipped capabilities from planned work; it is not a release
schedule. Last reviewed: **2026-10-14**.

## Available

| Area | Shipped capabilities |
| --- | --- |
| Authoring | SQL editor, connector forms, validation, source samples, output previews, and optional AI-assisted drafting. |
| Catalog and data flow | Reusable table definitions, schema registry integration, topic/database grouping, read/write relationships, and an interactive pipeline map with external systems. |
| Job operations | Streaming and scheduled batch jobs, restart supervision, run history, checkpoint and savepoint recovery, and savepoint retention. |
| Organization | Job tags, search, cluster and tag filters, activity history, definition versions, and YAML import/export. |
| Clusters | Guided cluster setup, job placement, resource diagnostics, shared-storage verification, stateful moves, and guided rolling upgrades. |
| Bulk actions | Server-managed move, stop, and resume batches, with progress that survives a closed browser or console restart. Moves currently run sequentially. |
| Administration | Administrator/editor/viewer roles, API tokens, encrypted secrets, optional update checks, Prometheus metrics, and opt-in restore drills. |

Stateful moves include pause estimates based on state size and measured savepoint
speed, optional native savepoints, and recovery to the source if destination
submission fails. Rolling upgrades check that each moved job is running and has
completed a checkpoint before moving the next. The reliability gaps below still
apply; these features do not make the default deployment highly available.

## Next: operational reliability

The priority order agreed on 2026-10-13 remains unchanged. These fixes come before
further pipeline work in the separate World of Buoys project.

1. **Recover moves that outlast their savepoint timeout.** Include recent checkpoint
   durations and backpressure in the wait budget, suspend supervision throughout a
   move, and track late savepoint completion. Record the resulting restore point
   and complete or recover the move without falling back silently to an earlier
   run's checkpoint.
2. **Make savepoint progress persistent and exclusive.** Show an in-progress stop
   or move across page reloads and console restarts, including elapsed time and
   acknowledged subtasks. Refuse overlapping state operations and report whether
   the job is still running and which restore point is usable after a failure.
3. **Make deployment tooling reliable.** Harden the companion deployment workflow
   (`deploy.sh`, maintained outside this repository) with preflight checks, a dry
   run, actionable errors, explicit host scope, and repeatable smoke tests.
4. **Show versions and update instructions per cluster.** Report the image each
   cluster actually runs, provide exact commands for that host, lead with rolling
   upgrades where possible, and verify completion. Block upgrades that would
   restart a cluster with jobs still running.
5. **Identify the actual backpressure bottleneck.** Distinguish a downstream busy
   operator from the upstream operators it blocks, shorten repeated operator
   chains, and surface relevant sink metrics.
6. **Move jobs concurrently with controlled rollback.** Use bounded parallel moves,
   check destination slots and memory before starting, handle slow or large-state
   jobs separately, and offer rollback of a wave or batch after a failed health
   check. Report per-job downtime separately from health-check time.

See the [implementation notes](docs/roadmap-notes.md) for incident evidence and
detailed acceptance criteria. In particular, a slow savepoint can currently finish
and stop a job after MARS has timed out; supervision may then select stale state.
Do not treat a timeout as confirmation that a job remained running.

## Following priorities

- **Clearer operational status:** a Jobs attention filter, data freshness, unknown
  versus healthy states, and current state size with sorting and move estimates.
- **More predictable maintenance:** stable upgrade plans with explicit operator
  and MARS steps, observed completion, and measured downtime in history and metrics.
- **Capacity planning:** more accessible resource details, state and checkpoint
  trends, and warnings before memory or slots run out.
- **Pipeline editing:** clearer controls for external systems, a list alternative
  to the map, optional merging of equivalent catalog tables, and owner/failure filters.
- **Safer authoring:** an explicit path from saved SQL to a running job, clearer
  definition differences, and validation retries when Flink is unavailable.
- **Release readiness and recovery:** repeatable installation checks, deployment
  guidance, and simpler backup, restore, and migration workflows.
- **Design follow-ups:** consistent cluster terminology, accurate export and
  upgrade wording, visibility of selected jobs hidden by filters, and clearer
  confirmations. The 2026-10-12 design review used synthetic data; validation
  against a live console with viewer access remains open.

## Later

- A CLI for reviewing and applying definitions in automated workflows.
- More connector and format integrations, including a Telegram long-polling source
  in the companion connector project, with credentials from MARS secrets and a
  single active poller per bot.
- External identity providers for shared installations.
- Job renaming that preserves history, schedules, and saved state, with clear
  treatment of automatically assigned Kafka consumer groups.
- Cluster renaming that updates job references without interrupting running jobs.
- External secret providers, starting with CyberArk and HashiCorp Vault, resolved
  at submission time.
