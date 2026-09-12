"""Local fast-release evidence and immutable artifact manifest operations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.release_evidence import validate
from scripts.release_image_smoke import docker, smoke
from scripts.release_mode import git, version
from scripts.test_gate_changes import GateConfigError
from scripts.test_gate_evidence import inputs


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with temporary.open("x") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise GateConfigError(f"missing or unsafe prepared artifact: {path.name}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_directory(root: Path, directory: Path) -> None:
    relative = directory.absolute().relative_to(root.absolute())
    if relative.parts[:2] != (".test-results", "fast-release"):
        raise GateConfigError("prepared artifacts must be under .test-results/fast-release")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise GateConfigError("prepared artifact directory must not be a symlink")


def baseline(host: str) -> str:
    template = ('{{.State.Running}}|{{.State.Health.Status}}|'
                '{{index .Config.Labels "io.inteliscope.source.digest"}}|{{.Image}}|{{.Id}}')
    # Only non-secret labels and health are returned, never container Env.
    import shlex
    command = shlex.join(["docker", "inspect", "--format", template,
                          "horizon-light-api", "horizon-light-worker"])
    result = subprocess.run(["ssh", "-o", "ConnectTimeout=10", host, command],
                            capture_output=True, text=True, timeout=30)
    lines = result.stdout.strip().splitlines()
    if result.returncode or len(lines) != 2:
        raise GateConfigError("cannot read both production containers; retry when the host is reachable")
    identities = [line.split("|") for line in lines]
    if any(len(parts) != 5 for parts in identities):
        raise GateConfigError("invalid production identity response")
    if identities[0][:4] == identities[1][:4]:
        match = re.fullmatch(r"true\|healthy\|git:([0-9a-f]{40})", "|".join(identities[0][:3]))
        if match:
            return match[1]
    # Unknown revisions still retain a runtime identity, so an unknown ->
    # different unknown deployment cannot silently reuse prepared artifacts.
    return "unknown:" + hashlib.sha256(result.stdout.encode()).hexdigest()


def seal(root: Path, directory: Path, release_id: str, image: str, built_at: str,
         host: str, runtime: str, public_url: str) -> dict:
    check_directory(root, directory)
    metadata = json.loads(docker("image", "inspect", image))[0]
    report = json.loads((directory / "smoke.json").read_text())
    evidence = json.loads((directory / "evidence.json").read_text())
    revision = git(root, "rev-parse", "HEAD")
    labels = metadata["Config"]["Labels"]
    if (not report.get("ok") or metadata["Id"] != report.get("image_id")
            or metadata["Architecture"] != "amd64"
            or labels.get("io.inteliscope.source.digest") != "git:" + revision
            or labels.get("org.opencontainers.image.version") != version(root)
            or inputs(root) != evidence["inputs"]):
        raise GateConfigError("prepared source, image or smoke identity changed")
    manifest = dict(schema=1, mode="fast", revision=revision, version=version(root),
                    baseline=evidence["baseline"], inputs=evidence["inputs"],
                    image=image, image_id=metadata["Id"], release_id=release_id, built_at=built_at,
                    host=host, runtime=runtime, public_url=public_url,
                    hashes={name: file_hash(directory / name) for name in
                            ("source.tar.gz", "image.tar.gz", "evidence.json", "smoke.json")})
    write(directory / "manifest.json", manifest)
    return manifest


def verify(root: Path, directory: Path, host: str, runtime: str, public_url: str) -> dict:
    check_directory(root, directory)
    file_hash(directory / "manifest.json")
    manifest = json.loads((directory / "manifest.json").read_text())
    revision = git(root, "rev-parse", "HEAD")
    if (manifest.get("schema") != 1 or manifest.get("mode") != "fast"
            or manifest.get("revision") != revision or manifest.get("version") != version(root)
            or manifest.get("inputs") != inputs(root)
            or (manifest.get("host"), manifest.get("runtime"), manifest.get("public_url")) != (host, runtime, public_url)):
        raise GateConfigError("prepared release identity changed; run prepare-fast again")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", manifest["release_id"]):
        raise GateConfigError("invalid prepared release id")
    if (manifest["image"] != "inteliscope-service:" + manifest["release_id"]
            or not re.fullmatch(r"[0-9TZ:-]+", manifest["built_at"])):
        raise GateConfigError("invalid prepared image metadata")
    for name in ("source.tar.gz", "image.tar.gz", "evidence.json", "smoke.json"):
        if manifest.get("hashes", {}).get(name) != file_hash(directory / name):
            raise GateConfigError("prepared artifact checksum changed: " + name)
    if json.loads(docker("image", "inspect", manifest["image"]))[0]["Id"] != manifest["image_id"]:
        raise GateConfigError("prepared image missing or changed")
    if baseline(host) != manifest["baseline"]:
        raise GateConfigError("production baseline changed; run prepare-fast again")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("baseline", "evidence", "smoke", "seal", "verify"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--gate-result", type=Path)
    parser.add_argument("--e2e-result", type=Path)
    parser.add_argument("--baseline", default="unknown")
    parser.add_argument("--host", default="vps-tokyo")
    parser.add_argument("--runtime", default="/opt/inteliscope")
    parser.add_argument("--public-url", default="https://rb.jiefs.top")
    parser.add_argument("--image")
    parser.add_argument("--release-id")
    parser.add_argument("--built-at")
    args = parser.parse_args()
    try:
        if args.action == "baseline":
            print(baseline(args.host) or "unknown")
        elif args.action == "evidence":
            evidence = validate(ROOT, args.gate_result, args.e2e_result,
                                None if args.baseline.startswith("unknown") else args.baseline)
            evidence["baseline"] = args.baseline
            if args.directory is not None:
                write(args.directory / "evidence.json", evidence)
        elif args.action == "smoke":
            write(args.directory / "smoke.json", smoke(ROOT, args.image))
        elif args.action == "seal":
            seal(ROOT, args.directory, args.release_id, args.image, args.built_at,
                 args.host, args.runtime, args.public_url)
        else:
            data = verify(ROOT, args.directory, args.host, args.runtime, args.public_url)
            print(data["release_id"], data["image"], data["version"], data["built_at"])
        return 0
    except (OSError, ValueError, KeyError, TypeError, GateConfigError, subprocess.SubprocessError) as exc:
        print(f"fast release: {exc}; refresh local evidence and run prepare-fast explicitly", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
