#!/usr/bin/env bash
# End-to-end tests: start the backend on the recorded feeds, run Playwright
# against the built web app, then tear everything down.
# Uses its own Docker project and ports, so it can run beside `make dev`.
#   deploy/e2e.sh [extra playwright args]
set -euo pipefail
cd "$(dirname "$0")/.."

export DEV_API_PORT=${DEV_API_PORT:-8199} DEV_DB_PORT=${DEV_DB_PORT:-5499}
export LAYOVER_API="http://localhost:${DEV_API_PORT}"
compose=(docker compose -p layover-e2e -f "$PWD/deploy/compose.dev.yml" --profile e2e)

cleanup() { "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM PIPE

"${compose[@]}" up -d --build --quiet-pull
echo "waiting for the fixtures to finish replaying…"
for _ in $(seq 1 120); do
  state=$("${compose[@]}" ps -a --format '{{.Service}} {{.State}} {{.ExitCode}}' | awk '$1=="replay-once"')
  case "$state" in
    *"exited 0"*) break ;;
    *exited*) echo "replay failed: $state" >&2; "${compose[@]}" logs replay-once >&2; exit 1 ;;
  esac
  sleep 2
done
curl -sf "$LAYOVER_API/api/systems/squamish/live" >/dev/null || { echo "API not ready" >&2; exit 1; }

cd web
npx playwright test "$@"
