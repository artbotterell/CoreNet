"""Tests for config loading and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.config import (
    BridgeConfig,
    NailedUpBridgeConfig,
    PeerConfig,
    RadioConfig,
    RouterConfig,
    load_config,
    load_config_from_dict,
)


MINIMAL_CONFIG = {
    "router": {
        "name": "bridge.lax.example.net",
        "short_tag": "LAX",
        "local_callsign": "BRIDGE-LAX",
    },
    "radio": {
        "type": "mock",
    },
}


class TestMinimalConfig:
    def test_loads(self):
        cfg = load_config_from_dict(MINIMAL_CONFIG)
        assert cfg.router.name == "bridge.lax.example.net"
        assert cfg.router.short_tag == "LAX"
        assert cfg.radio.type == "mock"

    def test_defaults(self):
        cfg = load_config_from_dict(MINIMAL_CONFIG)
        assert cfg.bridges == []
        assert cfg.peers == []
        assert cfg.radio.baudrate == 115200
        assert cfg.reticulum.display_name == "CoreNet Bridge"


class TestValidation:
    def test_serial_requires_port(self):
        with pytest.raises(Exception):
            load_config_from_dict({
                "router": {"name": "b"},
                "radio": {"type": "serial"},
            })

    def test_secret_must_be_hex(self):
        with pytest.raises(Exception):
            load_config_from_dict({
                "router": {"name": "b"},
                "radio": {"type": "mock"},
                "bridges": [{"name": "x", "secret": "not-hex"}],
            })

    def test_secret_must_be_16_bytes(self):
        with pytest.raises(Exception):
            load_config_from_dict({
                "router": {"name": "b"},
                "radio": {"type": "mock"},
                "bridges": [{"name": "x", "secret": "aa" * 8}],   # 8 bytes
            })

    def test_valid_secret(self):
        cfg = load_config_from_dict({
            "router": {"name": "b"},
            "radio": {"type": "mock"},
            "bridges": [{"name": "weather", "secret": "aa" * 16}],
        })
        assert len(cfg.bridges) == 1
        assert cfg.bridges[0].secret_bytes() == b"\xaa" * 16

    def test_peer_hash_must_be_hex(self):
        with pytest.raises(Exception):
            load_config_from_dict({
                "router": {"name": "b"},
                "radio": {"type": "mock"},
                "peers": [{"router_name": "p", "identity_hash": "not-hex"}],
            })


class TestLoadFromFile:
    def test_yaml_loader(self, tmp_path: Path):
        yaml_content = """
router:
  name: bridge.test.example.net
  short_tag: TEST
radio:
  type: mock
bridges:
  - name: corenet-wa
    secret: aabbccddeeff00112233445566778899
peers:
  - router_name: bridge.sea.example.net
    identity_hash: deadbeefcafebabe1122334455667788
"""
        p = tmp_path / "config.yaml"
        p.write_text(yaml_content)
        cfg = load_config(p)
        assert cfg.router.name == "bridge.test.example.net"
        assert len(cfg.bridges) == 1
        assert cfg.bridges[0].name == "corenet-wa"
        assert len(cfg.peers) == 1

    def test_toml_loader(self, tmp_path: Path):
        toml_content = """
[router]
name = "bridge.test.example.net"
short_tag = "TEST"

[radio]
type = "mock"
"""
        p = tmp_path / "config.toml"
        p.write_text(toml_content)
        cfg = load_config(p)
        assert cfg.router.name == "bridge.test.example.net"

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_unknown_extension(self, tmp_path: Path):
        p = tmp_path / "config.ini"
        p.write_text("junk")
        with pytest.raises(ValueError):
            load_config(p)


class TestHelpers:
    def test_secret_bytes_roundtrip(self):
        b = NailedUpBridgeConfig(name="x", secret="de" * 16)
        assert b.secret_bytes() == b"\xde" * 16

    def test_peer_hash_bytes_roundtrip(self):
        p = PeerConfig(router_name="r", identity_hash="be" * 16)
        assert p.hash_bytes() == b"\xbe" * 16
