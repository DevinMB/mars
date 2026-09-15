#!/usr/bin/env bash
# Adds optional Flink SQL formats to the image.
#
# Flink's distribution ships json and csv only. Avro is a separate artifact, and
# without it a table declaring 'format' = 'avro' is accepted at creation and then
# fails when a job uses it with "Could not find any factory for identifier
# 'avro'" -- the worst kind of failure, because it looks like your SQL is wrong.
#
# Optional on purpose: run this if you consume Avro, skip it if you do not, and
# the console will not offer a format the cluster cannot honour either way.
#
#   ./scripts/fetch-formats.sh [flink-version]
set -euo pipefail

VERSION="${1:-2.2.1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HERE/flink/jars"
BASE="https://repo1.maven.org/maven2/org/apache/flink"

# The confluent registry format is the one most Avro-on-Kafka setups use; plain
# avro is for topics written without a registry.
ARTIFACTS=(
  "flink-sql-avro"
  "flink-sql-avro-confluent-registry"
)

mkdir -p "$OUT"
echo "Fetching Flink $VERSION formats into flink/jars/"

for a in "${ARTIFACTS[@]}"; do
  jar="$a-$VERSION.jar"
  url="$BASE/$a/$VERSION/$jar"
  if [ -f "$OUT/$jar" ]; then
    echo "  $jar already here"
    continue
  fi
  echo "  $jar"
  curl -fsSL "$url" -o "$OUT/$jar.part"
  mv "$OUT/$jar.part" "$OUT/$jar"
done

echo
echo "Rebuild so Flink picks them up:"
echo "    docker compose build jobmanager && docker compose up -d"
