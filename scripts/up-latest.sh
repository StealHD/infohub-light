#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

read_setting() {
  local name="$1"
  local default_value="$2"
  local value="${!name-}"

  if [[ -z "$value" && -f ".env" ]]; then
    value="$(awk -F= -v key="$name" '$1 == key {print substr($0, index($0, "=") + 1)}' .env | tail -n 1)"
    value="${value%$'\r'}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "${value:-$default_value}"
}

BUILD_FLAGS=("--pull")

if [[ -f "docker-compose.light.yml" ]]; then
  COMPOSE=(docker compose -f docker-compose.light.yml)
  LIGHT_SERVICES=("horizon-api" "horizon-worker")
  LIGHT_MANUAL_SERVICE="horizon"
  SERVICES=("${LIGHT_SERVICES[@]}")
  MANUAL_SERVICE="$LIGHT_MANUAL_SERVICE"
  PRUNE_PROJECT="infohub-light"
  DEFAULT_WEB_PORT="8081"
else
  COMPOSE=(docker compose)
  SERVICES=("horizon-api" "horizon-worker")
  MANUAL_SERVICE="horizon"
  PRUNE_PROJECT="horizon"
  DEFAULT_WEB_PORT="8080"
fi

revision="$(git rev-parse --short=12 HEAD 2>/dev/null || printf unknown)"
if [[ -n "$(git status --porcelain 2>/dev/null || true)" ]]; then
  revision="${revision}-dirty"
fi
export INTELISCOPE_VERSION="$(read_setting INTELISCOPE_VERSION 1.5.0)"
export INTELISCOPE_BUILD_REVISION="$(read_setting INTELISCOPE_BUILD_REVISION "$revision")"
export INTELISCOPE_BUILT_AT="$(read_setting INTELISCOPE_BUILT_AT "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
export INTELISCOPE_IMAGE="$(read_setting INTELISCOPE_IMAGE "inteliscope-service:local-${revision}")"

if [[ "$(read_setting HORIZON_BUILD_NO_CACHE true)" == "true" ]]; then
  BUILD_FLAGS+=("--no-cache")
fi

echo "==> Building current workspace into Docker images"
echo "    ${COMPOSE[*]} build ${BUILD_FLAGS[*]} ${SERVICES[*]} $MANUAL_SERVICE"
"${COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${SERVICES[@]}" "$MANUAL_SERVICE"

echo "==> Recreating running services from freshly built images"
"${COMPOSE[@]}" up -d --no-build --force-recreate --remove-orphans "${SERVICES[@]}"

web_port="$(read_setting HORIZON_WEB_PORT "$DEFAULT_WEB_PORT")"
live_url="http://127.0.0.1:${web_port}/api/health/live"
ready_url="http://127.0.0.1:${web_port}/api/health/ready"
echo "==> Waiting for API liveness and readiness"
for attempt in $(seq 1 90); do
  live_payload="$(curl -fsS "$live_url" 2>/dev/null || true)"
  ready_payload="$(curl -fsS "$ready_url" 2>/dev/null || true)"
  if [[ "$live_payload" == *"$INTELISCOPE_BUILD_REVISION"* && -n "$ready_payload" ]]; then
    break
  fi
  if [[ "$attempt" -eq 90 ]]; then
    echo "API failed release identity/readiness verification" >&2
    "${COMPOSE[@]}" logs --tail=200 "${SERVICES[@]}" >&2 || true
    exit 1
  fi
  sleep 2
done
echo "    live revision: $INTELISCOPE_BUILD_REVISION"
echo "    ready: yes"

if [[ "$(read_setting HORIZON_PRUNE_OLD_IMAGES true)" == "true" ]]; then
  echo "==> Removing old dangling images for this Compose project"
  docker image prune -f --filter "label=com.docker.compose.project=$PRUNE_PROJECT" >/dev/null || true
fi

if [[ "$(read_setting HORIZON_PRUNE_BUILD_CACHE true)" == "true" ]]; then
  prune_until="$(read_setting HORIZON_PRUNE_BUILD_CACHE_UNTIL 24h)"
  echo "==> Removing Docker build cache older than $prune_until"
  docker builder prune -f --filter "until=$prune_until" >/dev/null || true
fi

echo "==> Current service status"
"${COMPOSE[@]}" ps
