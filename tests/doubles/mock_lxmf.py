"""MockLxmfTransport: a recordable fake LXMF transport for use in tests.

Provides:
  - sent: list[LxmfMessage]       — all messages passed to send()
  - announces: list[...]          — all calls to announce()
  - inject(msg)                   — deliver an inbound message to all registered callbacks
  - assert_sent(transport, dest)  — convenience assertion

Usage::

    lxmf = MockLxmfTransport()
    router = Router(contacts, lxmf, local_hash="abc123")

    # Trigger a remote DM
    await router.handle_app_command(pack_send_txt_msg(remote_prefix, "hello"))

    assert len(lxmf.sent) == 1
    msg = lxmf.sent[0]
    assert msg.transport == LxmfTransport.PROPAGATED
    assert "abc123" in msg.destination
    assert msg.text == "hello"
"""
from __future__ import annotations

import asyncio

from bridge.companion.types import LxmfTransport, LxmfDestType
from bridge.lxmf_layer.transport import LxmfMessage, LxmfTransportBase, MessageCallback


class MockLxmfTransport(LxmfTransportBase):
    """In-memory LXMF transport.  No network, no RNS dependency."""

    def __init__(self) -> None:
        self.sent: list[LxmfMessage] = []
        self.announces: list[tuple[str, bytes]] = []   # (destination, app_data)
        self._callbacks: list[MessageCallback] = []
        self._announce_callbacks: list = []
        self._started = False

    # ------------------------------------------------------------------
    # LxmfTransportBase implementation
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send(self, msg: LxmfMessage) -> None:
        self.sent.append(msg)

    async def announce(self, destination: str, app_data: bytes) -> None:
        self.announces.append((destination, app_data))

    def add_inbound_callback(self, cb: MessageCallback) -> None:
        self._callbacks.append(cb)

    def add_announce_callback(self, cb) -> None:
        """Mirror of ReticulumLxmfTransport.add_announce_callback for tests."""
        self._announce_callbacks.append(cb)

    async def inject_announce(self, announce) -> None:
        """Simulate a peer-announce arrival."""
        for cb in self._announce_callbacks:
            await cb(announce)

    # ------------------------------------------------------------------
    # Test-side injection
    # ------------------------------------------------------------------

    async def inject(self, msg: LxmfMessage) -> None:
        """Simulate an inbound LXMF message arriving from the network."""
        for cb in self._callbacks:
            await cb(msg)

    async def inject_text(
        self,
        text: str,
        source: str = "remote_node_hash",
        destination: str = "meshcore.node.local",
        transport: LxmfTransport = LxmfTransport.PROPAGATED,
        app_data: dict | None = None,
    ) -> None:
        """Convenience: inject a plain text DM."""
        from bridge.lxmf_layer.transport import FIELD_TEXT, FIELD_APP_DATA
        fields = {FIELD_TEXT: text}
        if app_data:
            fields[FIELD_APP_DATA] = app_data
        msg = LxmfMessage(
            transport=transport,
            dest_type=LxmfDestType.NODE,
            destination=destination,
            source=source,
            fields=fields,
        )
        await self.inject(msg)

    async def inject_channel_text(
        self,
        text: str,
        ch_idx: int = 0,
        source: str = "remote_node_hash",
        channel_hash: str = "channel_hash",
    ) -> None:
        """Convenience: inject a channel message."""
        from bridge.lxmf_layer.transport import FIELD_TEXT, FIELD_APP_DATA
        import time as _time
        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.CHANNEL,
            destination=f"meshcore.channel.{channel_hash}",
            source=source,
            fields={
                FIELD_TEXT: text,
                FIELD_APP_DATA: {"ch_idx": ch_idx, "ts": int(_time.time()), "path_len": 1},
            },
        )
        await self.inject(msg)

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_sent_count(self, n: int) -> None:
        assert len(self.sent) == n, f"Expected {n} sent messages, got {len(self.sent)}"

    def assert_last_sent(
        self,
        *,
        transport: LxmfTransport | None = None,
        dest_contains: str | None = None,
        text: str | None = None,
    ) -> LxmfMessage:
        assert self.sent, "No messages were sent"
        msg = self.sent[-1]
        if transport is not None:
            assert msg.transport == transport, (
                f"Expected transport {transport.name}, got {msg.transport.name}"
            )
        if dest_contains is not None:
            assert dest_contains in msg.destination, (
                f"Expected '{dest_contains}' in destination '{msg.destination}'"
            )
        if text is not None:
            assert msg.text == text, f"Expected text {text!r}, got {msg.text!r}"
        return msg

    def assert_announced(self, dest_contains: str) -> None:
        matches = [d for d, _ in self.announces if dest_contains in d]
        assert matches, (
            f"No announce with '{dest_contains}' in destination. "
            f"Got: {[d for d, _ in self.announces]}"
        )

    def reset(self) -> None:
        self.sent.clear()
        self.announces.clear()
