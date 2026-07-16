import json
import stat

from scripts.service_stack_smoke import build_report, run_stack_smoke, wait_for_api_health, write_report


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, failures=None):
        self.commands = []
        self.failures = failures or {}

    def __call__(self, command):
        self.commands.append(command)
        name = command[-1] if command else ""
        for marker, result in self.failures.items():
            if marker in " ".join(command):
                return result
        return FakeResult(returncode=0, stdout=f"ran {name}")


def _healthy(_base_url, _timeout_seconds):
    return {"status": "passed", "message": "API health endpoint responded"}


def test_stack_health_check_uses_readiness_endpoint(monkeypatch):
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"ok":true,"data":{"status":"ready"}}'

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("scripts.service_stack_smoke.urllib.request.urlopen", fake_urlopen)

    result = wait_for_api_health("http://127.0.0.1:8080", timeout_seconds=1)

    assert result["status"] == "passed"
    assert seen == [("http://127.0.0.1:8080/api/health/ready", 5)]


def test_build_report_marks_failed_and_degraded_steps():
    report = build_report(
        [
            {"name": "compose_up", "status": "passed"},
            {"name": "real_source_smoke", "status": "degraded_optional"},
            {"name": "api_smoke", "status": "failed", "exit_code": 1},
        ]
    )

    assert report["ok"] is False
    assert report["summary"] == {
        "passed": 1,
        "failed": 1,
        "skipped": 0,
        "degraded_optional": 1,
    }
    assert report["failed"] == ["api_smoke"]


def test_stack_smoke_api_only_runs_api_without_worker_and_api_smoke():
    runner = FakeRunner()

    report = run_stack_smoke(
        compose_file="docker-compose.light.yml",
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        api_only=True,
        full_real_source=False,
        run_worker=False,
        runner=runner,
        health_checker=_healthy,
    )

    joined = [" ".join(command) for command in runner.commands]

    assert report["ok"] is True
    compose_up = next(item for item in joined if " up -d --build " in item)
    assert compose_up.endswith("docker-compose.light.yml up -d --build horizon-api")
    assert "horizon-worker" not in compose_up
    assert any("scripts/service_api_smoke.py" in item for item in joined)
    assert "secret-password" not in json.dumps(report)
    assert not any("scripts/service_real_source_smoke.py" in item for item in joined)
    assert any(step["name"] == "real_source_smoke" and step["status"] == "skipped" for step in report["steps"])


def test_api_only_ephemeral_stack_uses_project_and_always_cleans_up():
    runner = FakeRunner()

    report = run_stack_smoke(
        compose_file="docker-compose.test-gate.yml",
        base_url="http://127.0.0.1:18081",
        username="owner",
        password="secret-password",
        api_only=True,
        full_real_source=False,
        run_worker=False,
        project_name="test-gate-123",
        cleanup=True,
        report_dir=".test-results/test-gate-123",
        runner=runner,
        health_checker=_healthy,
    )

    joined = [" ".join(command) for command in runner.commands]
    assert report["ok"] is True
    assert joined[0].startswith(
        "docker compose -f docker-compose.test-gate.yml -p test-gate-123 up"
    )
    assert joined[-1].endswith(
        "-p test-gate-123 down --volumes --remove-orphans"
    )
    assert not any("horizon-worker" in command for command in joined)
    assert any(
        "--json-output .test-results/test-gate-123/service-api-smoke-latest.json" in command
        for command in joined
    )
    assert any(step["name"] == "compose_down" and step["status"] == "passed" for step in report["steps"])


def test_stack_report_is_private(tmp_path):
    output = tmp_path / "report.json"

    write_report(build_report([]), str(output))

    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_health_failure_collects_api_logs_before_ephemeral_cleanup():
    runner = FakeRunner()

    report = run_stack_smoke(
        compose_file="docker-compose.test-gate.yml",
        base_url="http://127.0.0.1:18081",
        username="owner",
        password="secret-password",
        api_only=True,
        full_real_source=False,
        run_worker=False,
        project_name="test-gate-logs",
        cleanup=True,
        runner=runner,
        health_checker=lambda *_args: {"status": "failed", "error": "not ready"},
    )

    joined = [" ".join(command) for command in runner.commands]
    logs_index = next(index for index, command in enumerate(joined) if " logs " in command)
    down_index = next(index for index, command in enumerate(joined) if " down " in command)
    assert logs_index < down_index
    assert joined[logs_index].endswith("logs --no-color --tail 120 horizon-api")
    assert any(step["name"] == "api_container_logs" for step in report["steps"])


def test_stack_smoke_full_real_source_runs_real_source_with_worker():
    runner = FakeRunner()

    report = run_stack_smoke(
        compose_file="docker-compose.light.yml",
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        api_only=False,
        full_real_source=True,
        run_worker=True,
        include_ui_smoke=False,
        runner=runner,
        health_checker=_healthy,
    )

    joined = [" ".join(command) for command in runner.commands]

    assert report["ok"] is True
    assert any("scripts/service_real_source_smoke.py" in item for item in joined)
    assert any("--run-worker" in item for item in joined)
    assert any(step["name"] == "worker_once" and step["status"] == "passed" for step in report["steps"])


def test_stack_smoke_can_include_ui_smoke_without_real_sources():
    runner = FakeRunner()

    report = run_stack_smoke(
        compose_file="docker-compose.light.yml",
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        api_only=True,
        full_real_source=False,
        run_worker=False,
        include_ui_smoke=True,
        runner=runner,
        health_checker=_healthy,
    )

    joined = [" ".join(command) for command in runner.commands]

    assert report["ok"] is True
    assert any("scripts/service_ui_smoke.py" in item for item in joined)
    assert any(step["name"] == "ui_smoke" and step["status"] == "passed" for step in report["steps"])


def test_stack_smoke_failed_child_command_records_command_and_exit_code():
    runner = FakeRunner(
        failures={
            "scripts/service_api_smoke.py": FakeResult(
                returncode=7,
                stdout="api smoke failed",
                stderr="bad auth",
            )
        }
    )

    report = run_stack_smoke(
        compose_file="docker-compose.light.yml",
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        api_only=True,
        full_real_source=False,
        run_worker=False,
        include_ui_smoke=False,
        runner=runner,
        health_checker=_healthy,
    )

    failed = next(step for step in report["steps"] if step["name"] == "api_smoke")

    assert report["ok"] is False
    assert failed["status"] == "failed"
    assert failed["exit_code"] == 7
    assert "scripts/service_api_smoke.py" in " ".join(failed["command"])
    assert failed["stderr"] == "bad auth"
