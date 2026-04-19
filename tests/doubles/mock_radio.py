"""MockRadio: a scriptable fake MeshCore radio for use in tests.

Provides:
  - inject_push(pkt_type, payload)   — push a response/push frame into the
                                        stream that the bridge's reader sees
  - expect_command(cmd_type)         — assert the next outbound command
  - canned_response(cmd_type, resp)  — auto-reply when a command is received

Usage::

    radio = MockRadio()
    radio.canned_response(CommandType.APP_START, b"\\x00")  # Ok

    # In test: drive the bridge, then inspect
    radio.inject_push(PacketType.ADVERTISEMENT, adv.pack())
    cmd_payload = await radio.next_command()
    assert cmd_payload[0] == CommandType.SEND_TXT_MSG
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from bridge.companion import frames as framing
from bridge.companion.types import CommandType, PacketType


class MockRadio:
    """Fake serial radio transport.  Thread-safe via asyncio queues."""

    def __init__(self) -> None:
        # Frames the bridge reads (radio → bridge direction)
        self._inbound: asyncio.Queue[tuple[bool, bytes]] = asyncio.Queue()
        # Raw command payloads the bridge wrote (bridge → radio direction)
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue()
        # Canned auto-replies: cmd_type → list of response payloads (FIFO)
        self._canned: defaultdict[int, list[bytes]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Test-side API
    # ------------------------------------------------------------------

    def inject_response(self, pkt_type: PacketType, payload: bytes = b"") -> None:
        """Push a response frame (radio → bridge) into the inbound queue."""
        self._inbound.put_nowait((True, bytes([pkt_type]) + payload))

    def inject_push(self, pkt_type: PacketType, payload: bytes = b"") -> None:
        """Alias for inject_response (pushes are also radio → bridge)."""
        self.inject_response(pkt_type, payload)

    def canned_response(self, cmd_type: CommandType, response_payload: bytes) -> None:
        """Register a response to auto-send when cmd_type is received."""
        self._canned[int(cmd_type)].append(response_payload)

    async def next_command(self, timeout: float = 2.0) -> bytes:
        """Wait for the next outbound command payload from the bridge."""
        return await asyncio.wait_for(self._outbound.get(), timeout=timeout)

    async def drain_commands(self) -> list[bytes]:
        """Return all pending commands without blocking."""
        cmds: list[bytes] = []
        while not self._outbound.empty():
            cmds.append(self._outbound.get_nowait())
        return cmds

    # ------------------------------------------------------------------
    # Bridge-side transport interface (implements RadioTransport protocol)
    # ------------------------------------------------------------------

    async def send_command(self, payload: bytes) -> None:
        """Called by the bridge to transmit a command to the radio."""
        await self._outbound.put(payload)
        # Auto-reply if a canned response is registered
        cmd_byte = payload[0] if payload else 0
        if self._canned[cmd_byte]:
            resp = self._canned[cmd_byte].pop(0)
            self._inbound.put_nowait((True, resp))

    async def read_frame(self) -> tuple[bool, bytes]:
        """Called by the bridge reader loop to get the next inbound frame."""
        return await self._inbound.get()

    async def read_frame_nowait(self) -> tuple[bool, bytes] | None:
        """Non-blocking variant; returns None if queue is empty."""
        try:
            return self._inbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ------------------------------------------------------------------
    # Assertions (convenience for tests)
    # ------------------------------------------------------------------

    async def assert_command(
        self, cmd_type: CommandType, timeout: float = 2.0
    ) -> bytes:
        """Assert that the next command is of the given type; return its payload."""
        payload = await self.next_command(timeout=timeout)
        assert payload[0] == int(cmd_type), (
            f"Expected command {cmd_type.name} (0x{int(cmd_type):02X}), "
            f"got 0x{payload[0]:02X}"
        )
        return payload

    def assert_no_pending_commands(self) -> None:
        assert self._outbound.empty(), (
            f"Expected no pending commands, found {self._outbound.qsize()}"
        )
