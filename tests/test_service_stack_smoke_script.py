from scripts.service_stack_smoke import build_report, run_stack_smoke


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


def test_stack_smoke_api_only_runs_compose_health_and_api_smoke():
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
    assert any("docker compose -f docker-compose.light.yml up -d --build horizon-api" in item for item in joined)
    assert any("scripts/service_api_smoke.py" in item for item in joined)
    assert not any("scripts/service_real_source_smoke.py" in item for item in joined)
    assert any(step["name"] == "real_source_smoke" and step["status"] == "skipped" for step in report["steps"])


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
