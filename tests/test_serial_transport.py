"""Tests for bridge/companion/serial_transport.py.

Uses an asyncio.StreamReader / StreamWriter pair backed by in-memory transport
objects so the tests run without any real serial hardware.
"""
from __future__ import annotations

import asyncio

import pytest

from bridge.companion import frames as framing
from bridge.companion.serial_transport import SerialRadioTransport


# ---------------------------------------------------------------------------
# Plumbing: a pair of asyncio.StreamReader/Writer backed by in-memory buffers
# ---------------------------------------------------------------------------

class _MemWriterTransport:
    """Minimal asyncio transport that records writes into a bytearray."""

    def __init__(self, sink: bytearray) -> None:
        self._sink = sink
        self._closed = False

    def write(self, data: bytes) -> None:
        self._sink.extend(data)

    def close(self) -> None:
        self._closed = True

    def is_closing(self) -> bool:
        return self._closed

    def get_extra_info(self, name: str, default=None) -> object:
        return default


def _make_streams() -> tuple[
    asyncio.StreamReader, asyncio.StreamWriter, bytearray
]:
    """Return (reader, writer, sink) where writes land in sink."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=65536)
    sink = bytearray()
    transport = _MemWriterTransport(sink)
    protocol = asyncio.StreamReaderProtocol(reader)

    # Patch close() so it triggers connection_lost → wait_closed returns promptly.
    original_close = transport.close
    def _close():
        original_close()
        loop.call_soon(protocol.connection_lost, None)
    transport.close = _close   # type: ignore[assignment]

    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer, sink


class TestSendCommand:
    async def test_payload_is_framed_and_written(self):
        reader, writer, sink = _make_streams()
        t = SerialRadioTransport(reader, writer)
        await t.start()

        await t.send_command(b"\x01\x02\x03")
        await asyncio.sleep(0)

        expected = framing.pack(b"\x01\x02\x03", response=False)
        assert bytes(sink) == expected

        await t.stop()

    async def test_multiple_commands_concatenate(self):
        reader, writer, sink = _make_streams()
        t = SerialRadioTransport(reader, writer)
        await t.start()

        await t.send_command(b"\x01")
        await t.send_command(b"\x02\x03")
        await asyncio.sleep(0)

        expected = framing.pack(b"\x01") + framing.pack(b"\x02\x03")
        assert bytes(sink) == expected

        await t.stop()

    async def test_send_after_stop_raises(self):
        reader, writer, _ = _make_streams()
        t = SerialRadioTransport(reader, writer)
        await t.start()
        await t.stop()
        with pytest.raises(RuntimeError):
            await t.send_command(b"\x01")

    async def test_double_start_rejected(self):
        reader, writer, _ = _make_streams()
        t = SerialRadioTransport(reader, writer)
        await t.start()
        with pytest.raises(RuntimeError):
            await t.start()
        await t.stop()


class TestReaderLoop:
    async def test_callback_fires_for_complete_frame(self):
        reader, writer, _ = _make_streams()
        received: list[tuple[bool, bytes]] = []

        async def cb(is_resp: bool, payload: bytes) -> None:
            received.append((is_resp, payload))

        t = SerialRadioTransport(reader, writer, frame_cb=cb)
        await t.start()

        # Simulate data arriving on the port
        frame = framing.pack(b"\x05hello", response=True)
        reader.feed_data(frame)
        await asyncio.sleep(0.01)   # let the reader task pick it up

        assert received == [(True, b"\x05hello")]

        await t.stop()

    async def test_fragmented_delivery(self):
        """Frames arriving split across reads still parse correctly."""
        reader, writer, _ = _make_streams()
        received: list[tuple[bool, bytes]] = []

        async def cb(is_resp: bool, payload: bytes) -> None:
            received.append((is_resp, payload))

        t = SerialRadioTransport(reader, writer, frame_cb=cb)
        await t.start()

        frame = framing.pack(b"\xAB\xCD\xEF")
        reader.feed_data(frame[:2])
        await asyncio.sleep(0.01)
        reader.feed_data(frame[2:])
        await asyncio.sleep(0.01)

        assert received == [(False, b"\xAB\xCD\xEF")]

        await t.stop()

    async def test_multiple_frames_back_to_back(self):
        reader, writer, _ = _make_streams()
        received: list[tuple[bool, bytes]] = []

        async def cb(is_resp: bool, payload: bytes) -> None:
            received.append((is_resp, payload))

        t = SerialRadioTransport(reader, writer, frame_cb=cb)
        await t.start()

        data = framing.pack(b"\x01") + framing.pack(b"\x02", response=True)
        reader.feed_data(data)
        await asyncio.sleep(0.01)

        assert received == [(False, b"\x01"), (True, b"\x02")]

        await t.stop()

    async def test_eof_terminates_reader(self):
        reader, writer, _ = _make_streams()
        t = SerialRadioTransport(reader, writer)
        await t.start()

        reader.feed_eof()
        await asyncio.sleep(0.02)

        # Reader task should have completed (stopped)
        assert t._reader_task.done()

        await t.stop()

    async def test_junk_bytes_tolerated(self):
        reader, writer, _ = _make_streams()
        received: list[tuple[bool, bytes]] = []

        async def cb(is_resp: bool, payload: bytes) -> None:
            received.append((is_resp, payload))

        t = SerialRadioTransport(reader, writer, frame_cb=cb)
        await t.start()

        # Leading garbage, then a valid frame
        reader.feed_data(b"\x00\xFF\xAA" + framing.pack(b"\x42"))
        await asyncio.sleep(0.01)

        assert received == [(False, b"\x42")]

        await t.stop()
