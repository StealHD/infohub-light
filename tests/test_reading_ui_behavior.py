from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_reading_ui_behavior_in_node():
    result = subprocess.run(
        ["node", "--test", "tests/reading_ui_behavior.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
