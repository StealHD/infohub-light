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
    --runtime "$REMOTE_BASE" --public-url "$PUBLIC_URL"
}

prepare_fast() {
  umask 077
  local gate_result="" e2e_result="" directory revision version built_at release_id image baseline started
  local gate_args compare_base
  started=$SECONDS
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --gate-result) [[ $# -ge 2 ]] || fail "--gate-result requires PATH"; gate_result="$2"; shift 2 ;;
      --e2e-result) [[ $# -ge 2 ]] || fail "--e2e-result requires PATH"; e2e_result="$2"; shift 2 ;;
      *) fail "unknown prepare-fast argument: $1" ;;
    esac
  done
  [[ -n "$gate_result" ]] || fail "prepare-fast requires --gate-result PATH"
  require_commands
  cd "$ROOT_DIR"
  [[ "$(git branch --show-current)" == main ]] || fail "prepare-fast must run from local main"
  revision="$(git rev-parse HEAD)"
  require_frozen_release_source "$revision"
  "$PYTHON_BIN" scripts/release_mode.py --require fast --check-version
  version="$(project_version)"
  [[ "$RELEASE_TAG" == "v$version" ]] || fail "tag and project version disagree"
  [[ "$PLATFORM" == linux/amd64 ]] || fail "fast release requires linux/amd64"
  baseline="$(fast_helper baseline --host "$REMOTE_HOST")"
  reject_implicit_migrations "$(release_base_ref)"
  compare_base="HEAD^"
  if [[ "$baseline" != unknown* ]]; then
    reject_implicit_migrations "$baseline"
    compare_base="$baseline"
  fi
  gate_args=(--gate-result "$gate_result" --baseline "$baseline")
  if [[ -n "$e2e_result" ]]; then gate_args+=(--e2e-result "$e2e_result"); fi
  fast_helper evidence "${gate_args[@]}"
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
  fast_helper evidence --directory "$directory" "${gate_args[@]}"
  "$PYTHON_BIN" scripts/test_gate.py run --mode targeted --scope control \
    --base "$compare_base" --head HEAD
  "$PYTHON_BIN" scripts/release_light_checks.py --base "$compare_base" --head HEAD
  built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  release_id="$version-$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-fast-$$"
  image="inteliscope-service:$release_id"
  LOCAL_RELEASE_IMAGE="$image"
  build_package "${revision:0:12}" "$revision" "$version" "$built_at" "$release_id" "$image"
  fast_helper smoke --directory "$directory" --image "$image"
  require_frozen_release_source "$revision"
  [[ "$(fast_helper baseline --host "$REMOTE_HOST")" == "$baseline" ]] || fail "production baseline changed during prepare"
  fast_helper seal --directory "$directory" --release-id "$release_id" --image "$image" \
    --built-at "$built_at" --host "$REMOTE_HOST" --runtime "$REMOTE_BASE" --public-url "$PUBLIC_URL"
  RELEASE_TMP_DIR=""
  LOCAL_RELEASE_IMAGE=""
  echo "Fast preparation complete in $((SECONDS - started))s: $directory"
}

release_fast() {
  local directory revision release_id image version built_at fields started
  started=$SECONDS
  require_release_prerequisites
  "$PYTHON_BIN" "$ROOT_DIR/scripts/release_mode.py" --require fast --check-version
  directory="$(fast_directory)"
  fields="$(verify_fast_package)" || fail "no valid fast preparation; run prepare-fast explicitly"
  read -r release_id image version built_at <<<"$fields"
  revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  wait_for_workflow_success test-gate.yml "$revision" main
  # Keep prepared artifacts on both success and failure; the EXIT cleanup owns
  # only the remote staging directory during fast publication.
  REMOTE_RELEASE_STAGE="/tmp/inteliscope-release-$release_id"
  ( RELEASE_TMP_DIR="$directory"; upload_package "$release_id" )
  require_frozen_release_source "$revision"
  verify_fast_package >/dev/null
  git -C "$ROOT_DIR" tag -a "$RELEASE_TAG" -m "Release $RELEASE_TAG" -m "Release-Mode: fast"
  TAG_CREATED=true
  git -C "$ROOT_DIR" push origin "refs/tags/$RELEASE_TAG"
  TAG_PUSHED=true
  wait_for_workflow_success release-tag.yml "$revision" "$RELEASE_TAG"
  require_frozen_release_source "$revision"
  [[ "$(fast_helper baseline --host "$REMOTE_HOST")" == "$(
    "$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1]))["baseline"] or "unknown")' "$directory/manifest.json"
  )" ]] || fail "production baseline changed before cutover"
  deploy_remote_release "$release_id" "$image" "$version" "${revision:0:12}" "$built_at" "git:$revision"
  REMOTE_RELEASE_STAGE=""
  echo "Fast release complete in $((SECONDS - started))s: $RELEASE_TAG ($release_id)"
}
