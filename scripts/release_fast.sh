#!/usr/bin/env bash
# Sourced by release_vps.sh; shares build, transfer, cutover and rollback helpers.

fast_helper() {
  "$PYTHON_BIN" "$ROOT_DIR/scripts/release_fast.py" "$@"
}

fast_directory() {
  printf '%s/.test-results/fast-release/%s\n' "$ROOT_DIR" "$(git -C "$ROOT_DIR" rev-parse HEAD)"
}

verify_fast_package() {
  fast_helper verify --directory "$(fast_directory)" --host "$REMOTE_HOST" \
    --runtime "$REMOTE_BASE" --public-url "$PUBLIC_URL" \
    --migration-receipt "$MIGRATION_RECEIPT_PATH"
}

prepare_fast() {
  umask 077
  local directory revision version built_at release_id image started
  started=$SECONDS
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --migration-receipt) [[ $# -ge 2 && -z "$MIGRATION_RECEIPT_PATH" ]] || fail "--migration-receipt requires one PATH"; MIGRATION_RECEIPT_PATH="$2"; shift 2 ;;
      *) fail "unknown prepare-fast argument: $1" ;;
    esac
  done
  require_commands
  cd "$ROOT_DIR"
  [[ "$(git branch --show-current)" == main ]] || fail "prepare-fast must run from local main"
  revision="$(git rev-parse HEAD)"
  require_frozen_release_source "$revision"
  version="$(project_version)"
  [[ "$RELEASE_TAG" == "v$version" ]] || fail "tag and project version disagree"
  [[ "$PLATFORM" == linux/amd64 ]] || fail "fast release requires linux/amd64"
  directory="$(fast_directory)"
  [[ ! -L "$ROOT_DIR/.test-results" && ! -L "$(dirname "$directory")" && ! -L "$directory" ]] \
    || fail "fast artifact directories must not be symlinks"
  if [[ -f "$directory/manifest.json" ]] && verify_fast_package >/dev/null; then
    echo "Prepared artifacts reused: $directory"
    return 0
  fi
  if [[ -d "$directory" ]]; then mv "$directory" "$directory.previous-$(date +%s)-$$"; fi
  mkdir -p "$(dirname "$directory")"
  mkdir -m 700 "$directory"
  RELEASE_TMP_DIR="$directory"
  built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  release_id="$version-$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-fast-$$"
  image="inteliscope-service:$release_id"
  LOCAL_RELEASE_IMAGE="$image"
  build_package "${revision:0:12}" "$revision" "$version" "$built_at" "$release_id" "$image"
  require_frozen_release_source "$revision"
  fast_helper seal --directory "$directory" --release-id "$release_id" --image "$image" \
    --built-at "$built_at" --host "$REMOTE_HOST" --runtime "$REMOTE_BASE" \
    --public-url "$PUBLIC_URL" --migration-receipt "$MIGRATION_RECEIPT_PATH"
  RELEASE_TMP_DIR=""
  LOCAL_RELEASE_IMAGE=""
  echo "Fast preparation complete in $((SECONDS - started))s: $directory"
}

release_fast() {
  local directory revision release_id image version built_at fields started package_kib image_bytes archive_kib
  started=$SECONDS
  require_release_prerequisites
  prepare_fast
  directory="$(fast_directory)"
  fields="$(verify_fast_package)" || fail "release package verification failed"
  read -r release_id image version built_at <<<"$fields"
  revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  image_bytes="$(docker image inspect "$image" --format '{{.Size}}')"
  archive_kib="$(du -k "$directory/source.tar.gz" "$directory/image.tar.gz" | awk '{total += $1} END {print total}')"
  [[ "$image_bytes" =~ ^[0-9]+$ && "$archive_kib" =~ ^[0-9]+$ ]] || fail "cannot size release package"
  package_kib=$((image_bytes / 1024 + archive_kib * 2))
  remote_capacity_preflight "$package_kib"
  # Keep prepared artifacts on both success and failure; the EXIT cleanup owns
  # only the remote staging directory during fast publication.
  REMOTE_RELEASE_STAGE="/tmp/inteliscope-release-$release_id"
  ( RELEASE_TMP_DIR="$directory"; upload_package "$release_id" )
  require_frozen_release_source "$revision"
  verify_fast_package >/dev/null
  deploy_remote_release "$release_id" "$image" "$version" "${revision:0:12}" "$built_at" "git:$revision" \
    "$MIGRATION_RECEIPT_PATH" "$MIGRATION_BACKUP_PATH"
  REMOTE_RELEASE_STAGE=""
  git -C "$ROOT_DIR" tag -a "$RELEASE_TAG" -m "Release $RELEASE_TAG"
  TAG_CREATED=true
  git -C "$ROOT_DIR" push origin "refs/tags/$RELEASE_TAG" \
    || fail "VPS is healthy on $release_id, but tag push failed; publish the tag without redeploying"
  TAG_PUSHED=true
  echo "Release complete in $((SECONDS - started))s: $RELEASE_TAG ($release_id)"
}
