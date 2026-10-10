# Security

MARS is designed for trusted operators on a protected network. It is not a sandbox
for untrusted SQL or a public, multi-tenant execution service.

## Access boundaries

- Keep Flink REST and SQL Gateway endpoints private. They do not inherit MARS authentication.
- Use HTTPS for shared console access, set `MARS_SESSION_COOKIE_SECURE=true`, and
  apply login rate limiting and request limits at your reverse proxy.
- Grant editor access only to people trusted to run SQL with the cluster's network
  access and credentials. Viewer access includes SQL definitions and operational metadata.
- Protect host access, Docker access, logs, and backups. Health and metrics endpoints
  are unauthenticated and should remain within the deployment's network boundary.

## Credentials and data

Passwords and API tokens are hashed with Argon2. Connection secrets are encrypted
with a per-installation Fernet key. The database and key share the console data volume;
encryption does not protect against someone who can read that whole volume.

Use **Settings → Secrets** and `${secret:name}` references for connection credentials.
Use the AI provider's Authentication controls for its credential. Extra headers,
endpoint URLs, SQL, descriptions, and version history are ordinary stored configuration;
do not put literal credentials there. Redaction of known secret values in diagnostic
text is best effort: short values and encoded forms may not be removed. It is not
a guarantee that arbitrary output is safe to share.

Definition exports omit the secret store but include user-entered SQL and endpoints.
Review exports, logs, screenshots, and Git history before publishing them. If a
credential is committed, rotate it; deleting the latest copy does not erase history.

AI assistance is optional. When enabled, prompts, catalog names and column definitions,
and validation feedback may be sent to the configured provider. Use a provider approved
for that information and avoid sensitive data in prompts.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** option if available.
Otherwise, ask the maintainer for a private reporting channel without posting exploit
details or credentials in a public issue. Include the affected version and a minimal
reproduction using synthetic data.
