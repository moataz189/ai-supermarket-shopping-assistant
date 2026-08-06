#!/usr/bin/env bash
# Proves container construction and basic reachability of the docker-compose stack — not a
# substitute for the manual walkthrough (real Bedrock/Spoonacular calls, retailer-cart
# flows) documented in docs/plan/09-containerization.md. Never touches external API quota:
# only checks that each service comes up and responds, using whatever BEDROCK_MODEL_ID /
# SPOONACULAR_API_KEY happen to be configured in .env (a placeholder value is enough — the
# backend and recipe-mcp only need it to be *set*, not valid, to pass their own health
# checks; no chat/recipe request is made here).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

on_exit() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo
    echo "=== smoke test FAILED (exit $status) — service status ==="
    docker compose ps
    echo
    echo "=== logs for services not running or unhealthy ==="
    for svc in $(docker compose ps --services 2>/dev/null); do
      state=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null || echo "unknown")
      health=$(docker compose ps --format '{{.Health}}' "$svc" 2>/dev/null || echo "")
      if [ "$state" != "running" ] || [ "$health" = "unhealthy" ]; then
        echo "--- logs: $svc (state=$state health=$health) ---"
        docker compose logs --no-color "$svc" || true
        echo
      fi
    done
  fi
  echo "=== tearing down ==="
  docker compose down --remove-orphans
  exit "$status"
}
trap on_exit EXIT

echo "=== building images ==="
docker compose build

echo "=== starting stack ==="
docker compose up -d

wait_for() {
  local name="$1" url="$2" timeout="${3:-90}"
  echo "waiting up to ${timeout}s for $name ($url)..."
  for ((i = 0; i < timeout; i++)); do
    if curl -sf "$url" > /dev/null 2>&1; then
      echo "$name ready after ${i}s"
      return 0
    fi
    sleep 1
  done
  echo "$name did not become ready within ${timeout}s" >&2
  return 1
}

wait_for "backend" "http://localhost:8000/health" 90
curl -sf http://localhost:8000/health

wait_for "web" "http://localhost:3000/" 90
curl -sf http://localhost:3000/ > /dev/null

echo "=== container status ==="
docker compose ps

echo "=== verifying every started service is running ==="
for svc in $(docker compose ps --services); do
  state=$(docker compose ps --format '{{.State}}' "$svc")
  if [ "$state" != "running" ]; then
    echo "service $svc is not running (state: $state)" >&2
    exit 1
  fi
done

echo "smoke test passed"
