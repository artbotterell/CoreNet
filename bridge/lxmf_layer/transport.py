"""Abstract LXMF transport interface and LxmfMessage dataclass.

The real implementation wraps RNS + LXMF.  Tests use MockLxmfTransport from
tests/doubles/mock_lxmf.py, which records sends and allows injecting inbound
messages without touching a network socket.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field

from bridge.companion.types import LxmfTransport, LxmfDestType

# LXMF standard field IDs (matches NomadNetwork/Sideband convention)
FIELD_TEXT       = 0x01   # UTF-8 text body
FIELD_ATTACHMENT = 0x02   # file attachments
FIELD_IMAGE      = 0x03   # inline image
FIELD_AUDIO      = 0x04   # audio clip
FIELD_APP_DATA   = 0xFB   # msgpack dict — CoreNet namespace
FIELD_RAW_BINARY = 0xFC   # opaque binary


@dataclass
class LxmfMessage:
    """A message to be sent or received via LXMF.

    Fields are populated according to the encoding table in
    meshcore-lxmf-encoding.md.  transport and dest_type drive routing;
    fields carries the msgpack-encoded payload dict.
    """
    transport: LxmfTransport
    dest_type: LxmfDestType
    destination: str            # "meshcore.{node|bridge|channel}.<hash>"
    title: str = ""
    fields: dict = field(default_factory=dict)   # keyed by FIELD_* constants
    source: str = ""            # populated on inbound receipt
    timestamp: float = field(default_factory=time.time)

    # Convenience accessors
    @property
    def text(self) -> str | None:
        return self.fields.get(FIELD_TEXT)

    @property
    def app_data(self) -> dict | None:
        return self.fields.get(FIELD_APP_DATA)

    @property
    def raw_binary(self) -> bytes | None:
        return self.fields.get(FIELD_RAW_BINARY)


MessageCallback = Callable[[LxmfMessage], Awaitable[None]]


class LxmfTransportBase(ABC):
    """Abstract LXMF transport.

    The bridge holds one instance of this.  In production it wraps RNS/LXMF;
    in tests it is replaced by MockLxmfTransport.
    """

    @abstractmethod
    async def send(self, msg: LxmfMessage) -> None:
        """Deliver an outbound LXMF message (direct or propagated)."""

    @abstractmethod
    async def announce(self, destination: str, app_data: bytes) -> None:
        """Emit a Reticulum announce for the given destination."""

    @abstractmethod
    def add_inbound_callback(self, cb: MessageCallback) -> None:
        """Register a coroutine called for every inbound LXMF message."""

    @abstractmethod
    async def start(self) -> None:
        """Initialise Reticulum, load identity, open destinations."""

    @abstractmethod
    async def stop(self) -> None:
        """Shut down cleanly."""
