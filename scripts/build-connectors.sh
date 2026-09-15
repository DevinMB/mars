#!/usr/bin/env bash
# Builds the MARS connectors and puts them where the Flink image picks them up.
#
# They are not committed: they are build output, and a repository is the wrong
# place for 9 MB of jars. They are also not downloaded when a container starts --
# that turns every restart into a dependency on someone else's uptime, and a slow
# network into a cluster that comes up without its connectors.
#
# So they are built once, here, into flink/jars/, and baked into the image.
# Needs Docker and nothing else: the build runs in a Maven container.
set -euo pipefail

REPO="${MARS_CONNECTORS_REPO:-https://github.com/DevinMB/mars-connectors.git}"
REF="${MARS_CONNECTORS_REF:-main}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HERE/flink/jars"

echo "Building connectors from $REPO ($REF)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone --depth 1 --branch "$REF" "$REPO" "$work/src"

docker run --rm \
  -v "$work/src:/src" \
  -v "$work/m2:/root/.m2" \
  -w /src \
  maven:3.9-eclipse-temurin-17 \
  mvn -q -B -DskipTests package

mkdir -p "$OUT"
found=0
while IFS= read -r jar; do
  case "$(basename "$jar")" in
    *-sources.jar|*-javadoc.jar|original-*) continue ;;
  esac
  cp "$jar" "$OUT/"
  echo "  $(basename "$jar")"
  found=$((found + 1))
done < <(find "$work/src" -path '*/target/*.jar' -type f)

if [ "$found" -eq 0 ]; then
  echo "No jars were produced. The build printed nothing useful above?" >&2
  exit 1
fi

echo
echo "$found connector jar(s) in flink/jars/."
echo "Rebuild the image so Flink picks them up:"
echo "    docker compose build jobmanager && docker compose up -d"
