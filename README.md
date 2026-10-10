# MARS

**A web console for Apache Flink SQL.**

Build streaming pipelines, manage reusable sources and sinks, and operate jobs from
one workspace. MARS brings SQL editing, scheduling, savepoints, and run history
alongside your Flink cluster.

![MARS jobs workspace, shown with sample pipelines](docs/images/jobs.png)

## What you can do

- **Build pipelines** with a SQL editor, connector forms, validation, and data previews.
- **Run and recover jobs** with schedules, restart supervision, and savepoints.
- **Reuse definitions** through a shared catalog, version history, and YAML import/export.
- **Manage access** with administrator, editor, and viewer roles, API tokens, and encrypted secrets.
- **Choose where jobs run** across registered Flink clusters. Optional AI assistance helps draft SQL.

## Quick start

Requires Git, Docker with Compose v2, and roughly 6 GB of available RAM for the default stack.

```bash
git clone https://github.com/DevinMB/mars.git
cd mars
cp .env.example .env
docker compose up -d --build
```

Open **[localhost:8080](http://localhost:8080)**. Retrieve the generated administrator
password locally, sign in as `admin`, and change it:

```bash
docker compose logs console | grep -A4 'administrator'
```

The log contains a credential; keep it private. A fresh installation includes an
example pipeline using generated data, so you can try a job without an external service.

The stack includes Flink 2.2.1, its SQL Gateway, and the MARS console with SQLite.
Kafka, datagen, and print connectors are available out of the box; additional
connectors and Avro formats are [optional](docs/connectors.md).

Ports bind to localhost by default. For remote access, use an SSH tunnel or follow
the [deployment guide](docs/deployment.md). Flink and its SQL Gateway must stay on a
protected network; MARS is intended for trusted operators.

## Documentation

[Deployment & backups](docs/deployment.md) · [Connectors](docs/connectors.md) ·
[Development](docs/development.md) · [Security](SECURITY.md) · [Roadmap](ROADMAP.md)

MARS is open source under the [MIT License](LICENSE) and is under active development.

---

MARS is an independent project, not affiliated with the Apache Software Foundation.
Apache Flink® is a registered trademark of the ASF.
