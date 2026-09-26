"""Exercise the Gateway plugin with Node's native test runner, without a desktop."""
from pathlib import Path
import subprocess


def test_native_desktop_bridge_authorization_and_state_transitions():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', '--test', str(root / 'tests/openclaw_book_desktop.test.mjs')],
                            cwd=root, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
