"""Deployment-owned device key; browser never receives upstream credentials."""
import base64
import hashlib
import os
import time
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from .settings import SCOPES


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def load_key(path: Path) -> Ed25519PrivateKey:
    target = path / 'device.key'
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return Ed25519PrivateKey.from_private_bytes(target.read_bytes())
    key = Ed25519PrivateKey.generate()
    with os.fdopen(fd, 'wb') as output:
        output.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    return key


def connect_params(path: Path, token: str, nonce: str) -> dict:
    key = load_key(path)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    device_id = hashlib.sha256(public).hexdigest()
    now = int(time.time() * 1000)
    payload = '|'.join(['v3', device_id, 'gateway-client', 'backend', 'operator', ','.join(SCOPES), str(now), token, nonce, 'linux', 'server'])
    return {
        'minProtocol': 4, 'maxProtocol': 4,
        'client': {'id': 'gateway-client', 'version': 'infohub-relay-1', 'platform': 'linux', 'deviceFamily': 'server', 'mode': 'backend'},
        'role': 'operator', 'scopes': SCOPES, 'caps': ['tool-events'], 'auth': {'token': token},
        'device': {'id': device_id, 'publicKey': b64(public), 'signature': b64(key.sign(payload.encode())), 'signedAt': now, 'nonce': nonce},
    }
