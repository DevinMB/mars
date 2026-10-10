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

## Monitoring

`/healthz` checks the console process; `/readyz` checks default Flink reachability.
`/metrics` exposes Prometheus metrics including running and failed job counts.
These endpoints are unauthenticated, so keep them inside the same access boundary.
Flink's Prometheus reporter listens on port 9249 inside the container network.
