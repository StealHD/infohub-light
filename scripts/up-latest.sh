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

SERVICES=("horizon-web" "horizon-scheduler")
MANUAL_SERVICE="horizon"
BUILD_FLAGS=("--pull")

if [[ "$(read_setting HORIZON_BUILD_NO_CACHE true)" == "true" ]]; then
  BUILD_FLAGS+=("--no-cache")
fi

echo "==> Building current workspace into Docker images"
echo "    docker compose build ${BUILD_FLAGS[*]} ${SERVICES[*]} $MANUAL_SERVICE"
docker compose build "${BUILD_FLAGS[@]}" "${SERVICES[@]}" "$MANUAL_SERVICE"

echo "==> Recreating running services from freshly built images"
docker compose up -d --no-build --force-recreate --remove-orphans "${SERVICES[@]}"

if [[ "$(read_setting HORIZON_PRUNE_OLD_IMAGES true)" == "true" ]]; then
  echo "==> Removing old dangling images for this Compose project"
  docker image prune -f --filter "label=com.docker.compose.project=horizon" >/dev/null || true
fi

if [[ "$(read_setting HORIZON_PRUNE_BUILD_CACHE true)" == "true" ]]; then
  prune_until="$(read_setting HORIZON_PRUNE_BUILD_CACHE_UNTIL 24h)"
  echo "==> Removing Docker build cache older than $prune_until"
  docker builder prune -f --filter "until=$prune_until" >/dev/null || true
fi

echo "==> Current service status"
docker compose ps
