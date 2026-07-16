"""Write-only local secret values backed by an atomically replaced env file."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

from dotenv import dotenv_values


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


class SecretValueError(ValueError):
    """A secret name or value is unsafe for the local secret file."""


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.RLock())


class SecretStore:
    """Persist secret values without returning them through public helpers."""

    def __init__(self, data_dir: Path | str, *, filename: str = "secrets.env") -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / filename
        self._lock = _lock_for(self.path)
        self._loaded_names: set[str] = set()

    @staticmethod
    def validate_env_name(env_name: str) -> str:
        value = str(env_name or "").strip()
        if not _ENV_NAME_RE.fullmatch(value):
            raise SecretValueError("env_name must be a valid environment variable name")
        return value

    @staticmethod
    def validate_value(value: str) -> str:
        secret = str(value or "")
        if not secret:
            raise SecretValueError("secret value must not be empty")
        if "\n" in secret or "\r" in secret or "\x00" in secret:
            raise SecretValueError("secret value must be a single non-null line")
        if len(secret) > 4096:
            raise SecretValueError("secret value must not exceed 4096 characters")
        return secret

    def read(self) -> dict[str, str]:
        with self._lock:
            if not self.path.exists():
                return {}
            values = dotenv_values(self.path)
            return {
                str(name): str(value)
                for name, value in values.items()
                if value is not None and _ENV_NAME_RE.fullmatch(str(name))
            }

    def status(self, env_name: str) -> dict[str, object]:
        name = self.validate_env_name(env_name)
        values = self.read()
        return {"env_name": name, "is_set": bool(values.get(name) or os.getenv(name))}

    def set(self, env_name: str, value: str) -> None:
        name = self.validate_env_name(env_name)
        secret = self.validate_value(value)
        with self._lock:
            values = self.read()
            values[name] = secret
            self._write(values)

    def delete(self, env_name: str) -> None:
        name = self.validate_env_name(env_name)
        with self._lock:
            values = self.read()
            values.pop(name, None)
            self._write(values)

    def load_into_environ(self) -> set[str]:
        with self._lock:
            values = self.read()
            removed = self._loaded_names - set(values)
            for name in removed:
                os.environ.pop(name, None)
            for name, value in values.items():
                os.environ[name] = value
            self._loaded_names = set(values)
            return set(values)

    def _write(self, values: dict[str, str]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.data_dir / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        payload = "".join(
            f"{name}={json.dumps(value, ensure_ascii=False)}\n"
            for name, value in sorted(values.items())
        )
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory_fd = os.open(self.data_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
