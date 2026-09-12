"""Exercise the actual CI shell commands without GitHub, Docker or builds."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/test-gate.yml").read_text()


def run_block(name):
    section = WORKFLOW.split(f"name: {name}\n", 1)[1]
    return textwrap.dedent(re.search(r"        run: \|\n((?:          .*\n|\n)+)", section)[1])


def fake_tools(tmp_path):
    stub = tmp_path / "python"
    stub.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        import json, os, pathlib, subprocess, sys
        args = sys.argv[1:]
        if args[0] == '-c':
            raise SystemExit(subprocess.call([sys.executable, *args]))
        with open(os.environ['CALLS'], 'a') as stream:
            stream.write(json.dumps(args) + '\\n')
        if args[0] == 'scripts/test_gate_ci.py':
            pathlib.Path(args[args.index('--output') + 1]).write_text(json.dumps({
                'ui_impacted': True, 'backend_impacted': True, 'frontend_impacted': True,
                'release_mode': os.environ.get('MODE', 'standard')}))
        print('{}')
        raise SystemExit(int(os.environ.get('FAIL_CONTROL', '0'))
                         if '--scope' in args and args[args.index('--scope') + 1] == 'control' else 0)
        '''))
    stub.chmod(0o700)
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    uv.chmod(0o700)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}",
               CALLS=str(tmp_path / "calls"), GITHUB_OUTPUT=str(tmp_path / "outputs"),
               GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
               BASE_SHA="a" * 40, HEAD_SHA="b" * 40, GATE_EVENT="push")
    return env


def execute(block, tmp_path, env, event="push"):
    block = block.replace('${{ github.event_name }}', event)
    block = block.replace('${{ github.event.inputs.release }}', 'false')
    block = block.replace('/tmp/', str(tmp_path) + '/')
    return subprocess.run(['bash', '-c', block], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("domain", ["backend", "frontend"])
@pytest.mark.parametrize("event,mode", [("pull_request", "targeted"), ("push", "full")])
def test_code_jobs_run_selected_mode_without_shared_controls(tmp_path, domain, event, mode):
    env = fake_tools(tmp_path)
    result = execute(run_block(f"Impacted PR or full main {domain} gate"), tmp_path, env, event)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(env['CALLS']).read_text().splitlines()]
    assert len(calls) == 1
    args = calls[0]
    assert args[args.index('--mode') + 1] == mode
    assert args[args.index('--scope') + 1] == domain
    assert '--skip-control' in args


@pytest.mark.parametrize("fail", [False, True])
def test_shared_control_failure_prevents_scheduling_outputs(tmp_path, fail):
    env = fake_tools(tmp_path)
    env['FAIL_CONTROL'] = '1' if fail else '0'
    result = execute(run_block('Generate impact plan and verify shared controls'), tmp_path, env)
    assert result.returncode == int(fail), result.stderr
    calls = [json.loads(line) for line in Path(env['CALLS']).read_text().splitlines()]
    assert sum('--scope' in args and 'control' in args for args in calls) == 1
    assert Path(env['GITHUB_OUTPUT']).exists() is not fail
    for job in ('backend-full', 'frontend-full', 'ui-e2e'):
        assert f'  {job}:\n    needs: impact\n' in WORKFLOW


@pytest.mark.parametrize("event,full", [("pull_request", False), ("push", True)])
def test_browser_gate_remains_complete_on_main(tmp_path, event, full):
    env = fake_tools(tmp_path)
    result = execute(run_block('UI impacted/final gate'), tmp_path, env, event)
    assert result.returncode == 0, result.stderr
    args = json.loads(Path(env['CALLS']).read_text())
    assert ('--full-e2e' in args) is full
    assert '--skip-control' in args


def test_tag_can_skip_controls_only_after_exact_main_verification():
    workflow = (ROOT / '.github/workflows/release-tag.yml').read_text()
    assert workflow.index('head_sha=$GITHUB_SHA&branch=main&event=push&status=success') < workflow.index('--skip-control')
    assert '--scope smoke --skip-control' in workflow


def test_fast_control_runs_only_lightweight_commands(tmp_path):
    env = fake_tools(tmp_path)
    env['MODE'] = 'fast'
    result = execute(run_block('Generate impact plan and verify shared controls'), tmp_path, env)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(env['CALLS']).read_text().splitlines()]
    assert [args[0] for args in calls] == [
        'scripts/test_gate_ci.py', 'scripts/test_gate.py',
        'scripts/release_mode.py', 'scripts/release_light_checks.py']
    assert 'release_mode=fast' in Path(env['GITHUB_OUTPUT']).read_text()
    for job in ('backend-full', 'frontend-full', 'ui-e2e'):
        section = WORKFLOW.split(f'  {job}:\n', 1)[1].split('    runs-on:', 1)[0]
        assert "needs.impact.outputs.release_mode != 'fast'" in section
    tag = (ROOT / '.github/workflows/release-tag.yml').read_text()
    assert tag.count("if: steps.identity.outputs.release_mode == 'standard'") == 3
