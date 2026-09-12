"""Exercise release dispatch with external commands and cutover safely mocked."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REVISION = "1" * 40
BASE_REF = "v0.0.1"
RELEASE_TAG = "v99.99.99"

FAKE_COMMAND = r'''
import json
import os
import sys

command = sys.argv.pop(1)
args = sys.argv[1:]
failure = os.environ["FAKE_FAILURE"]
revision = "1" * 40

def record(event):
    with open(os.environ["FAKE_EVENT_LOG"], "a") as stream:
        stream.write(event + "\n")

if command == "python":
    if args[:1] == ["scripts/test_gate.py"]:
        record("test_gate " + " ".join(args[1:]))
        sys.exit(1 if failure == "test_gate" else 0)
    if args[0].endswith("release_mode.py"):
        sys.exit(1 if failure == "mode" else 0)
    if args[0].endswith("release_light_checks.py"):
        sys.exit(0)
    os.execv(sys.executable, [sys.executable, *args])

if command == "git" and args[:1] == ["-C"]:
    args = args[2:]
record(command + " " + " ".join(args))

if command == "git":
    if args[0] == "status":
        print(" M dirty.py" if failure == "dirty" else "")
    elif args[:2] == ["branch", "--show-current"]:
        print("feature" if failure == "branch" else "main")
    elif args[0] == "rev-parse":
        if args[-1] == "origin/main" and failure == "remote_sha":
            print("2" * 40)
        else:
            print(revision[:12] if "--short=12" in args else revision)
    elif args[:2] == ["tag", "--list"]:
        print(args[-1] if failure == "local_tag" else "")
    elif args[0] == "ls-remote":
        sys.exit(0 if failure == "remote_tag" else 2)
    elif args[0] == "describe":
        print("v0.0.1")
    elif args[:2] == ["diff", "--name-only"] and failure == "migration":
        print("scripts/migrate_fixture.py")
    elif args[:2] == ["diff", "-U0"] and failure == "schema":
        print("+CREATE TABLE fixture")
elif command == "ssh":
    sys.stdin.read()
    if args[:1] != ["-o"]:
        record("capacity")
        sys.exit(1 if failure == "capacity" else 0)
elif command == "gh":
    workflow = args[args.index("--workflow") + 1]
    branch = "main" if workflow == "test-gate.yml" else "v99.99.99"
    failed = failure == ("main_ci" if branch == "main" else "tag_ci")
    print(json.dumps([{
        "status": "completed", "conclusion": "failure" if failed else "success",
        "event": "push", "headBranch": branch, "url": "https://example.invalid/run"
    }]))
'''

ARTIFACT_STUBS = '''
build_package_and_upload() {
  printf 'artifact %s\\n' "$2" >> "$FAKE_EVENT_LOG"
  [[ "$FAKE_FAILURE" != artifact ]]
}
deploy_remote_release() {
  printf 'cutover\\n' >> "$FAKE_EVENT_LOG"
}
'''


ARTIFACT_STUBS += r'''
build_package() {
  echo build >> "$FAKE_EVENT_LOG"
  [[ "$FAKE_FAILURE" != artifact ]]
}
upload_package() {
  echo upload >> "$FAKE_EVENT_LOG"
}
fast_helper() {
  echo "fast $1" >> "$FAKE_EVENT_LOG"
  [[ "$FAKE_FAILURE" != "$1" ]] || return 1
  case "$1" in
    baseline) echo 1111111111111111111111111111111111111111 ;;
    verify)
      mkdir -p "$3"
      echo '{"baseline":"1111111111111111111111111111111111111111"}' > "$3/manifest.json"
      echo '99.99.99-fast inteliscope-service:99.99.99-fast 99.99.99 2026-09-12T00:00:00Z'
      ;;
  esac
}
'''


@pytest.fixture
def run_release_command(tmp_path):
    fixture_root = tmp_path / "checkout"
    scripts = fixture_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "release_fast.sh").write_text((ROOT / "scripts/release_fast.sh").read_text())
    (fixture_root / "pyproject.toml").write_text(
        '[project]\nversion = "99.99.99"\n', encoding="utf-8"
    )
    source = (ROOT / "scripts/release_vps.sh").read_text(encoding="utf-8")
    # Keep the real CLI, prerequisites, CI polling, tagging and failure handling.
    # Replace only artifact preparation and remote cutover before CLI dispatch.
    dispatch = 'command="${1:-}"\ncase "$command" in'
    assert source.count(dispatch) == 1
    script = scripts / "release_vps.sh"
    script.write_text(source.replace(dispatch, ARTIFACT_STUBS + dispatch), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_command = fake_bin / "command.py"
    fake_command.write_text(FAKE_COMMAND, encoding="utf-8")
    for name in ("git", "docker", "rsync", "ssh", "gh", "gzip", "shasum", "python"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
            f"{shlex.quote(str(fake_command))} {name} \"$@\"\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    event_log = tmp_path / "events.log"

    def run(command, failure="", tag=RELEASE_TAG, extra=()):
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("HORIZON_", "INTELISCOPE_"))
        }
        environment.update(
            PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            INTELISCOPE_RELEASE_PYTHON=str(fake_bin / "python"),
            FAKE_EVENT_LOG=str(event_log),
            FAKE_FAILURE=failure,
        )
        result = subprocess.run(
            ["bash", str(script), command, tag, *extra], env=environment,
            capture_output=True, text=True, timeout=15,
        )
        return result, event_log.read_text(encoding="utf-8").splitlines()

    return run


def test_release_reuses_exact_main_ci_without_running_local_code_tests(run_release_command):
    result, events = run_release_command("release", failure="test_gate")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(event.startswith("test_gate ") for event in events)
    assert f"git diff --name-only {BASE_REF}...HEAD -- scripts/migrate_*.py" in events
    main_ci = next(event for event in events if "--workflow test-gate.yml" in event)
    tag_ci = next(event for event in events if "--workflow release-tag.yml" in event)
    assert f"--commit {REVISION}" in main_ci
    assert f"--commit {REVISION}" in tag_ci
    tag = f"git tag -a {RELEASE_TAG} -m Release {RELEASE_TAG}"
    assert events.index("capacity") < events.index(main_ci) < events.index(tag)
    assert events.index(f"artifact {REVISION}") < events.index(tag)
    assert events.index(tag) < events.index(tag_ci) < events.index("cutover")


@pytest.mark.parametrize("failure", ["", "test_gate"])
def test_explicit_preflight_runs_local_tests_without_tagging_or_cutover(run_release_command, failure):
    result, events = run_release_command("preflight", failure=failure)

    assert result.returncode == (1 if failure else 0), result.stdout + result.stderr
    gate = f"test_gate preflight --base {BASE_REF} --head HEAD"
    assert events.count(gate) == 1
    assert events.index("capacity") < events.index(gate)
    assert ("Preflight passed" in result.stdout) == (not failure)
    assert not any(event.startswith(("artifact ", "gh ", "git tag -a", "git push")) for event in events)
    assert "cutover" not in events


@pytest.mark.parametrize("failure", [
    "dirty", "branch", "remote_sha", "local_tag", "remote_tag", "migration", "schema", "capacity", "mode",
])
def test_release_prerequisite_failures_block_artifacts_tag_and_cutover(run_release_command, failure):
    result, events = run_release_command("release", failure=failure)

    assert result.returncode != 0
    assert not any(event.startswith(("artifact ", "gh ", "test_gate ", "git tag -a", "git push")) for event in events)
    assert "cutover" not in events


def test_release_rejects_version_mismatch_before_tag_or_cutover(run_release_command):
    result, events = run_release_command("release", tag="v0.0.2")

    assert result.returncode != 0
    assert "does not match pyproject version" in result.stderr
    assert not any(event.startswith(("artifact ", "gh ", "git tag -a", "git push")) for event in events)
    assert "cutover" not in events


@pytest.mark.parametrize("failure", ["main_ci", "artifact", "tag_ci"])
def test_release_evidence_failures_block_cutover(run_release_command, failure):
    result, events = run_release_command("release", failure=failure)

    assert result.returncode != 0
    assert not any(event.startswith("test_gate ") for event in events)
    assert any(event.startswith("git tag -a") for event in events) == (failure == "tag_ci")
    assert any(event.startswith("git push") for event in events) == (failure == "tag_ci")
    assert "cutover" not in events


def test_fast_publication_never_builds_or_runs_tests(run_release_command):
    result, events = run_release_command("release-fast")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "build" not in events
    assert not any(e.startswith("test_gate ") for e in events)
    assert "fast smoke" not in events and "fast evidence" not in events
    assert events.index("fast verify") < events.index("upload") < events.index("cutover")
    assert any("Release-Mode: fast" in e for e in events if e.startswith("git tag"))


@pytest.mark.parametrize("failure", ["verify", "main_ci", "tag_ci", "mode"])
def test_fast_publication_failure_does_not_fallback(run_release_command, failure):
    result, events = run_release_command("release-fast", failure=failure)
    assert result.returncode != 0
    assert "cutover" not in events and "build" not in events
    assert not any(e.startswith("test_gate ") for e in events)


@pytest.mark.parametrize("failure", ["", "evidence", "smoke", "artifact"])
def test_fast_preparation_is_local_and_builds_once(run_release_command, failure):
    result, events = run_release_command("prepare-fast", failure=failure,
                                         extra=("--gate-result", "/tmp/example-result.json"))
    assert result.returncode == (0 if not failure else 1), result.stdout + result.stderr
    assert events.count("build") == (0 if failure == "evidence" else 1)
    assert not any(e.startswith(("git push", "git tag -a", "gh ")) for e in events)
    assert "upload" not in events and "cutover" not in events
    assert all("--scope control" in e for e in events if e.startswith("test_gate "))
