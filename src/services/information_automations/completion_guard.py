"""Persist ambiguous inference state rather than treating an HTTP timeout as a stop."""
import json
import os
import uuid


def path(journal):
    return journal.with_name('inference-state.json')


def uncertain(journal):
    marker = path(journal)
    if marker.is_symlink():
        raise ValueError('Unsafe inference marker')
    return marker.exists() and json.loads(marker.read_text()).get('state') != 'finished'


def record(journal, claim_id, agent_id, state):
    marker = path(journal)
    if marker.is_symlink() or marker.parent.resolve() != marker.parent:
        raise ValueError('Unsafe inference marker')
    marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = marker.with_name('.inference-' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'claim_id': claim_id, 'agent_id': agent_id, 'state': state}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)
