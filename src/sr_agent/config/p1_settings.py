"""L0 config: typed accessors for the P1 extractor settings.

Every value has exactly one home (mysql_extract.yaml / p1.yaml); code reads
them through this module and nowhere else. Secrets resolve from the
environment only — a literal password in YAML is rejected.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"^\$\{(?P<name>[A-Z][A-Z0-9_]*)(?::(?P<default>.*))?\}$")


class ConfigError(ValueError):
    """A required setting is missing or malformed."""


def _resolve(value: str) -> str:
    """`${ENV}` / `${ENV:default}` → environment lookup with optional default."""
    m = _ENV_PATTERN.match(value.strip())
    if not m:
        return value
    env, default = m.group("name"), m.group("default")
    resolved = os.environ.get(env)
    if resolved is None:
        if default is not None:
            return default
        raise ConfigError(f"environment variable {env} is not set (required by mysql_extract.yaml)")
    return resolved


def _read(filename: str) -> dict[str, Any]:
    text = resources.files("sr_agent.config").joinpath(filename).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{filename}: expected a mapping at top level")
    return data


@dataclass(frozen=True)
class MysqlConfig:
    """Connection settings for the read-only extractor (§4.5.3 rev)."""

    host: str
    port: int
    user: str
    password: str
    database: str
    connect_timeout: int

    def dsn(self) -> str:  # pragma: no cover - trivial formatting
        return f"mysql://{self.user}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class TableExtract:
    """One table's extraction recipe (deterministic ORDER BY, fixed columns)."""

    name: str
    shadow_table: str | None
    chunk_by: str
    order_by: str
    columns: tuple[str, ...]


@lru_cache(maxsize=1)
def load_mysql_config() -> MysqlConfig:
    raw = _read("mysql_extract.yaml")["mysql"]
    host = _resolve(str(raw["host"]))
    user = _resolve(str(raw["user"]))
    password = _resolve(str(raw["password"]))
    if not host or not user or not password:
        raise ConfigError("mysql host/user/password must all resolve (env SR_MYSQL_*)")
    return MysqlConfig(
        host=host,
        port=int(_resolve(str(raw["port"]))),
        user=user,
        password=password,
        database=_resolve(str(raw["database"])),
        connect_timeout=int(raw["connect_timeout"]),
    )


@lru_cache(maxsize=1)
def load_table_extracts() -> dict[str, TableExtract]:
    raw = _read("mysql_extract.yaml")["tables"]
    out: dict[str, TableExtract] = {}
    for name, spec in raw.items():
        out[name] = TableExtract(
            name=name,
            shadow_table=spec.get("shadow_table"),
            chunk_by=spec["chunk_by"],
            order_by=spec["order_by"],
            columns=tuple(spec["columns"]),
        )
    return out


@lru_cache(maxsize=1)
def load_p1() -> dict[str, Any]:
    """p1.yaml as a plain dict (cached; treat as read-only)."""
    return _read("p1.yaml")["p1"]
