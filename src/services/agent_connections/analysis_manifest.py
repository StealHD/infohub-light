"""Derived ownership for one binding's managed analysis runtime."""
import hashlib
import re
from .manifest import validate_manifest


def objects(base):
    validate_manifest(base)
    identity = base['binding_id']
    return {'binding_id': identity, 'agent_id': 'ic-' + identity,
            'secret_ref': 'INTELISCOPE_CONNECTOR_' + identity.upper()}


def validate_token(base, token):
    if not isinstance(token, str) or not re.fullmatch(r'ih_ic_v1_' + base['binding_id'] + r'\.[A-Za-z0-9_-]{43}', token):
        raise ValueError('Analysis credential binding mismatch')
    return hashlib.sha256(token.encode()).hexdigest()
