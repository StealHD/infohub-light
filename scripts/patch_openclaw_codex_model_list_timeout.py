"""Repair the active Codex plugin's isolated model-list deadline (explicit operator action)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


SUPPORTED_VERSION = '2026.9.3'
CALL_ANCHOR = '\t\tconst modelSelection = await resolveCodexBoundedTurnModel({\n\t\t\tclient,'
CALL_PATCH = CALL_ANCHOR + '\n\t\t\tmodelListTimeoutMs: params.taskLabel === "isolated completion" ? 30e3 : 5e3,'
DEADLINE_ANCHOR = 'timeoutMs: Math.min(params.timeoutMs, 5e3),'
DEADLINE_PATCH = 'timeoutMs: Math.min(params.timeoutMs, params.modelListTimeoutMs ?? 5e3),'


def active_package():
    result = subprocess.run(
        ['openclaw', 'plugins', 'inspect', 'codex', '--json'],
        capture_output=True, text=True, timeout=20, check=True,
    )
    plugin = json.loads(result.stdout)['plugin']
    if plugin.get('id') != 'codex' or plugin.get('status') != 'loaded':
        raise ValueError('The active Codex plugin is not loaded.')
    root = Path(plugin['rootDir']).resolve(strict=True)
    if Path(plugin['source']).resolve(strict=True) != root / 'dist' / 'index.js':
        raise ValueError('Unexpected active Codex plugin source.')
    return root


def patched_source(source):
    if source.count(CALL_PATCH) == 1 and source.count(DEADLINE_PATCH) == 1:
        return source
    if source.count(CALL_ANCHOR) != 1 or source.count(DEADLINE_ANCHOR) != 1:
        raise ValueError('Unreviewed Codex bounded-turn implementation; no changes made.')
    if 'modelListTimeoutMs' in source:
        raise ValueError('Existing model-list timeout change is not recognized.')
    return source.replace(CALL_ANCHOR, CALL_PATCH).replace(DEADLINE_ANCHOR, DEADLINE_PATCH)


def patch_package(package, apply=False):
    root = Path(package).resolve(strict=True)
    metadata = json.loads((root / 'package.json').read_text())
    if metadata.get('name') != '@openclaw/codex' or metadata.get('version') != SUPPORTED_VERSION:
        raise ValueError('Only the reviewed @openclaw/codex 2026.9.3 package is supported.')
    candidates = sorted(p for p in (root / 'dist').glob('bounded-turn-*.js')
                        if CALL_ANCHOR in p.read_text() or CALL_PATCH in p.read_text())
    if len(candidates) != 1 or candidates[0].is_symlink():
        raise ValueError('Expected one regular Codex bounded-turn implementation.')
    target = candidates[0]
    original = target.read_bytes()
    updated = patched_source(original.decode()).encode()
    status = 'already_patched' if updated == original else 'ready'
    if apply and updated != original:
        digest = hashlib.sha256(original).hexdigest()
        backup = target.with_name(target.name + '.inteliscope-' + digest[:12] + '.bak')
        with backup.open('xb') as stream:
            os.chmod(backup, 0o600)
            stream.write(original)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.codex-model-list-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, target.stat().st_mode & 0o777)
            if target.read_bytes() != original:
                raise ValueError('Codex package changed during patch; refusing overwrite.')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        status = 'patched_restart_required'
    return {'status': status, 'version': metadata['version'], 'path': str(target)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', help='Explicit package root; defaults to active OpenClaw plugin.')
    parser.add_argument('--apply', action='store_true', help='Patch with a private backup; Gateway restart remains explicit.')
    args = parser.parse_args()
    print(json.dumps(patch_package(args.package_root or active_package(), args.apply)))
