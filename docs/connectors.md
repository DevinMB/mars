# Connectors and formats

The default image includes Kafka support. Flink provides datagen and print for
trying pipelines without external services, plus JSON and CSV formats.

Additional MARS connectors are maintained in
[mars-connectors](https://github.com/DevinMB/mars-connectors). Build them with:

```bash
./scripts/build-connectors.sh
```

This requires Git and Docker and downloads the connector source and Maven dependencies.
Set `MARS_CONNECTORS_REF` to a reviewed tag or branch for a reproducible deployment.
JARs are written to `flink/jars/` and remain outside version control.

For optional Avro formats:

```bash
./scripts/fetch-formats.sh
```

After adding connectors or formats, rebuild the Flink image and recreate its services
in a planned maintenance window. Save stateful jobs first; replacing workers interrupts
running jobs. The console reads connector manifests from the JAR directory.
Every execution target needs the connectors and formats used by its jobs.

Store connection credentials in **Settings → Secrets** and reference them in SQL:

```sql
'password' = '${secret:database_password}'
```

Values are resolved when statements are submitted. Avoid literal credentials in SQL,
URLs, descriptions, and extra headers: those fields are ordinary configuration and
may appear in definitions, history, or exports. See [Security](../SECURITY.md).

## How the catalog groups tables

A catalog entry is a table. Whether a job reads or writes it comes from the job:
from Flink's plan when the job is validated, otherwise from its SQL (tables after
`INSERT INTO` are written, the job's other tables are read). There is no source or
sink to choose.

Entries pointing at the same thing are grouped: every table on one Kafka topic is
that topic, shown once with the jobs that write and read it. MARS knows what Kafka,
upsert-kafka, CouchDB, filesystem and JDBC tables point at. A connector can declare
its own in its manifest:

```json
"identity": { "server": "base-url", "name": "domain", "label": "home assistant domain" }
```

`name` is the option naming the target, `server` (optional) the option naming the
system it lives on, so two clusters with a same-named target stay apart, and
`label` what to call it. Without `identity`, each table is shown on its own.
