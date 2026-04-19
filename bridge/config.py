"""Configuration loading and validation for the CoreNet bridge daemon.

Config is YAML or TOML; Pydantic validates structure and applies defaults.
Example (YAML):

    router:
      name: bridge.lax.example.net
      short_tag: LAX
      local_callsign: BRIDGE-LAX
      zone_description: Los Angeles metro

    radio:
      type: serial
      port: /dev/tty.usbmodem1101
      baudrate: 115200

    reticulum:
      config_dir: ~/.config/corenet/reticulum
      identity_path: ~/.config/corenet/identity
      storage_path: ~/.config/corenet/lxmf

    bridges:
      - name: corenet-wa
        secret: "aabbccdd...32hex"
        channel_idx: 3

    peers:
      - router_name: bridge.sea.example.net
        identity_hash: "deadbeef..."
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RouterConfig(BaseModel):
    name: str = Field(..., description="Fully-qualified router name (DNS-like)")
    short_tag: str | None = None
    local_callsign: str = "BRIDGE"
    zone_description: str = ""


class RadioConfig(BaseModel):
    type: Literal["serial", "mock"] = "serial"
    port: str | None = None
    baudrate: int = 115200

    @model_validator(mode="after")
    def _port_required_for_serial(self) -> "RadioConfig":
        if self.type == "serial" and not self.port:
            raise ValueError("radio.port is required when radio.type is 'serial'")
        return self


class ReticulumConfig(BaseModel):
    type: Literal["reticulum", "mock"] = "reticulum"
    config_dir: Path | None = None
    identity_path: Path | None = None
    storage_path: Path | None = None
    display_name: str = "CoreNet Bridge"


class NailedUpBridgeConfig(BaseModel):
    name: str
    secret: str = Field(..., description="Hex-encoded channel secret (16 bytes)")
    channel_idx: int | None = None

    @field_validator("secret")
    @classmethod
    def secret_is_hex(cls, v: str) -> str:
        try:
            raw = bytes.fromhex(v)
        except ValueError as e:
            raise ValueError(f"channel secret must be hex: {e}") from None
        if len(raw) != 16:
            raise ValueError(f"channel secret must be 16 bytes, got {len(raw)}")
        return v

    def secret_bytes(self) -> bytes:
        return bytes.fromhex(self.secret)


class PeerConfig(BaseModel):
    router_name: str
    identity_hash: str = Field(..., description="Hex-encoded identity hash")

    @field_validator("identity_hash")
    @classmethod
    def hash_is_hex(cls, v: str) -> str:
        try:
            bytes.fromhex(v)
        except ValueError as e:
            raise ValueError(f"identity_hash must be hex: {e}") from None
        return v

    def hash_bytes(self) -> bytes:
        return bytes.fromhex(self.identity_hash)


class BridgeConfig(BaseModel):
    """Top-level bridge daemon configuration."""
    router: RouterConfig
    radio: RadioConfig = Field(default_factory=RadioConfig)
    reticulum: ReticulumConfig = Field(default_factory=ReticulumConfig)
    bridges: list[NailedUpBridgeConfig] = Field(default_factory=list)
    peers: list[PeerConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> BridgeConfig:
    """Load a config from a YAML or TOML file.

    Dispatches on file extension.  Raises FileNotFoundError if missing,
    pydantic.ValidationError for invalid content.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")

    text = p.read_text()
    suffix = p.suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise ImportError("PyYAML is required for YAML configs") from e
        data = yaml.safe_load(text) or {}
    elif suffix == ".toml":
        try:
            import tomllib  # 3.11+
        except ImportError:   # pragma: no cover
            import tomli as tomllib   # type: ignore[no-redef]
        data = tomllib.loads(text)
    else:
        raise ValueError(f"unsupported config extension: {suffix}")

    return BridgeConfig.model_validate(data)


def load_config_from_dict(data: dict) -> BridgeConfig:
    """Load from an already-parsed dict (test convenience)."""
    return BridgeConfig.model_validate(data)
