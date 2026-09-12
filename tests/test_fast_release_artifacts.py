"""A prepared artifact cannot silently change source, image, checksum or target."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import release_fast as fast
from scripts import release_image_smoke as image_smoke
from scripts.release_mode import git
from scripts.test_gate_changes import GateConfigError
from scripts.test_gate_evidence import inputs


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text(".test-results/\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="horizon"\nversion="1.2.3"\n')
    (tmp_path / "uv.lock").write_text('[[package]]\nname="horizon"\nversion="1.2.3"\nsource={editable="."}\n')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "release\n\nRelease-Mode: fast")
    revision = git(tmp_path, "rev-parse", "HEAD")
    directory = tmp_path / ".test-results/fast-release" / revision
    directory.mkdir(parents=True)
    for name in ("source.tar.gz", "image.tar.gz"):
        (directory / name).write_bytes(name.encode())
    fast.write(directory / "evidence.json", dict(inputs=inputs(tmp_path), baseline=revision))
    fast.write(directory / "smoke.json", dict(ok=True, image_id="sha256:test"))
    metadata = {"Id": "sha256:test", "Architecture": "amd64", "Config": {"Labels": {
        "io.inteliscope.source.digest": "git:" + revision, "org.opencontainers.image.version": "1.2.3"}}}
    monkeypatch.setattr(fast, "docker", lambda *args: json.dumps([metadata]))
    monkeypatch.setattr(fast, "baseline", lambda host: revision)
    fast.seal(tmp_path, directory, "1.2.3-test", "inteliscope-service:1.2.3-test",
              "2026-09-12T00:00:00Z", "vps", "/opt/app", "https://example.invalid")
    return tmp_path, directory, metadata


def verify(prepared):
    root, directory, _ = prepared
    return fast.verify(root, directory, "vps", "/opt/app", "https://example.invalid")


def test_same_artifacts_are_reusable_without_test_or_build(prepared):
    assert verify(prepared)["mode"] == "fast"


def test_symlink_directory_is_rejected(prepared):
    root, directory, _ = prepared
    saved = directory.with_name("saved")
    directory.rename(saved)
    directory.symlink_to(saved, target_is_directory=True)
    with pytest.raises(GateConfigError, match="symlink"):
        verify(prepared)


def test_baseline_reads_only_identity_and_tracks_unknown_changes(monkeypatch):
    state = ["true|healthy|git:" + "a" * 40 + "|image1|api\n",
             "true|healthy|git:" + "a" * 40 + "|image1|worker\n"]
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "".join(state), "")
    monkeypatch.setattr(subprocess, "run", run)
    assert fast.baseline("vps") == "a" * 40
    state[0] = "true|healthy|missing|image2|api\n"
    first = fast.baseline("vps")
    state[0] = "true|healthy|missing|image3|api\n"
    assert first.startswith("unknown:") and fast.baseline("vps") != first
    assert all(".Env" not in str(args) for args in calls)


def test_unreachable_host_is_not_an_unknown_baseline(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 255, "", "offline"))
    with pytest.raises(GateConfigError, match="production containers"):
        fast.baseline("vps")


@pytest.mark.parametrize("change", ["source", "image", "archive", "evidence", "baseline", "target", "symlink"])
def test_changed_artifacts_fail(prepared, monkeypatch, change):
    root, directory, metadata = prepared
    if change == "source":
        (root / "new.py").write_text("new code")
    elif change == "image":
        metadata["Id"] = "sha256:other"
    elif change in {"archive", "evidence"}:
        (directory / ("image.tar.gz" if change == "archive" else "evidence.json")).write_text("changed")
    elif change == "baseline":
        monkeypatch.setattr(fast, "baseline", lambda host: "f" * 40)
    elif change == "symlink":
        (directory / "image.tar.gz").unlink()
        (directory / "image.tar.gz").symlink_to(directory / "source.tar.gz")
    else:
        data = json.loads((directory / "manifest.json").read_text())
        data["host"] = "other-host"
        (directory / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(GateConfigError):
        verify(prepared)


@pytest.mark.parametrize("healthy", [True, False])
def test_smoke_uses_pinned_image_and_cleans_only_its_container(tmp_path, monkeypatch, healthy):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/config.light.example.json").write_text('{}')
    calls = []
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ("image", "inspect"):
            return json.dumps([{"Id": "sha256:fixed", "Architecture": "amd64", "Os": "linux"}])
        if args[0] == "exec":
            if not healthy:
                raise subprocess.CalledProcessError(1, ["docker", *args])
            return json.dumps({"ok": True})
        return "created"
    monkeypatch.setattr(image_smoke, "docker", docker)
    if healthy:
        assert image_smoke.smoke(tmp_path, "image:tag")["image_id"] == "sha256:fixed"
    else:
        with pytest.raises(subprocess.CalledProcessError):
            image_smoke.smoke(tmp_path, "image:tag")
    run, kwargs = next((a, k) for a, k in calls if a[0] == "run")
    assert "sha256:fixed" in run and "--pull=never" in run
    assert "HORIZON_AUTH_PASSWORD" in run and kwargs["env"]["HORIZON_AUTH_PASSWORD"] not in run
    assert run[run.index("--network") + 1] == "none" and "-p" not in run
    assert calls[-1][0][:3] == ("rm", "-f", "-v")
    assert not any("build" in a or "horizon-light-api" in a or "horizon-worker" in a for a, _ in calls)
