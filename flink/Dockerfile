# MARS Flink image: a pinned Flink release plus the connectors MARS ships with.
#
# Everything is baked in at build time. Nothing is downloaded when a container
# starts, so a cold boot does not depend on Maven Central or GitHub being up.
FROM flink:2.3.0-java17

ARG FLINK_KAFKA_VERSION=5.0.0-2.2
ARG KAFKA_CLIENTS_VERSION=3.9.2
ARG MAVEN_CENTRAL=https://repo1.maven.org/maven2

USER root

# Kafka connector + its client. Fetched at build time, verified non-empty.
RUN set -eux; \
    curl -fsSL -o /opt/flink/lib/flink-connector-kafka.jar \
      "${MAVEN_CENTRAL}/org/apache/flink/flink-connector-kafka/${FLINK_KAFKA_VERSION}/flink-connector-kafka-${FLINK_KAFKA_VERSION}.jar"; \
    curl -fsSL -o /opt/flink/lib/kafka-clients.jar \
      "${MAVEN_CENTRAL}/org/apache/kafka/kafka-clients/${KAFKA_CLIENTS_VERSION}/kafka-clients-${KAFKA_CLIENTS_VERSION}.jar"; \
    test -s /opt/flink/lib/flink-connector-kafka.jar; \
    test -s /opt/flink/lib/kafka-clients.jar

# The Prometheus reporter already sits in /opt/flink/plugins/metrics-prometheus and
# is picked up by Flink's plugin loader, so it needs no copy onto the classpath.

# MARS connectors, built from the mars-connectors repo.
COPY jars/ /opt/flink/lib/

# Checkpoint and savepoint root. Creating it here with the right ownership matters:
# Docker seeds a new named volume from the image path, so a volume mounted at
# /flink-state inherits flink:flink. Without this the volume is root-owned and every
# job fails at submission with "Failed to create directory for shared state".
RUN mkdir -p /flink-state/checkpoints /flink-state/savepoints \
    && chown -R flink:flink /flink-state /opt/flink/lib

USER flink
