"""Serial driver for the MeshCore companion protocol.

A SerialRadioTransport opens a serial port to a MeshCore radio (e.g. a T-Echo
on /dev/tty.usbmodem*), feeds inbound bytes through FrameReader, and dispatches
complete frames to a consumer callback.  Outbound commands are written to the
port after being wrapped by frames.pack().

The class is usable with any asyncio StreamReader/StreamWriter pair, which
makes it testable without a real serial port.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from bridge.companion import frames as framing

log = logging.getLogger(__name__)


FrameCallback = Callable[[bool, bytes], Awaitable[None]]
"""Async callback invoked for each complete frame: (is_response, payload)."""


class SerialRadioTransport:
    """Async companion-protocol transport over a serial port.

    Conforms to the RadioTransport protocol (send_command) and additionally
    runs a reader task that invokes `frame_cb` for each inbound frame.

    Lifecycle:

        transport = SerialRadioTransport(reader, writer, frame_cb=...)
        await transport.start()
        ...
        await transport.send_command(payload)
        ...
        await transport.stop()
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        frame_cb: FrameCallback | None = None,
        read_chunk: int = 1024,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._frame_cb = frame_cb
        self._read_chunk = read_chunk
        self._buf = framing.FrameReader()
        self._reader_task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        """Launch the reader task."""
        if self._reader_task is not None:
            raise RuntimeError("SerialRadioTransport already started")
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        """Cancel the reader task and close the writer."""
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        try:
            self._writer.close()
            # wait_closed can block indefinitely on some transports; bound it.
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._writer.wait_closed(), timeout=1.0)
        except Exception as e:   # pragma: no cover — depends on OS timing
            log.debug("writer close raised: %s", e)

    # ------------------------------------------------------------------
    # RadioTransport protocol
    # ------------------------------------------------------------------

    async def send_command(self, payload: bytes) -> None:
        """Pack `payload` into a 0x3C frame and write it to the port."""
        if self._closed:
            raise RuntimeError("SerialRadioTransport closed")
        framed = framing.pack(payload, response=False)
        self._writer.write(framed)
        await self._writer.drain()

    # ------------------------------------------------------------------
    # Reader loop
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Read bytes, feed the frame parser, dispatch complete frames."""
        try:
            while not self._closed:
                try:
                    chunk = await self._reader.read(self._read_chunk)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("serial read error: %s", e)
                    break
                if not chunk:
                    # EOF
                    break
                frames = self._buf.feed(chunk)
                for is_resp, payload in frames:
                    if self._frame_cb is not None:
                        try:
                            await self._frame_cb(is_resp, payload)
                        except Exception as e:   # pragma: no cover
                            log.exception("frame callback raised: %s", e)
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def open_serial(
        cls,
        port: str,
        baudrate: int = 115200,
        *,
        frame_cb: FrameCallback | None = None,
        **kwargs: Any,
    ) -> "SerialRadioTransport":
        """Open a real serial port via pyserial-asyncio and return a started transport.

        Requires the `pyserial-asyncio` package.  Any extra kwargs are passed
        through to the underlying serial connection.
        """
        import serial_asyncio   # local import so tests don't require it

        reader, writer = await serial_asyncio.open_serial_connection(
            url=port, baudrate=baudrate, **kwargs
        )
        transport = cls(reader, writer, frame_cb=frame_cb)
        await transport.start()
        return transport
