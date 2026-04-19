"""MockApp: records companion push frames delivered to the connected client app."""
from __future__ import annotations

import asyncio

from bridge.companion.types import PacketType


class MockApp:
    """Fake companion-app transport (implements AppTransport protocol)."""

    def __init__(self) -> None:
        self.received: list[bytes] = []    # raw push payloads (no frame header)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def push_frame(self, payload: bytes) -> None:
        self.received.append(payload)
        await self._queue.put(payload)

    async def next_frame(self, timeout: float = 2.0) -> bytes:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    async def drain(self) -> list[bytes]:
        frames: list[bytes] = []
        while not self._queue.empty():
            frames.append(self._queue.get_nowait())
        return frames

    def assert_received_type(self, pkt_type: PacketType) -> bytes:
        matching = [p for p in self.received if p and p[0] == int(pkt_type)]
        assert matching, (
            f"No frame of type {pkt_type.name} received. "
            f"Got types: {[PacketType.from_byte(p[0]).name for p in self.received if p]}"
        )
        return matching[-1]

    def reset(self) -> None:
        self.received.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
