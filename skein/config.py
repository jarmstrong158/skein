"""Configuration loader. config.json is canonical; env vars override."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


_DEFAULTS = {
    "db_path": "./data/skein.db",
    "host": "127.0.0.1",
    "port": 5050,
    "default_task_timeout_seconds": 300,
    "artifact_inline_max_bytes": 65536,
    "artifact_storage_dir": "./data/artifacts",
}

_ENV_OVERRIDES = {
    "SKEIN_DB_PATH": ("db_path", str),
    "SKEIN_HOST": ("host", str),
    "SKEIN_PORT": ("port", int),
    "SKEIN_DEFAULT_TASK_TIMEOUT_SECONDS": ("default_task_timeout_seconds", int),
    "SKEIN_ARTIFACT_INLINE_MAX_BYTES": ("artifact_inline_max_bytes", int),
    "SKEIN_ARTIFACT_STORAGE_DIR": ("artifact_storage_dir", str),
}


@dataclass
class Config:
    db_path: str = _DEFAULTS["db_path"]
    host: str = _DEFAULTS["host"]
    port: int = _DEFAULTS["port"]
    default_task_timeout_seconds: int = _DEFAULTS["default_task_timeout_seconds"]
    artifact_inline_max_bytes: int = _DEFAULTS["artifact_inline_max_bytes"]
    artifact_storage_dir: str = _DEFAULTS["artifact_storage_dir"]

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        data = dict(_DEFAULTS)
        if path is not None:
            p = Path(path)
            if p.exists():
                data.update(json.loads(p.read_text()))
        for env_key, (field_name, caster) in _ENV_OVERRIDES.items():
            if env_key in os.environ:
                data[field_name] = caster(os.environ[env_key])
        return cls(**{k: data[k] for k in _DEFAULTS})
