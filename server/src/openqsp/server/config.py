"""Environment and dotenv configuration for the production server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path


class ConfigurationError(ValueError):
    """Operator configuration is missing or invalid."""


def load_dotenv(
    path: str | Path = ".env", *, environ: dict[str, str] | None = None
) -> None:
    """Load simple KEY=VALUE entries without replacing real environment values."""
    target = os.environ if environ is None else environ
    file = Path(path)
    if not file.is_file():
        return
    for number, raw in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigurationError(f"{file}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "A").isalnum():
            raise ConfigurationError(f"{file}:{number}: invalid variable name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        target.setdefault(key, value)


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _port(name: str, value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{name} must be between 1 and 65535")
    return port


@dataclass(frozen=True)
class ServerConfig:
    database: Path = Path("openqsp.db")
    tcp_enabled: bool = True
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 8023
    aprs_enabled: bool = False
    aprs_callsign: str | None = None
    aprs_passcode: str | None = None
    aprs_host: str = "rotate.aprs2.net"
    aprs_port: int = 14580
    aprs_filter: str | None = None

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ServerConfig":
        env = os.environ if environ is None else environ
        get = env.get
        config = cls(
            database=Path(get("OPENQSP_DATABASE", "openqsp.db")),
            tcp_enabled=_boolean(
                "OPENQSP_TCP_ENABLED", get("OPENQSP_TCP_ENABLED", "true")
            ),
            tcp_host=get("OPENQSP_TCP_HOST", "127.0.0.1"),
            tcp_port=_port("OPENQSP_TCP_PORT", get("OPENQSP_TCP_PORT", "8023")),
            aprs_enabled=_boolean(
                "OPENQSP_APRS_ENABLED", get("OPENQSP_APRS_ENABLED", "false")
            ),
            aprs_callsign=get("OPENQSP_APRS_CALLSIGN") or None,
            aprs_passcode=get("OPENQSP_APRS_PASSCODE") or None,
            aprs_host=get("OPENQSP_APRS_HOST", "rotate.aprs2.net"),
            aprs_port=_port("OPENQSP_APRS_PORT", get("OPENQSP_APRS_PORT", "14580")),
            aprs_filter=get("OPENQSP_APRS_FILTER") or None,
        )
        config.validate()
        return config

    def with_overrides(self, **values: object) -> "ServerConfig":
        result = replace(
            self, **{key: value for key, value in values.items() if value is not None}
        )
        result.validate()
        return result

    @property
    def effective_aprs_filter(self) -> str | None:
        return self.aprs_filter or (
            f"g/{self.aprs_callsign}" if self.aprs_callsign else None
        )

    def validate(self) -> None:
        _port("OPENQSP_TCP_PORT", str(self.tcp_port))
        _port("OPENQSP_APRS_PORT", str(self.aprs_port))
        if not self.tcp_enabled and not self.aprs_enabled:
            raise ConfigurationError("at least one transport must be enabled")
        if self.aprs_enabled and not self.aprs_callsign:
            raise ConfigurationError(
                "OPENQSP_APRS_CALLSIGN is required when APRS is enabled"
            )
        if self.aprs_enabled and not self.aprs_passcode:
            raise ConfigurationError(
                "OPENQSP_APRS_PASSCODE is required when APRS is enabled"
            )
