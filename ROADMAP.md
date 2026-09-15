# MARS roadmap

Ordered roughly by when each becomes necessary rather than by appeal.

## Next up — resume here

Ordered. Each entry carries enough detail to start without re-deriving it.

### 1. Clean-room install test — **DONE**

**16 assertions, all passing, from a fresh clone against a nested daemon.**
`scripts/clean-room-test.sh` is the durable artifact; run it before a release.

It found a fifth defect the first round had missed, and a better diagnosis of the
first. A fresh install came up working but *silent* -- no connector list, no
"Application startup complete", and no administrator password, so the documented way
in returned nothing. The cause was not buffering (that fix was worth making but was
not it): alembic's `env.py` calls `logging.config.fileConfig`, which both disables
existing loggers and re-levels the root logger to WARNING from its ini. What made it
so hard to see is that `upgrade_to_head` returns early when the schema is current, so
alembic only runs on a **first install or an upgrade** -- exactly the run that prints
the generated password, and no other. Running in-process, alembic no longer touches
logging at all.

Two harness bugs also masqueraded as product bugs, which is worth remembering: nested
`sh -c` quoting ate the `-H 'Content-Type: …'` header, and `/api/connectors` needs a
session. A test that lies costs more than no test.

The first attempt ran on this host rather than a separate machine, and the two stacks
collided: the second deployment's TaskManager registered with the production
JobManager, the production console began resolving `jobmanager` to the wrong cluster
and started duplicate jobs, and rebuilding the shared image tag from a fresh checkout
(where `flink/jars/` is empty) replaced production's Flink image with one that had no
connectors. Roughly ten minutes of downtime. All four causes are fixed; the lesson is
that this test needs a daemon of its own.

**Venue: Docker-in-Docker.** A nested daemon shares no images, networks, volumes or
container names with the host's, which is exactly the class of failure above.

```bash
docker run -d --name mars-cleanroom --privileged --cpus 1.2 -m 9g \
  -e DOCKER_TLS_CERTDIR= -v cleanroom-docker:/var/lib/docker \
  docker:27-dind --storage-driver=overlay2
until docker exec mars-cleanroom docker info >/dev/null 2>&1; do sleep 2; done
# clone on the host, copy in, then run the four README commands inside
```

Cap the CPU: this host has two, and production Flink wants them. Remove the container
and the `cleanroom-docker` volume afterwards.

**What it must assert** — each of these is a regression test for something that was
actually broken:

- the console reaches "Application startup complete"
- **the generated admin password appears in `docker logs`** (the buffering defect)
- migrations run from empty to head, with no manual step
- `/healthz` and the UI both answer 200
- logging in with the printed password works
- the connector list is exactly what the README claims for a bare install
- after `scripts/build-connectors.sh`, `couchdb` appears in that list
- a source, a sink and a job can be created through the API and run to RUNNING
- **nothing on the host's daemon changed**: no new images, networks or containers

**Deliverable: `scripts/clean-room-test.sh`**, so this runs before every release
rather than once. A one-off test that found four defects will find a fifth.

### 2. Backup, restore, and export — **mostly done**

Export and import are built and verified: `GET /api/export` emits YAML with SQL as
block literals so it diffs a line at a time, and `POST /api/import` defaults to a dry
run. Round-tripping this installation reports all 30 definitions **unchanged**, which
is the check that matters -- an export that cannot be re-imported cleanly is not a
backup. Secret values are never exported; the file lists the names it needs.

The UI is in Administration: Export downloads the file; Import takes a file or pasted
text, shows exactly what would change, and only then offers to apply it. Overwriting is
off by default and confirmed by name and count.

Worth recording, because it changes how a team would use this: **the `.sql` files in a
jobs repository are a mirror, not a source.** Nothing in MARS reads them, so editing one
changes nothing, and they cannot express what a job needs beyond its statement — which
tables it declares, its schedule, its target, its type. The YAML export carries all of
that, which is what makes git-as-source-of-truth possible rather than decorative.

### Git as the source of truth, per environment

A button in a console is a hobby workflow; nobody at a company clicks Export on
production. The plumbing is right and the delivery is not. What changes it:

- **Ownership differs per environment, not per object.** Development authors in the
  console, because that is the better interface for figuring out what you want. QA and
  production are applied from git by CI and are read-mostly: run, stop, diagnose, but
  not edit. This resolves the drift problem more cleanly than marking individual
  objects as managed -- there is one answer per environment rather than one per row,
  and it matches how a change actually travels.
- **A CLI usable in CI**: `mars diff`, `mars apply -f defs/`, a token, a meaningful
  exit code. Thin over the API that exists; the import dry run is already the diff and
  already reports `updated` for everything that differs.
- **Per-environment targets.** The same definitions must land on different clusters.
  Secrets already work this way -- values are never exported, so each environment
  supplies its own -- but the target name is baked into a job and should be overridable.
- **Audit.** `JobVersion` records a note and a username; applied-from-git versions
  should record the commit.

Not urgent for a single-operator install, where the console is genuinely the better
interface. It is what a buyer's platform team will ask about on the first call.

**The original gap, for context:** Every job, catalog entry, schedule, target, user and
encrypted secret lives in one Docker volume, `mars_console-data`. Two consequences,
both worth stating to anyone who deploys this:

- Lose that volume and every definition is gone, with no way back.
- `secret.key` sits *beside* `mars.db` in it. The volume is both the only copy of the
  data and the means to decrypt it: losing it loses both, and copying it copies every
  credential in plaintext-equivalent form.

Build, in this order:

1. **Export** every catalog entry, job, schedule and target as YAML through the API.
   Deliberately excluding secret *values* — an export is a thing people mail around and
   commit. Export the `${secret:...}` references and let the import say which secrets it
   needs.
2. **Import**, with a dry run that reports what would be created, updated and skipped.
   Same guard rails as the editor: validate before writing.
3. **Document the volume backup** for the parts YAML cannot carry — the encryption key,
   run history, password hashes — and say plainly that the key is in there.

This is the GitOps item already on the list, promoted: the disaster case is more urgent
than the workflow, and the same round-trip serves both.

### 3. Preview a job's output before deploying

The other half of the sampling work. Sources can already be sampled; a whole statement
cannot. Most of the machinery exists: `gateway.select_rows` pages a streaming SELECT
with a time budget and cancels the operation afterwards, and `preview.py` already
rebuilds a table definition with a throwaway consumer group.

The work is turning `INSERT INTO sink SELECT ...` into a bounded `SELECT ...` and
showing the rows. Hazards already learned: use a throwaway group so a preview cannot
take partitions from the running job, cancel the operation on every path out because a
streaming SELECT holds a slot, and expect ten to thirty seconds before the first row
because Flink has to schedule the job.

### 4. Connector health checks

Manifests already declare `supportsHealthCheck` and nothing reads it. Probing a
connector's target when someone presses Save turns "the job restarts forever" into
"this database does not exist" at the moment the mistake is made. The CouchDB sink
already fails with exactly that at runtime — see the diagnostics trace naming
`CouchDbClient.checkDatabaseExists`.

---

## Near term

- ~~Alembic migrations run on startup~~ **DONE**, and needed sooner than expected:
  adding a column to `jobs` brought the console up and then failed at the first query
  mentioning it, because `create_all` adds missing tables but never missing columns.
- ~~Job diagnostics~~ **DONE.** A failing job used to show one truncated line, and
  diagnosing it meant leaving MARS for the Flink UI or `docker logs`. Each job now has a
  Diagnostics tab: checkpoint health judged against that job's own configured interval,
  per-operator backpressure and throughput, Kafka consumer lag, and the full stack trace
  with stored secrets replaced by their references.

  Two things that had to be got right, both of which produce a confident wrong answer:

  - Flink chains `Source -> Calc -> Sink` into one task, so the task-level record counters
    read 0 on exactly the jobs someone is most likely to be checking. The real counts are
    operator-level and have to be summed across subtasks.
  - A two-phase sink's committer emits one record per checkpoint whether or not any data
    moved, so the naive "busiest operator" reading reported an idle pipeline as steadily
    processing records. Committers are excluded from throughput.

- **Alerting stays in Grafana.** MARS exposes `/metrics`; Prometheus scrapes it and
  Grafana owns thresholds, routing and delivery. Building a second alerting system inside
  MARS would mean a second place to configure the same thing, and anyone running this
  already has somewhere alerts go. The console's job is to explain a problem once someone
  is looking at it -- which is what the Diagnostics tab now does.

- ~~Check the statement while it is being written~~ **DONE.** Validation existed but
  ran only against a *saved* job, from the job's detail page -- so MARS could tell you
  your job read and wrote the same topic, but only once you had written it, saved it and
  navigated away. The editor now checks on a pause in typing, marks the line, and shows
  the semantic warnings live.

- ~~Flink errors in plain language~~ **DONE.** "Non-query expression encountered in
  illegal context" is a typo; "doesn't support consuming update changes which is produced
  by node GroupAggregate" is an aggregate feeding an append-only sink. Both are precise
  and neither says what to change. Recognised failures are rewritten with a suggested
  fix, near-miss table and column names are offered, and Flink's own wording stays one
  click away. Unrecognised messages pass through untouched -- a translation layer that
  swallows what it does not understand hides the one error nobody anticipated.

  Every pattern was taken from a failure produced against this Flink version rather than
  written from memory: the wording changes between releases, and a table built from
  recollection quietly stops matching.

- ~~Delivery and producer/consumer settings~~ **DONE.** They were always available --
  Flink's Kafka connector passes anything prefixed `properties.` straight to the Kafka
  client, and adds `sink.delivery-guarantee` of its own -- but none of it was in the
  form, so reaching them meant hand-editing DDL. Delivery and Tuning groups now expose
  the guarantee, transactional id prefix, acks, compression, transaction timeout,
  linger/batch, poll size and isolation level.

  Where they come into play is worth stating, because Flink changes the usual answers:

  - **Offsets are not committed by the consumer.** Flink checkpoints them, so
    `enable.auto.commit` does nothing and `auto.offset.reset` is replaced by
    `scan.startup.mode`. The consumer group is used for reporting and for
    `group-offsets` startup, not for partition assignment in the usual sense.
  - **`acks` sits underneath the delivery guarantee rather than beside it.** Flink
    accepts `acks=0` with `exactly-once` without complaint; the producer then never
    learns whether a record arrived, so flushing at a checkpoint proves nothing. Now a
    danger-level warning, because nothing else reports it.
  - **Exactly-once is fenced by the transactional id prefix.** Two jobs sharing one abort
    each other's transactions and both stall. Now checked across jobs.
  - **Reading a transactional topic needs `read_committed`**, or the reader sees records
    from transactions that were later aborted. Now checked whenever a source reads a
    topic some exactly-once sink writes.

  Still missing: `transaction.timeout.ms` must exceed the checkpoint interval, which MARS
  knows per cluster and could check rather than only document.

- ~~See what is in a source~~ **DONE** for sources. The declared columns of every table
  are now listed beside the editor, and clicking one inserts it at the cursor. That alone
  is not enough here: eight of ten sources on this host carry an opaque JSON document in a
  single STRING column, so the declared schema reads `record_key, doc` and says nothing
  about what can be selected. "Look inside" reads a few real records and lists the fields
  found within the document, with an example value, inserting `JSON_VALUE(doc, '$.field')`
  on click.

  Every record sampled is inspected rather than just the first, because these documents
  are not schema-checked anywhere: the first real sample found `user_id` arriving as both
  a number and a string, which is exactly the thing worth knowing before writing a cast.

  Two hazards, both handled: a preview gets a throwaway consumer group and an explicit
  start position, so it can never take partitions from the job that owns the real group
  (verified: production offsets unmoved, no group left behind); and the operation is
  cancelled on every path out, because a streaming SELECT is a job holding a slot.

- **Preview a job's output before deploying.** The remaining half. Today
  a statement goes from the editor to production with nothing in between; the SQL Gateway
  can run a bounded SELECT, so the editor could show twenty real rows first. The same
  mechanism gives the Catalog a "peek at this source" -- five live messages from a topic
  -- which is how someone works out what to write in the first place.

- ~~Describe the job in words~~ **DONE.** A box above the editor takes a description and
  drafts the statement. Asked for the device-status conversion in one sentence, the model
  produced the production statement, character for character.

  What makes this workable rather than a novelty is that MARS can give the model real
  context and can check the answer:

  - The prompt is grounded in the tables actually ticked for the job, their columns, and
    -- for raw-passthrough sources -- the fields found by sampling a record. The model is
    told what exists instead of guessing at names.
  - References in the prompt autocomplete against those same tables and columns, so
    "@whispers_raw" and "@doc.username" are unambiguous rather than prose the model has to
    interpret.
  - The draft is validated before it is shown. `/api/jobs/validate` already compiles a
    statement and explains failures in plain language, so a draft that does not compile
    can be repaired and re-checked automatically.
  - **The draft always lands in the editor for a human to approve.** It is never
    submitted. That rule lives in the drafting module rather than the UI: it returns text
    and has no way to run anything.

  Amending an existing statement works the same way, with the current statement supplied
  so a small request stays a small change: "also uppercase the username" produced a
  one-line diff against a four-line statement rather than a rewrite. Nothing is applied
  until the diff is accepted -- a draft that silently replaced the editor would destroy
  work that was never offered up for changing.

  The repair loop is worth keeping. Asked for something Flink rejects -- sorting an
  unbounded stream -- the first draft failed, the plain-language explanation was fed back,
  and the second attempt compiled. An error message written for a person turns out to be
  at least as useful to a model.

- ~~Autocomplete in both boxes~~ **DONE.** One index of tables, columns and sampled
  document fields serves the SQL editor and the description box. In SQL a field inserts
  `JSON_VALUE(doc, '$.username')`; in prose the same entry inserts `@doc.username`, which
  is what the model is then told about. The description box only completes after an `@`,
  so ordinary prose is never interrupted.

  The list is anchored under the field rather than at the caret. Positioning at the caret
  inside a textarea means measuring text with a mirrored element, and it misplaces itself
  on wrapping and scrolling in ways that are worse than a list that is always in the same
  place. Worth revisiting alongside a real editor component.

- **Schema-aware completion.** MARS knows every table and column in the catalog, which
  Flink's own UI does not. Completing table names after FROM, then that table's columns,
  is the feature people expect from a managed service and cannot get self-hosted. Needs a
  real editor component; CodeMirror 6 rather than Monaco, for bundle size.

- **An MCP server over the existing API.** The pieces an agent needs are already built:
  the catalog describes every table, the manifests describe every connector option, and
  `/api/jobs/validate` lets an agent check its own work before a human sees it. Exposing
  that over MCP lets people build jobs from the tools they already use, without MARS
  shipping an LLM integration or paying for inference. The rule that makes it safe is
  that generated SQL lands in the editor for approval and is never submitted directly.

- ~~A configurable AI provider~~ **DONE.** One provider, set under Administration, used by
  every feature that needs a model: Ollama, Claude, or anything serving the OpenAI chat
  shape. Features ask for the configured model rather than carrying an endpoint, so
  switching backends is one change and everything follows.

  Three properties worth keeping as this grows:

  - **The credential is not a new mechanism.** An API key is a reference into the existing
    encrypted secret store, so it is handled exactly like a database password: encrypted
    at rest, never returned by the API, redacted out of error text.
  - **Off by default.** Until an administrator configures and enables a provider, every AI
    feature is inert and nothing is sent anywhere. Enabling Claude says plainly that
    prompts go to Anthropic.
  - **Testing checks the model, not just the host.** The usual misconfiguration is a model
    that is not pulled on the server; a bare ping would pass and the failure would appear
    only when someone first used it. Test lists what is there and suggests the near match.

- ~~Savepoint-aware restarts~~ **DONE.** "Stop and save state" writes a savepoint and
  stops; starting again resumes from it. Supervisor mode resumes rather than restarting
  from scratch, and cron jobs deliberately do not -- a bounded job is meant to start
  clean each time.

  Decisions worth keeping:

  - **The safe stop is the default action.** Discarding state is still one click away but
    has to be chosen, and says what will be lost.
  - **A failed savepoint leaves the job running.** Stopping a stateful job whose state was
    not saved is precisely the outcome this exists to prevent; doing it anyway and
    reporting an error afterwards would be worse than not trying.
  - **`execution.savepoint.path` must be set on the session before the statement that
    starts the job.** Flink reads it when the graph is submitted, so setting it afterwards
    silently does nothing and the job starts empty -- the exact failure this feature
    exists to stop, and one that looks like success.
  - **Drain is offered but not the default.** It advances the watermark to the end of time
    to flush pending windows, which is right when retiring a job and wrong when it is
    coming back, since event time cannot go backwards afterwards.

  Verified on the live `sit_sessionize`, which holds MATCH_RECOGNIZE state: stopped with a
  savepoint and resumed with `restored: 1`, running again in under three seconds.

  This also unblocks credential rotation, which needs a restart of whatever holds the old
  password.
- **GitOps export/import.** Round-trip every catalog entry, job and schedule as YAML so a
  deployment can be reviewed and version-controlled outside MARS.
- **Connector health checks.** Manifests already declare `supportsHealthCheck`. Probing a
  connector's target *before* submitting turns "job restarts forever" into "this database
  does not exist" at the moment a user presses Save.

## Identity

- **An acorn for the mark.** Flink's own logo is a squirrel, and a squirrel's acorn is
  the obvious companion: a small, self-contained thing that gets stored, kept and found
  again later, which is a fair description of a stream pipeline's state. It reads as
  deliberately paired with Flink rather than derivative of it. Worth drawing properly as
  a vector mark in the existing orange, keeping the current silhouette weight so the
  favicon still reads at 16px.

  One caution to respect: the association must stay visual. Flink is an Apache Software
  Foundation trademark, so the mark can nod to the ecosystem, but the *name* cannot imply
  endorsement -- "MARS, for Apache Flink®" stays the formulation.

- **The name, and whether it expands.** MARS is settled as a name. The backronym is not,
  and it should stay optional: Kafka, Flink, Grafana and Splunk all mean nothing, and the
  tagline carries the explanation instead. If one is wanted, the honest candidates
  describe the product rather than decorate it:

  | Expansion | Note |
  |---|---|
  | **M**anage **A**nd **R**un **S**treams | Plainest, and literally what it does |
  | **M**onitoring, **A**uthoring & **R**unning **S**treams | Maps to the actual tabs |
  | **M**anaged **A**ccessible **R**ealtime **S**treams | Most marketing-shaped |

  "Marsden" fits as the company or suite name above the product -- Marsden's MARS -- which
  is the usual way that wish gets granted without straining the acronym.

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

## External secret stores — CyberArk, Vault, cloud key managers

Requested so an organisation can keep credentials where it already keeps them, and
have them rotated on its own schedule rather than MARS's.

### What already fits

The design does not need changing to accommodate this. Job SQL holds a reference,
`${secret:couchdb_password}`, and the value is substituted only as the statement is
handed to the gateway — the stored text, every saved version and anything rendered
in the editor keep the placeholder. So where the value comes from is already an
implementation detail behind one call. `SecretStore.resolve` is the seam.

`SecretStore` becomes an interface with the current Fernet-in-SQLite
implementation as `LocalSecretBackend`, alongside one backend per external store.
External backends are **read-only from MARS**: the vault owns the value, and the
Secrets page becomes a browser rather than an editor when one is configured.

### What is actually hard: rotation

Fetching a rotated value is easy. Surviving one is not.

Resolution happens at submission, so a job **started after** a rotation picks up the
new credential with no help. A job **already running** does not: Flink baked the
credential into the table options when the job was submitted, and it holds that
value until it restarts. So a rotation silently breaks every running job that used
the old one, at whatever moment the old credential is revoked — which may be hours
later, and will look like an unrelated connector failure.

That is the feature, not a caveat to note in passing:

- MARS already knows which jobs reference which secret; the delete-guard computes
  exactly that today to refuse removing a secret still in use.
- So it can detect a changed value and **offer to restart the jobs that depend on
  it** — or do it automatically for jobs whose schedule says supervisor.
- Restarts should be savepoint-aware, which is why that item is listed above this
  one. Restarting a stateful job from scratch to pick up a password is a poor trade.

Anything that skips this ships a feature that appears to work and fails later,
somewhere else.

### Already done

The Secrets tab is administrator-only, and listing secret names stays available to
writers so the connector form can offer them. That split holds whatever backs the
store, and an external backend only narrows it further: with a vault configured, the
page becomes a browser rather than an editor for everyone.

### The rest of the design

- **Caching.** A vault round trip per statement is too slow and too noisy in the
  vault's audit log. Cache per secret with a short TTL, and treat a changed value as
  the rotation signal above.
- **MARS's own credential.** Reading a vault needs a credential, which cannot itself
  live in the vault. That is an AppRole, a machine identity, a Kubernetes service
  account, or a sidecar that injects a short-lived token — deployment-specific, and
  the README has to be honest that this is the one secret that stays outside.
- **Audit.** Vaults log who read what. MARS should pass the requesting identity
  through rather than presenting every read as itself, or the audit trail says only
  "mars" for everything.
- **The instance key.** `/data/secret.key` encrypts the local store. A vault could
  hold it instead, which removes the one file whose loss is unrecoverable — worth
  supporting even for deployments that keep using the local backend.

### Order of work

1. Extract the `SecretBackend` interface; keep the local store as the default. No
   behaviour change, and it is the only part that touches existing code.
2. One external backend end to end — HashiCorp Vault is the usual first, since it
   is easy to run locally for tests. CyberArk's Central Credential Provider and the
   cloud key managers follow the same shape.
3. Rotation detection and dependent-job restart, after savepoint-aware restarts
   exist.

Worth noting for sequencing: steps 1 and 2 are additive and could be done any time.
Step 3 is where the value is, and it depends on savepoints.

## Dark mode

A toggle, defaulting to the system preference.

**The leverage point is already there.** `index.css` defines `.card`, `.input`,
`.tbl`, `.btn-*` and `.eyebrow` as component classes, so most surfaces are described
in one file rather than scattered across markup. Moving their colours to CSS custom
properties — `--surface`, `--surface-raised`, `--text`, `--text-muted`, `--border` —
and redefining those under a `.dark` selector carries most of the interface without
touching a single component.

What does not come free:

- **Literal `slate-*` classes in pages.** They are everywhere and each is a decision
  that was made for a light background. These want auditing rather than a blanket
  `dark:` variant, which doubles every class and drifts the moment someone forgets.
- **Status colours.** The state pills lean on emerald, amber and red at 50-weight
  tints with 700-weight text. Those tints vanish on a dark ground; dark needs the
  relationship inverted — a dark tint with light text — and re-checked for contrast,
  because "running" and "restarting" have to stay distinguishable at a glance.
- **Orange on dark.** `brand-600` reads well on white and muddies against slate-900.
  The button and the accent rule likely want `brand-500`, which means the palette
  gains a per-theme mapping rather than one fixed choice.
- **Things already dark.** `CodeBlock` and the SQL editor gutter are slate-900 today
  because they sit on white. On a dark page they stop being distinct and need to go
  the other way, slightly lighter than the surface behind them.

**The implementation trap is the flash.** Reading the preference in React means the
first paint is the wrong theme and then corrects, which is uglier than not having the
feature. The class has to be on `<html>` before the bundle parses, which means a
small inline script in `index.html` that reads `localStorage` and falls back to
`prefers-color-scheme`. That script is the only part that cannot be tidy.

Scope note: three states, not two — light, dark, and follow the system. A toggle
that only flips between light and dark quietly overrides a preference the operating
system already expresses.

## Settle the name

`MARS` is fixed; the backronym is not. The current expansion, *Marsden Apache
Real-time Streaming*, has one problem worth solving before it reaches a licence
file or a landing page: **Apache** is itself an ASF mark, so an expansion that leans
on it is doing the thing the acronym was chosen to avoid. Dropping it removes the
concern entirely.

`M` is Marsden. Candidates for the rest, with what each claims:

| Expansion | What it says |
|---|---|
| Marsden **Adaptive Realtime Streaming** | Reads smoothly, claims little, hard to be wrong about |
| Marsden **Aggregation, Routing & Streaming** | Literally what the product does — it aggregates, routes jobs to targets and records to sinks, and streams |
| Marsden **Automated Realtime Streaming** | Emphasises that jobs run themselves once defined |
| Marsden **Applied Realtime Streaming** | Quiet and neutral; the weakest claim of the four |

*Aggregation, Routing & Streaming* is the most descriptive and the only one that
earns its words. *Adaptive Realtime Streaming* is the safest.

Decide before the first public commit, since the expansion lands in the README, the
page footer, the login screen and anything written about it. The acronym itself does
not change either way, so nothing in the code moves.

## Real accounts: email and single sign-on

Today an account is a username and a password held by MARS. That is the right amount
of machinery for one operator and too little for a team.

- **Email on an account**, which is the prerequisite for everything else: password
  reset without an administrator, notifying someone their job has been failing,
  saying who did what in a way that means something outside this one console.
- **Google sign-in**, then OIDC generally — Okta, Entra, Authentik. Worth building
  as OIDC once rather than Google specifically, since Google is simply one provider
  and every business buyer will ask for theirs.
- **Provisioning rules**, because SSO changes who creates accounts: does a first
  sign-in create one, and with which role? The safe default is that it does not, and
  an administrator invites instead.

Two things in the current design to revisit when this lands. Sessions are stateless
and signed, which is neat and means there is no server-side session to revoke on an
SSO logout — a short TTL covers it but is not the same thing. And the local password
path has to survive, because an identity provider being down must not lock everyone
out of the thing that runs their pipelines.

## Charging for it

Well past the current work, and recorded so the shape is not decided by accident.

**What to meter.** Slots are the natural unit: they are what a cluster actually
sells, what bounds how many jobs run at once, and MARS already counts them per
target and in aggregate. Jobs are a worse unit — a job that runs once a day and one
that pins a slot forever are not comparable — and records processed is worse still,
since it punishes exactly the workloads the product is good at.

**Keep the purchase boring.** The bar to clear is a mobile app subscription: pick a
plan, pay, done, cancel without an email exchange. That means a hosted checkout —
Stripe Checkout or similar — rather than card fields in this codebase, so the
application never touches a card number and PCI scope stays at nil.

**The awkward part is self-hosting.** MARS runs on someone else's hardware, so there
is no runtime to withhold. That leaves the usual options, and choosing among them is
a business decision rather than a technical one:

- A licence key that unlocks capacity, checked offline. Honest customers pay; it is
  not a lock.
- Open core: the console free, with the paid tier being the things an organisation
  needs — SSO, audit, external secret stores, support.
- A hosted offering, where the metering is real because the slots are yours.

Open core fits what already exists: SSO and external secret stores are both on this
roadmap and are both exactly what a business buyer needs and a hobbyist does not.

**What to build first, whenever this starts.** Not billing. Counting — per target,
over time, retained. Metering is useless applied retrospectively, and a usage view
is worth having even if nothing is ever charged for.

## Later

- **Multi-user in earnest.** Roles exist; per-job ownership and audit do not.
- **Alerting.** MARS knows when a job is restarting; it cannot yet tell anyone.
- **Metric history.** Checkpoint age and lag are read live and forgotten. A short rolling
  window would make "when did this start degrading" answerable.
- **Connector marketplace.** The manifest contract already allows third-party connectors;
  a signed, listed set is what makes that a platform rather than a convention.
