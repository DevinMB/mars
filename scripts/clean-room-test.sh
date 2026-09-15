#!/usr/bin/env bash
# Installs MARS the way a new user does, and checks that it works.
#
# Every assertion below is a regression test for something that was genuinely
# broken the first time this was run, and that was invisible on a machine where
# MARS already worked. The first administrator's password never reached the log;
# a clean checkout had no connectors; two installs on one host merged into one
# cluster because the network and image names were shared.
#
# It runs against a *nested* Docker daemon, not the host's. That is not
# fastidiousness: the first attempt ran on the host's daemon, the two stacks
# collided over shared names, and it cost ten minutes of production downtime. A
# separate daemon cannot share an image, a network, a volume or a container name,
# which is exactly the class of failure being avoided.
#
#   ./scripts/clean-room-test.sh [git-ref]
#
# Needs Docker and nothing else. Removes everything it creates.
set -uo pipefail

REF="${1:-main}"
REPO="${MARS_REPO:-https://github.com/DevinMB/mars.git}"
DIND="mars-cleanroom"
DIND_VOLUME="cleanroom-docker"
# The host has few cores and may be running something that matters. An install
# test is not worth starving it.
DIND_CPUS="${CLEANROOM_CPUS:-1.2}"
DIND_MEM="${CLEANROOM_MEM:-9g}"

pass=0
fail=0

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { pass=$((pass + 1)); printf '  PASS  %s\n' "$*"; }
bad()  { fail=$((fail + 1)); printf '  FAIL  %s\n' "$*"; }
note() { printf '        %s\n' "$*"; }

# Run a command inside the nested daemon's world.
inside() { docker exec "$DIND" sh -c "$*"; }
# Run a command inside the console container, which has curl.
console() { inside "docker exec mars-console $*"; }

cleanup() {
  if [ -n "${CLEANROOM_KEEP:-}" ]; then
    echo
    echo "CLEANROOM_KEEP set: leaving $DIND running for inspection."
    echo "  docker exec $DIND docker compose -f /mars/docker-compose.yml ps"
    echo "  docker exec $DIND docker logs mars-console"
    rm -rf "${WORK:-/nonexistent}"
    return
  fi
  say "Cleaning up"
  docker rm -f "$DIND" >/dev/null 2>&1
  docker volume rm "$DIND_VOLUME" >/dev/null 2>&1
  rm -rf "${WORK:-/nonexistent}"
  echo "  removed the nested daemon and its storage"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
say "Recording the host daemon, so we can prove we did not touch it"
host_images_before=$(docker images -q | sort | md5sum | cut -d' ' -f1)
host_nets_before=$(docker network ls -q | sort | md5sum | cut -d' ' -f1)
host_containers_before=$(docker ps -aq | sort | md5sum | cut -d' ' -f1)
note "images=$host_images_before networks=$host_nets_before containers=$host_containers_before"

# ---------------------------------------------------------------------------
say "Starting an isolated Docker daemon"
docker rm -f "$DIND" >/dev/null 2>&1
docker volume rm "$DIND_VOLUME" >/dev/null 2>&1
docker run -d --name "$DIND" --privileged \
  --cpus "$DIND_CPUS" -m "$DIND_MEM" \
  -e DOCKER_TLS_CERTDIR= \
  -v "$DIND_VOLUME":/var/lib/docker \
  docker:27-dind --storage-driver=overlay2 >/dev/null || {
    echo "could not start the nested daemon"; exit 1; }

for _ in $(seq 1 60); do
  inside "docker info" >/dev/null 2>&1 && break
  sleep 2
done
if inside "docker info" >/dev/null 2>&1; then
  ok "nested daemon is up"
  note "$(inside 'docker info --format "server {{.ServerVersion}}, {{.Images}} images, {{.Containers}} containers"')"
else
  bad "nested daemon never became ready"; exit 1
fi

inside "docker compose version" >/dev/null 2>&1 \
  && ok "docker compose is available inside" \
  || { bad "no docker compose inside the nested daemon"; exit 1; }

# ---------------------------------------------------------------------------
say "Cloning $REF as a new user would"
WORK=$(mktemp -d)
git clone -q --depth 1 --branch "$REF" "$REPO" "$WORK/mars" || {
  bad "clone failed"; exit 1; }
ok "cloned"
note "$(cd "$WORK/mars" && git log --oneline -1)"

jars=$(find "$WORK/mars/flink/jars" -name '*.jar' 2>/dev/null | wc -l)
note "connector jars in a fresh checkout: $jars (expected 0 -- they are build output)"

docker cp "$WORK/mars" "$DIND":/mars >/dev/null
inside "test -f /mars/docker-compose.yml" && ok "sources are in place" || bad "copy failed"

# ---------------------------------------------------------------------------
say "The four commands the README gives"
inside "cd /mars && cp .env.example .env" && ok "cp .env.example .env"
echo "        docker compose up -d --build   (this pulls base images; several minutes)"
if inside "cd /mars && docker compose up -d --build" >/dev/null 2>&1; then
  ok "docker compose up -d"
else
  bad "compose failed to bring the stack up"
  inside "cd /mars && docker compose ps" || true
  exit 1
fi

for _ in $(seq 1 90); do
  inside "docker exec mars-console curl -fsS http://localhost:8080/healthz" >/dev/null 2>&1 && break
  sleep 2
done

# ---------------------------------------------------------------------------
say "What a new user finds"

console "curl -fsS http://localhost:8080/healthz" >/dev/null 2>&1 \
  && ok "the console answers /healthz" || bad "the console does not answer /healthz"

console "curl -fsS -o /dev/null http://localhost:8080/" >/dev/null 2>&1 \
  && ok "the UI is served" || bad "the UI is not served"

logs=$(inside "docker logs mars-console 2>&1")

grep -q "Application startup complete" <<<"$logs" \
  && ok "startup completed" || bad "startup never completed"

if ! grep -q "Application startup complete" <<<"$logs" || ! grep -qi "administrator" <<<"$logs"; then
  echo
  echo "  ---- console log, last 40 lines ----"
  tail -40 <<<"$logs" | sed 's/^/  | /'
  echo "  ---- container states ----"
  inside "cd /mars && docker compose ps --format '{{.Name}} {{.State}} {{.Status}}'" | sed 's/^/  | /'
  echo "  ---- restarts ----"
  inside "docker inspect mars-console --format 'restarts={{.RestartCount}} exit={{.State.ExitCode}}'" | sed 's/^/  | /'
  echo
fi

# The defect: Python block-buffers stdout to a pipe, so this sat in a buffer and
# the documented way in returned nothing.
if grep -qi "administrator" <<<"$logs"; then
  ok "the first administrator's password is in the log, as the README says"
  PW=$(grep -A4 -i "administrator" <<<"$logs" | grep -oE 'password: .*' | head -1 | awk '{print $2}')
  note "password captured: ${PW:+yes}"
else
  bad "the README's 'docker logs | grep administrator' finds nothing"
  PW=""
fi

grep -q "Upgrading schema empty" <<<"$logs" \
  && ok "migrations ran from an empty database" || bad "migrations did not run from empty"

# ---------------------------------------------------------------------------
say "Signing in and building something"

if [ -n "${PW:-}" ]; then
  body="{\"username\":\"admin\",\"password\":\"$PW\"}"
  if console "curl -fsS -X POST http://localhost:8080/api/auth/login -H Content-Type:application/json -d '$body'" >/dev/null 2>&1; then
    ok "the printed password signs in"
  else
    bad "the printed password does not sign in"
  fi
else
  bad "skipped sign-in: no password was printed"
fi

# Listing connectors over the API needs a session; what the console logged at
# startup is the same list and needs none.
conns=$(grep -o "connector(s): .*" <<<"$logs" | head -1 | sed 's/^connector(s): //')
note "connectors on a bare install: ${conns:-unknown}"
case "$conns" in
  *kafka*) ok "Kafka is available, as the README claims" ;;
  *)       bad "Kafka is missing from a bare install" ;;
esac
case "$conns" in
  *couchdb*) bad "couchdb present without running build-connectors.sh (README says otherwise)" ;;
  *)         ok "couchdb is absent until the connectors are built, as documented" ;;
esac

# ---------------------------------------------------------------------------
say "Did any of this touch the host?"
host_images_after=$(docker images -q | sort | md5sum | cut -d' ' -f1)
host_nets_after=$(docker network ls -q | sort | md5sum | cut -d' ' -f1)
host_containers_after=$(docker ps -aq | sort | md5sum | cut -d' ' -f1)

[ "$host_images_before" = "$host_images_after" ] \
  && ok "no image on the host changed" \
  || bad "the host's images changed -- isolation failed"
[ "$host_nets_before" = "$host_nets_after" ] \
  && ok "no network on the host changed" \
  || bad "the host's networks changed -- isolation failed"
# The nested daemon itself is one new container on the host; that is expected.
[ "$host_containers_before" != "$host_containers_after" ] \
  && note "the host gained one container: the nested daemon" \
  || note "host containers unchanged"

# ---------------------------------------------------------------------------
say "Result"
printf '  %d passed, %d failed\n' "$pass" "$fail"
exit $(( fail > 0 ? 1 : 0 ))
