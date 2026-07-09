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
  LIGHT_SERVICES=("horizon-api")
  LIGHT_MANUAL_SERVICE="horizon"
  SERVICES=("${LIGHT_SERVICES[@]}")
  MANUAL_SERVICE="$LIGHT_MANUAL_SERVICE"
  PRUNE_PROJECT="infohub-light"
else
  COMPOSE=(docker compose)
  SERVICES=("horizon-web" "horizon-scheduler")
  MANUAL_SERVICE="horizon"
  PRUNE_PROJECT="horizon"
fi

if [[ "$(read_setting HORIZON_BUILD_NO_CACHE true)" == "true" ]]; then
  BUILD_FLAGS+=("--no-cache")
fi

echo "==> Building current workspace into Docker images"
echo "    ${COMPOSE[*]} build ${BUILD_FLAGS[*]} ${SERVICES[*]} $MANUAL_SERVICE"
"${COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${SERVICES[@]}" "$MANUAL_SERVICE"

echo "==> Recreating running services from freshly built images"
"${COMPOSE[@]}" up -d --no-build --force-recreate --remove-orphans "${SERVICES[@]}"

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
