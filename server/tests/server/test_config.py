from pathlib import Path

import pytest
from openqsp.server.config import ConfigurationError, ServerConfig, load_dotenv


def test_defaults_and_environment_overrides() -> None:
    default = ServerConfig.from_environment({})
    assert default.database == Path("openqsp.db")
    assert default.tcp_enabled and not default.aprs_enabled
    configured = ServerConfig.from_environment(
        {
            "OPENQSP_DATABASE": "node.sqlite",
            "OPENQSP_TCP_ENABLED": "off",
            "OPENQSP_APRS_ENABLED": "YES",
            "OPENQSP_APRS_CALLSIGN": "NODE-1",
            "OPENQSP_APRS_PASSCODE": "external",
            "OPENQSP_APRS_PORT": "10152",
        }
    )
    assert configured.database == Path("node.sqlite")
    assert configured.effective_aprs_filter == "g/NODE-1"
    assert configured.aprs_port == 10152


@pytest.mark.parametrize("value", ["maybe", "enabled", "2"])
def test_invalid_boolean(value: str) -> None:
    with pytest.raises(ConfigurationError, match="true or false"):
        ServerConfig.from_environment({"OPENQSP_TCP_ENABLED": value})


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPENQSP_TCP_PORT", "0"),
        ("OPENQSP_APRS_PORT", "65536"),
        ("OPENQSP_TCP_PORT", "not-a-port"),
    ],
)
def test_invalid_ports(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        ServerConfig.from_environment({name: value})


def test_aprs_requires_credentials_and_a_transport() -> None:
    with pytest.raises(ConfigurationError, match="CALLSIGN"):
        ServerConfig.from_environment({"OPENQSP_APRS_ENABLED": "true"})
    with pytest.raises(ConfigurationError, match="PASSCODE"):
        ServerConfig.from_environment(
            {"OPENQSP_APRS_ENABLED": "true", "OPENQSP_APRS_CALLSIGN": "NODE"}
        )
    with pytest.raises(ConfigurationError, match="at least one"):
        ServerConfig.from_environment({"OPENQSP_TCP_ENABLED": "false"})


def test_dotenv_only_fills_missing_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\n\nOPENQSP_TCP_HOST=from-file\nQUOTED='value'\n")
    env = {"OPENQSP_TCP_HOST": "real-environment"}
    load_dotenv(dotenv, environ=env)
    assert env == {"OPENQSP_TCP_HOST": "real-environment", "QUOTED": "value"}


def test_cli_style_overrides_take_precedence() -> None:
    config = ServerConfig.from_environment({"OPENQSP_TCP_PORT": "9000"})
    assert config.with_overrides(tcp_port=9001).tcp_port == 9001
