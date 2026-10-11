# Remote execution target

Run a separate Flink cluster when jobs need to execute on a particular host.
Register it in MARS under **Cluster**, then choose it in the job's **Runs on** field.
Each target needs the connectors used by its jobs and access to their data sources.

## Deploy

Copy the Flink image built by MARS to the target host, or use a registry:

```bash
docker save mars/flink:0.1.0 | ssh user@target-host docker load
scp -r remote-target user@target-host:~/mars-target
```

On that host:

```bash
cd ~/mars-target
cp .env.example .env
# Set TARGET_BIND_ADDRESS to this machine's own private IP (hostname -I), the
# address the MARS host will connect to. Not the MARS host's address.
# Restrict incoming access to that host before starting the target.
docker compose up -d
```

Ports bind to localhost until you choose an interface. Flink REST (8081) and the
SQL Gateway (8083) have no built-in authentication in this configuration. Anyone
who can reach them can control the cluster or execute SQL. Use a protected network
and source restrictions; do not publish these ports to the internet.

From the console host, check `/overview` on port 8081 and `/v1/info` on port 8083,
then add the corresponding URLs as an execution target in MARS. Connectivity must
also work from inside the console container.

## Sizing

Adjust memory in `.env` and `conf/config.yaml` together: Flink's process-memory
setting must fit within the container limit. This template uses one TaskManager
with eight slots. Scaling workers requires adjusting worker discovery/configuration;
it is not supported by simply adding `--scale` to this template.

Use a separate host or change fixed container names and ports for additional
instances. Networks and volumes are scoped to the Compose project.
