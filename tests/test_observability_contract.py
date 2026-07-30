from pathlib import Path

from scripts.check_observability_contract import (
    check_repository,
    source_violations,
)


ROOT = Path(__file__).resolve().parents[1]


def _codes(relative: str, source: str) -> set[str]:
    return {
        violation.code
        for violation in source_violations(relative, source)
    }


def test_repository_observability_contract_passes():
    assert check_repository(ROOT) == []


def test_contract_rejects_direct_output_and_unmanaged_uvicorn():
    source = """
MUTATION_OPERATION_ROUTES = {}
print("private")
uvicorn.run(app)
"""

    codes = _codes("src/api/server.py", source)

    assert {"OBS001", "OBS004"} <= codes


def test_contract_rejects_unmapped_api_mutation():
    source = """
MUTATION_OPERATION_ROUTES = {}

@app.post("/api/new-mutation")
async def mutate():
    return {}

uvicorn.run(app, log_config=None, access_log=False)
"""

    violations = source_violations("src/api/server.py", source)

    assert any(
        violation.code == "OBS005"
        and "POST /api/new-mutation" in violation.message
        for violation in violations
    )


def test_contract_rejects_worker_job_type_without_trace_policy():
    source = """
WORKER_JOB_TRACE_POLICY = {"known": "job_lifecycle_only"}

def _run_job(job):
    job_type = job["job_type"]
    if job_type == "known":
        return {}
    if job_type == "new_type":
        return {}
"""

    violations = source_violations("src/services/worker.py", source)

    assert any(
        violation.code == "OBS006"
        and "'new_type'" in violation.message
        for violation in violations
    )


def test_contract_detects_worker_job_types_in_membership_dispatch():
    source = """
WORKER_JOB_TRACE_POLICY = {"known": "job_lifecycle_only"}

def _run_job(job):
    job_type = job["job_type"]
    if job_type in {"known", "new_grouped_type"}:
        return {}
"""

    violations = source_violations("src/services/worker.py", source)

    assert any(
        violation.code == "OBS006"
        and "'new_grouped_type'" in violation.message
        for violation in violations
    )
