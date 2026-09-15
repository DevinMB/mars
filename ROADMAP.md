# MARS roadmap

Ordered roughly by when each becomes necessary rather than by appeal.

## Near term

- ~~Alembic migrations run on startup~~ **DONE**, and needed sooner than expected:
  adding a column to `jobs` brought the console up and then failed at the first query
  mentioning it, because `create_all` adds missing tables but never missing columns.
- **Savepoint-aware restarts.** Cancel-with-savepoint and resume-from-savepoint through
  the console. Supervisor mode currently resubmits from scratch, which is wrong for any
  job with meaningful state. Now also a prerequisite for credential rotation, since
  picking up a rotated password means restarting the jobs that hold the old one.
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
